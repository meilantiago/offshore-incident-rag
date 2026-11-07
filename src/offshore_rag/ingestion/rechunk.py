"""`run_rechunk`: build chunk sets for the stored documents from their stored pages (plan.md#Re-chunking).

No `PoliteClient` is involved, so no HTTP request is possible (AC-002-09). A document whose chunker raises
`ValueError` is reported as failed and the run goes on, as in `ingest`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

import structlog

from offshore_rag.ingestion.chunking import ChunkerPlan, DocType
from offshore_rag.ingestion.manifest import DOC_TYPES
from offshore_rag.ingestion.store import CorpusStore
from offshore_rag.ingestion.structure_aware import NOT_RECOGNIZED

log = structlog.get_logger()


@dataclass
class RechunkSummary:
    documents: int = 0
    chunks_created: dict[str, int] = field(default_factory=dict)
    unchanged_sets: int = 0
    not_recognized: list[tuple[str, str]] = field(default_factory=list)  # (source_url, doc_type)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (source_url, reason)
    duration_ms: dict[str, float] = field(default_factory=dict)
    total_ms: float = 0.0

    @property
    def has_failures(self) -> bool:
        return bool(self.failed)

    def format(self) -> str:
        lines = ["Re-chunking summary", f"  documents processed: {self.documents}"]
        lines.append("Chunks created per strategy")
        lines += [f"  {name}: {n}" for name, n in self.chunks_created.items()]
        lines.append(f"Unchanged chunk sets: {self.unchanged_sets}")
        lines.append(f"Structure not recognized: {len(self.not_recognized)}")
        lines += [f"  [{doc_type}] {url}" for url, doc_type in self.not_recognized]
        lines.append("Duration per strategy")
        lines += [f"  {name}: {ms:.0f} ms" for name, ms in self.duration_ms.items()]
        lines.append(f"Total duration: {self.total_ms:.0f} ms")
        if self.failed:
            lines.append("Failures")
            lines += [f"  {reason}: {url}" for url, reason in self.failed]
        return "\n".join(lines)


def run_rechunk(
    store: CorpusStore, plan: ChunkerPlan, clock: Callable[[], float] = time.perf_counter
) -> RechunkSummary:
    summary = RechunkSummary()
    start = clock()
    for doc in store.iter_stored_documents(DOC_TYPES):
        chunkers = plan.for_doc_type(doc.doc_type)
        if not chunkers:
            continue
        summary.documents += 1
        pages = store.load_pages(doc.id)
        try:
            for chunker in chunkers:
                t = clock()
                drafts = chunker.chunk(pages, cast(DocType, doc.doc_type))
                outcome = store.replace_chunk_set(doc.id, chunker, drafts)
                summary.duration_ms[chunker.id] = summary.duration_ms.get(chunker.id, 0.0) + (clock() - t) * 1000.0
                summary.chunks_created.setdefault(chunker.id, 0)
                if outcome == "created":
                    summary.chunks_created[chunker.id] += len(drafts)
                else:
                    summary.unchanged_sets += 1
                if any(d.section == NOT_RECOGNIZED for d in drafts) and (doc.source_url, doc.doc_type) not in (
                    summary.not_recognized
                ):
                    summary.not_recognized.append((doc.source_url, doc.doc_type))
        except ValueError as e:
            summary.failed.append((doc.source_url, f"{type(e).__name__}: {e}"))
            log.warning("rechunk_failed", url=doc.source_url, reason=str(e))
    summary.total_ms = (clock() - start) * 1000.0
    return summary
