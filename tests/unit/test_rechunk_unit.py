"""`CorpusStore.replace_chunk_set` and `run_rechunk` (spec 002 T08)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest

from offshore_rag.ingestion.chunking import ChunkerPlan, FixedWordChunker
from offshore_rag.ingestion.http import FetchResult
from offshore_rag.ingestion.manifest import ManifestEntry
from offshore_rag.ingestion.pdf import parse_pdf
from offshore_rag.ingestion.rechunk import run_rechunk
from offshore_rag.ingestion.store import CorpusStore
from offshore_rag.ingestion.structure_aware import StructureAwareChunker
from tests.conftest import PgSchema, migrate_schema
from tests.support import pdfs

pytestmark = pytest.mark.integration

URL = "https://example.test/a.pdf"


@pytest.fixture
def store(postgres: PgSchema) -> Iterator[CorpusStore]:
    migrate_schema(postgres)
    with psycopg.connect(postgres.url, autocommit=True) as conn:
        yield CorpusStore(conn)


def _ingest(store: CorpusStore, chunker: FixedWordChunker) -> int:
    data = pdfs.text_pdf(2)
    parsed = parse_pdf(data)
    store.save_document(
        ManifestEntry("safety_alert", URL, "https://example.test/l"),
        FetchResult(200, data, None, None, 1),
        "a" * 64,
        "raw/a.pdf",
        parsed,
        [(chunker, chunker.chunk(parsed.pages, "safety_alert"))],
        retrieved_at=datetime.now(UTC),
    )
    doc = store.get_document(URL)
    assert doc is not None
    return doc.id


def test_replace_chunk_set_is_unchanged_for_identical_params_and_keeps_ids(
    store: CorpusStore, postgres: PgSchema
) -> None:
    chunker = FixedWordChunker(size=50, overlap=10)
    doc_id = _ingest(store, chunker)
    before = postgres.rows("SELECT id, text FROM chunks ORDER BY id")
    pages = store.load_pages(doc_id)

    outcome = store.replace_chunk_set(doc_id, chunker, chunker.chunk(pages, "safety_alert"))

    assert outcome == "unchanged"
    assert postgres.rows("SELECT id, text FROM chunks ORDER BY id") == before


def test_replace_chunk_set_replaces_older_params(store: CorpusStore, postgres: PgSchema) -> None:
    doc_id = _ingest(store, FixedWordChunker(size=50, overlap=10))
    other = FixedWordChunker(size=60, overlap=0)

    outcome = store.replace_chunk_set(doc_id, other, other.chunk(store.load_pages(doc_id), "safety_alert"))

    assert outcome == "created"
    params = postgres.rows("SELECT DISTINCT chunker_params FROM chunks")
    assert params == [({"size": 60, "overlap": 0},)]


def test_run_rechunk_counts_per_strategy(store: CorpusStore, postgres: PgSchema) -> None:
    _ingest(store, FixedWordChunker(size=250, overlap=40))
    fixed = FixedWordChunker(size=250, overlap=40)
    plan = ChunkerPlan([fixed, StructureAwareChunker(size_cap=250)])

    first = run_rechunk(store, plan)
    created = postgres.scalar("SELECT count(*) FROM chunks WHERE chunker = 'structure_aware'")
    second = run_rechunk(store, plan)

    assert first.documents == 1 and first.unchanged_sets == 1 and not first.has_failures
    assert created > 0 and first.chunks_created == {"fixed_words": 0, "structure_aware": created}
    assert second.unchanged_sets == 2 and second.chunks_created == {"fixed_words": 0, "structure_aware": 0}
    assert postgres.scalar("SELECT count(*) FROM chunks WHERE chunker = 'structure_aware'") == created
    assert "documents processed: 1" in first.format()
