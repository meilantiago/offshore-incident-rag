"""`run_ingest`: download → parse → chunk → store for every manifest entry (plan.md#Ingestion run).

Documents are processed sequentially. A failure inside a document's stages (download error, robots.txt refusal,
hash mismatch, unreadable PDF, rejected rows) becomes that document's outcome and the run goes on (AC-001-10).
Errors outside a document's control (database connection lost, disk full) propagate: they are fatal for the run.

Parse and chunk run before the database transaction, so a failure at any stage leaves the stored version intact
(AC-001-09). Raw files are content-addressed under `DATA_DIR/raw/<sha256>.pdf` and written only for documents that
reach the store stage, so a mismatching or corrupt download leaves nothing on disk.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import psycopg
import structlog

from offshore_rag.ingestion.chunking import ChunkDraft, Chunker, ChunkerPlan, DocType
from offshore_rag.ingestion.http import FetchError, PoliteClient
from offshore_rag.ingestion.manifest import ManifestEntry
from offshore_rag.ingestion.pdf import PdfParseError, parse_pdf
from offshore_rag.ingestion.report import STAGES, DocumentOutcome, IngestionReport, Stage
from offshore_rag.ingestion.store import CorpusStore
from offshore_rag.ingestion.structure_aware import NOT_RECOGNIZED

log = structlog.get_logger()

RAW_DIR = "raw"


class _DocumentFailure(Exception):
    def __init__(self, stage: Stage, reason: str) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason


def run_ingest(
    entries: Sequence[ManifestEntry],
    client: PoliteClient,
    store: CorpusStore,
    plan: ChunkerPlan,
    data_dir: Path,
    clock: Callable[[], float] = time.perf_counter,
) -> IngestionReport:
    started_at = datetime.now(UTC)
    start = clock()
    requests0, retries0, bytes0 = client.requests, client.retries, client.bytes_downloaded
    outcomes: list[DocumentOutcome] = []
    for entry in entries:
        durations: dict[str, float] = dict.fromkeys(STAGES, 0.0)
        try:
            outcome = _process(entry, client, store, plan, data_dir, clock, durations)
        except _DocumentFailure as failure:
            outcome = DocumentOutcome(entry.source_url, "failed", stage=failure.stage, reason=failure.reason)
            log.warning("document_failed", url=entry.source_url, stage=failure.stage, reason=failure.reason)
        else:
            log.info("document_done", url=entry.source_url, status=outcome.status)
        outcome.durations_ms = durations
        outcomes.append(outcome)
    totals: dict[str, float] = {stage: sum(o.durations_ms.get(stage, 0.0) for o in outcomes) for stage in STAGES}
    return IngestionReport(
        started_at=started_at,
        manifest_entries=len(entries),
        documents=outcomes,
        durations_ms={"total": (clock() - start) * 1000.0, **totals},
        bytes_downloaded=client.bytes_downloaded - bytes0,
        requests=client.requests - requests0,
        retries=client.retries - retries0,
    )


def _process(
    entry: ManifestEntry,
    client: PoliteClient,
    store: CorpusStore,
    plan: ChunkerPlan,
    data_dir: Path,
    clock: Callable[[], float],
    durations: dict[str, float],
) -> DocumentOutcome:
    url = entry.source_url
    stored = store.get_document(url)

    # -- download -------------------------------------------------------------------------------------------
    t = clock()
    try:
        if not client.allowed(url):
            raise _DocumentFailure("download", "robots_disallowed")
        fetch = client.get(
            url,
            etag=stored.etag if stored else None,
            last_modified=stored.last_modified if stored else None,
        )
    except FetchError as e:
        raise _DocumentFailure("download", e.reason) from e
    finally:
        durations["download"] = (clock() - t) * 1000.0
    retrieved_at = datetime.now(UTC)
    if fetch.status == 304:
        if stored is None:
            raise _DocumentFailure("download", "http_304_without_stored_version")
        return DocumentOutcome(url, "skipped_unchanged")
    sha = hashlib.sha256(fetch.content).hexdigest()
    if entry.sha256 is not None and entry.sha256.lower() != sha:
        raise _DocumentFailure("download", "hash_mismatch")
    if stored is not None and stored.sha256 == sha:
        return DocumentOutcome(url, "skipped_unchanged")

    # -- parse ----------------------------------------------------------------------------------------------
    t = clock()
    try:
        parsed = parse_pdf(fetch.content)
    except PdfParseError as e:
        raise _DocumentFailure("parse", str(e)) from e
    finally:
        durations["parse"] = (clock() - t) * 1000.0

    # -- chunk ----------------------------------------------------------------------------------------------
    t = clock()
    chunk_sets: list[tuple[Chunker, list[ChunkDraft]]] = []
    chunk_ms: dict[str, float] = {}
    try:
        for chunker in plan.for_doc_type(entry.doc_type):
            t_chunker = clock()
            chunk_sets.append((chunker, chunker.chunk(parsed.pages, cast(DocType, entry.doc_type))))
            chunk_ms[chunker.id] = (clock() - t_chunker) * 1000.0
    except ValueError as e:
        raise _DocumentFailure("chunk", f"{type(e).__name__}: {e}") from e
    finally:
        durations["chunk"] = (clock() - t) * 1000.0

    # -- store ----------------------------------------------------------------------------------------------
    t = clock()
    try:
        raw_path = _write_raw(data_dir, sha, fetch.content)
        status = store.save_document(entry, fetch, sha, raw_path, parsed, chunk_sets, retrieved_at=retrieved_at)
    except (psycopg.IntegrityError, psycopg.DataError) as e:
        raise _DocumentFailure("store", " ".join(str(e).split())) from e
    finally:
        durations["store"] = (clock() - t) * 1000.0

    drafts = [d for _, ds in chunk_sets for d in ds]
    image_only_pages = sum(1 for p in parsed.pages if p.image_only)
    return DocumentOutcome(
        url,
        status,
        pages=parsed.page_count,
        chunks=len(drafts),
        image_only=image_only_pages == parsed.page_count,
        image_only_pages=image_only_pages,
        chunk_words=[len(d.text.split()) for d in drafts],
        doc_type=entry.doc_type,
        chunks_by_strategy={c.id: len(ds) for c, ds in chunk_sets},
        chunk_ms_by_strategy=chunk_ms,
        structure_not_recognized=any(d.section == NOT_RECOGNIZED for d in drafts),
    )


def _write_raw(data_dir: Path, sha: str, content: bytes) -> str:
    """Save the bytes as `DATA_DIR/raw/<sha256>.pdf` (temp file + rename); returns the path relative to DATA_DIR."""
    raw_dir = data_dir / RAW_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    target = raw_dir / f"{sha}.pdf"
    if not target.exists():
        fd, tmp = tempfile.mkstemp(dir=raw_dir, prefix=f".{sha}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return f"{RAW_DIR}/{sha}.pdf"
