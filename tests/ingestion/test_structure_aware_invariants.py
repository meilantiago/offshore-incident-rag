"""AC-002-08: invariants of every stored `structure_aware` chunk, checked against the stored pages.

The corpus is the three committed fixtures plus generated documents: a Form 2010 report with an image-only page
between two text pages (field 17 runs across it), an MMS "Notice No. 7" alert and the two unrecognized documents.
Removed content per document is written by hand in tests/support/structure.py (spec 002 #Definitions).
"""

from __future__ import annotations

import pytest

from tests.conftest import migrate_schema
from tests.support.ingest import EXIT_OK, IngestEnv, assert_exit
from tests.support.structure import (
    COMMITTED,
    FIXED,
    IMAGE_PAGE_DISTRICT,
    NOTICE_ALERT,
    STRUCTURE,
    UNRECOGNIZED_DISTRICT,
    UNRECOGNIZED_PANEL,
    Doc,
    assert_tiles,
    chunk_rows,
    kept_words,
    serve_docs,
    set_strategies,
)

pytestmark = pytest.mark.integration

CORPUS = [*COMMITTED, IMAGE_PAGE_DISTRICT, NOTICE_ALERT, UNRECOGNIZED_DISTRICT, UNRECOGNIZED_PANEL]


def _ingest_corpus(env: IngestEnv) -> dict[str, Doc]:
    migrate_schema(env.db)
    docs = serve_docs(env, CORPUS)
    set_strategies(env, [FIXED, STRUCTURE])
    assert_exit(env.ingest(), EXIT_OK)
    return docs


def test_ac_002_08_page_ranges_and_word_order_of_stored_chunks(db_env: IngestEnv) -> None:
    """AC-002-08: one document per chunk, 1 <= page_start <= page_end <= page count, first word from page_start,
    last from page_end, words in order and contiguous in the pages minus removed content, nothing skipped."""
    docs = _ingest_corpus(db_env)
    doc_ids = {r[0] for r in db_env.db.rows("SELECT id FROM documents")}

    for url, doc in docs.items():
        chunks = chunk_rows(db_env, url, STRUCTURE)
        assert chunks, f"{doc.name}: no structure_aware chunk stored"
        assert len({c["document_id"] for c in chunks}) == 1 and chunks[0]["document_id"] in doc_ids
        page_count = chunks[0]["page_count"]
        for c in chunks:
            assert 1 <= c["page_start"] <= c["page_end"] <= page_count, (
                f"{doc.name}: chunk {c['ordinal']} pages {c['page_start']}-{c['page_end']} of {page_count}"
            )
        stream = kept_words(db_env.pages(url), doc.removal)
        assert_tiles(chunks, stream, doc.name)


def test_ac_002_08_no_chunk_contains_text_from_an_image_only_page(db_env: IngestEnv) -> None:
    """AC-002-08: an image-only page is in no chunk's page range; a field running across it is cut there."""
    docs = _ingest_corpus(db_env)
    url = next(u for u, d in docs.items() if d is IMAGE_PAGE_DISTRICT)
    flags = {n: img for n, _, img in db_env.pages(url)}
    assert flags == {1: False, 2: False, 3: True, 4: False}, f"fixture precondition: page 3 is image-only: {flags}"

    chunks = chunk_rows(db_env, url, STRUCTURE)

    assert chunks, "no structure_aware chunk for the document with an image-only page"
    for c in chunks:
        assert not (c["page_start"] <= 3 <= c["page_end"]), (
            f"chunk {c['ordinal']} ({c.get('section')!r}) spans pages {c['page_start']}-{c['page_end']}, "
            "across the image-only page 3"
        )
    assert {c["page_start"] for c in chunks} >= {2, 4}, "both text pages of the narrative are chunked"
    for url_all, doc in docs.items():
        image_pages = {n for n, _, img in db_env.pages(url_all) if img}
        for c in chunk_rows(db_env, url_all, STRUCTURE):
            assert not image_pages & set(range(c["page_start"], c["page_end"] + 1)), (
                f"{doc.name}: chunk {c['ordinal']} covers image-only pages"
            )
