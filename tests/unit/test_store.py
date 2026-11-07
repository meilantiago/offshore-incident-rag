"""`CorpusStore`: atomic insert and replacement, one row per URL, `counts()` (T10)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from offshore_rag.ingestion.chunking import ChunkDraft, FixedWordChunker
from offshore_rag.ingestion.http import FetchResult
from offshore_rag.ingestion.manifest import ManifestEntry
from offshore_rag.ingestion.pdf import parse_pdf
from offshore_rag.ingestion.store import CorpusCounts, CorpusStore
from tests.conftest import PgSchema, migrate_schema
from tests.support import pdfs

pytestmark = pytest.mark.integration

URL = "https://example.test/a.pdf"
ENTRY = ManifestEntry("safety_alert", URL, "https://example.test/listing")


@pytest.fixture
def store(postgres: PgSchema) -> Iterator[CorpusStore]:
    migrate_schema(postgres)
    with psycopg.connect(postgres.url, autocommit=True) as conn:
        yield CorpusStore(conn)


def _fetch(data: bytes, etag: str | None = None) -> FetchResult:
    return FetchResult(200, data, etag, None, 1)


def _save(store: CorpusStore, data: bytes, sha: str, chunker: FixedWordChunker | None = None) -> str:
    parsed = parse_pdf(data)
    chunker = chunker or FixedWordChunker(size=50, overlap=10)
    return store.save_document(
        ENTRY,
        _fetch(data, etag=f'"{sha}"'),
        sha,
        f"raw/{sha}.pdf",
        parsed,
        [(chunker, chunker.chunk(parsed.pages, "safety_alert"))],
        retrieved_at=datetime.now(UTC),
    )


def _dump(pg: PgSchema) -> dict[str, Any]:
    return {
        "documents": pg.rows("SELECT * FROM documents ORDER BY id"),
        "pages": pg.rows("SELECT * FROM pages ORDER BY document_id, page_number"),
        "chunks": pg.rows("SELECT * FROM chunks ORDER BY id"),
    }


def test_insert_then_replace_keeps_one_row_and_new_content(store: CorpusStore, postgres: PgSchema) -> None:
    assert store.get_document(URL) is None
    assert _save(store, pdfs.text_pdf(3, tag="VERSION-A"), "a" * 64) == "ingested"
    first = store.get_document(URL)
    assert first is not None and first.sha256 == "a" * 64 and first.etag == f'"{"a" * 64}"'
    old_chunks = {r[0] for r in postgres.rows("SELECT id FROM chunks")}

    assert _save(store, pdfs.text_pdf(2, tag="VERSION-B"), "b" * 64) == "replaced"

    stored = store.get_document(URL)
    assert stored is not None and stored.id == first.id and stored.sha256 == "b" * 64
    assert postgres.scalar("SELECT count(*) FROM documents") == 1
    assert postgres.scalar("SELECT page_count FROM documents") == 2
    texts = [r[0] for r in postgres.rows("SELECT text FROM pages ORDER BY page_number")]
    assert len(texts) == 2 and all("VERSION-B" in t and "VERSION-A" not in t for t in texts)
    new_chunks = {r[0] for r in postgres.rows("SELECT id FROM chunks")}
    assert new_chunks and not new_chunks & old_chunks
    params = postgres.rows("SELECT DISTINCT chunker, chunker_params FROM chunks")
    assert params == [("fixed_words", {"size": 50, "overlap": 10})]


def test_failure_mid_transaction_leaves_previous_version_identical(store: CorpusStore, postgres: PgSchema) -> None:
    _save(store, pdfs.text_pdf(3, tag="VERSION-A"), "a" * 64)
    before = _dump(postgres)
    parsed = parse_pdf(pdfs.text_pdf(2, tag="VERSION-B"))
    chunker = FixedWordChunker(size=50, overlap=10)
    broken = [*chunker.chunk(parsed.pages, "safety_alert"), ChunkDraft(999, 1, 1, "")]  # empty text violates a CHECK

    with pytest.raises(psycopg.IntegrityError):
        store.save_document(
            ENTRY, _fetch(b"x"), "b" * 64, "raw/b.pdf", parsed, [(chunker, broken)], retrieved_at=datetime.now(UTC)
        )

    assert _dump(postgres) == before


def test_counts_match_rows(store: CorpusStore, postgres: PgSchema) -> None:
    assert store.counts() == CorpusCounts(0, 0, 0)
    _save(store, pdfs.text_pdf(3), "a" * 64)
    assert store.counts() == CorpusCounts(
        postgres.scalar("SELECT count(*) FROM documents"),
        postgres.scalar("SELECT count(*) FROM pages"),
        postgres.scalar("SELECT count(*) FROM chunks"),
    )
    assert store.counts().pages == 3


def test_image_only_document_has_pages_and_no_chunks(store: CorpusStore, postgres: PgSchema) -> None:
    data = pdfs.image_only_pdf(2)
    _save(store, data, "c" * 64)
    assert postgres.scalar("SELECT image_only FROM documents") is True
    assert postgres.rows("SELECT page_number, image_only FROM pages ORDER BY 1") == [(1, True), (2, True)]
    assert postgres.scalar("SELECT count(*) FROM chunks") == 0
