"""CorpusStore: documents, pages and chunks in Postgres, written atomically (plan.md#Store, #Replacement).

The connection is in autocommit mode; every write runs in its own explicit transaction, so a failure at any point of
`save_document` leaves the previous version of the document untouched.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import psycopg

from offshore_rag.ingestion.chunking import ChunkDraft, Chunker
from offshore_rag.ingestion.http import FetchResult
from offshore_rag.ingestion.manifest import ManifestEntry
from offshore_rag.ingestion.pdf import ParsedPdf

ChunkSets = Sequence[tuple[Chunker, Sequence[ChunkDraft]]]


@dataclass(frozen=True)
class StoredDocument:
    id: int
    source_url: str
    sha256: str
    etag: str | None
    last_modified: str | None
    raw_path: str


@dataclass(frozen=True)
class CorpusCounts:
    documents: int
    pages: int
    chunks: int


class CorpusStore:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def get_document(self, source_url: str) -> StoredDocument | None:
        row = self._conn.execute(
            "SELECT id, source_url, sha256, etag, last_modified, raw_path FROM documents WHERE source_url = %s",
            (source_url,),
        ).fetchone()
        if row is None:
            return None
        return StoredDocument(*row)

    def save_document(
        self,
        entry: ManifestEntry,
        fetch: FetchResult,
        sha256: str,
        raw_path: str,
        parsed: ParsedPdf,
        chunks_by_chunker: ChunkSets,
        *,
        retrieved_at: datetime,
    ) -> Literal["ingested", "replaced"]:
        """Insert a new document or replace the stored one, with its pages and chunks, in one transaction."""
        image_only = all(p.image_only for p in parsed.pages)
        values = (
            entry.doc_type,
            entry.listing_url,
            sha256,
            retrieved_at,
            fetch.etag,
            fetch.last_modified,
            raw_path,
            parsed.page_count,
            image_only,
        )
        with self._conn.transaction(), self._conn.cursor() as cur:
            row = cur.execute(
                "SELECT id FROM documents WHERE source_url = %s FOR UPDATE", (entry.source_url,)
            ).fetchone()
            outcome: Literal["ingested", "replaced"]
            if row is None:
                inserted = cur.execute(
                    "INSERT INTO documents (doc_type, listing_url, sha256, retrieved_at, etag, last_modified, "
                    "raw_path, page_count, image_only, source_url) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (*values, entry.source_url),
                ).fetchone()
                assert inserted is not None  # RETURNING always yields the new row
                document_id = int(inserted[0])
                outcome = "ingested"
            else:
                document_id = int(row[0])
                cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
                cur.execute("DELETE FROM pages WHERE document_id = %s", (document_id,))
                cur.execute(
                    "UPDATE documents SET doc_type = %s, listing_url = %s, sha256 = %s, retrieved_at = %s, "
                    "etag = %s, last_modified = %s, raw_path = %s, page_count = %s, image_only = %s, "
                    "updated_at = now() WHERE id = %s",
                    (*values, document_id),
                )
                outcome = "replaced"
            with cur.copy("COPY pages (document_id, page_number, text, image_only, char_count) FROM STDIN") as copy:
                for page in parsed.pages:
                    copy.write_row((document_id, page.number, page.text, page.image_only, len(page.text)))
            with cur.copy(
                "COPY chunks (document_id, chunker, chunker_params, ordinal, page_start, page_end, text, "
                "char_count, word_count) FROM STDIN"
            ) as copy:
                for chunker, drafts in chunks_by_chunker:
                    params = json.dumps(dict(chunker.params), sort_keys=True)
                    for d in drafts:
                        copy.write_row(
                            (
                                document_id,
                                chunker.id,
                                params,
                                d.ordinal,
                                d.page_start,
                                d.page_end,
                                d.text,
                                len(d.text),
                                len(d.text.split()),
                            )
                        )
        return outcome

    def counts(self) -> CorpusCounts:
        row = self._conn.execute(
            "SELECT (SELECT count(*) FROM documents), (SELECT count(*) FROM pages), (SELECT count(*) FROM chunks)"
        ).fetchone()
        assert row is not None
        return CorpusCounts(int(row[0]), int(row[1]), int(row[2]))
