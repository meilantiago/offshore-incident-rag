"""AC-001-07: chunk invariants (document, strategy, page range, text, coverage) and separate chunk sets.

As amended by spec 002: the substring and coverage clauses apply to `fixed_words` chunk sets only; chunks of other
strategies meet the guarantees of the spec that defines them (for `structure_aware`, AC-002-08, tested in
tests/ingestion/test_structure_aware_invariants.py).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import psycopg
import pytest

from tests.conftest import migrate_schema
from tests.support import pdfs
from tests.support.ingest import EXIT_OK, REAL_ALERT_PDF, TEST_USER_AGENT, IngestEnv, assert_exit, norm_ws


def _check_chunk_set(
    chunks: list[dict[str, Any]], pages: dict[int, tuple[str, bool]], page_count: int, label: str, chunker: str
) -> None:
    """Invariants of AC-001-07 for one document and one (chunker, params) set.

    Every strategy: chunks, unique ordinals, a valid page range and non-empty text. `fixed_words` only: the text is
    found in the concatenated text of its pages, and every page with extractable text is covered.
    """
    assert chunks, f"{label}: no chunks"
    ordinals = [c["ordinal"] for c in chunks]
    assert len(ordinals) == len(set(ordinals)), f"{label}: repeated ordinals {ordinals}"
    covered: set[int] = set()
    for c in chunks:
        ps, pe = c["page_start"], c["page_end"]
        assert 1 <= ps <= pe <= page_count, f"{label}: bad page range {ps}..{pe} of {page_count}"
        text = norm_ws(c["text"])
        assert text, f"{label}: empty chunk {c['ordinal']}"
        covered.update(range(ps, pe + 1))
        if chunker != "fixed_words":
            continue
        window = norm_ws(" ".join(pages[n][0] for n in range(ps, pe + 1)))
        assert text in window, f"{label}: chunk {c['ordinal']} text not found in pages {ps}..{pe}"
    if chunker != "fixed_words":
        return
    text_pages = {n for n, (t, image_only) in pages.items() if not image_only and t.strip()}
    assert text_pages <= covered, f"{label}: pages with text not covered by any chunk: {sorted(text_pages - covered)}"


def test_ac_001_07_fixed_word_chunker_invariants() -> None:
    """AC-001-07: FixedWordChunker records its id and params, keeps page ranges and covers every text page."""
    from offshore_rag.ingestion.chunking import FixedWordChunker
    from offshore_rag.ingestion.pdf import parse_pdf

    parsed = parse_pdf(pdfs.text_pdf(4, words_per_page=120))
    chunker = FixedWordChunker(size=50, overlap=10)

    drafts = chunker.chunk(parsed.pages, "safety_alert")

    assert chunker.id and isinstance(chunker.id, str)
    assert dict(chunker.params) == {"size": 50, "overlap": 10}
    pages = {p.number: (p.text, p.image_only) for p in parsed.pages}
    rows = [{"ordinal": d.ordinal, "page_start": d.page_start, "page_end": d.page_end, "text": d.text} for d in drafts]
    _check_chunk_set(rows, pages, 4, "unit", chunker.id)
    assert any(d.page_start < d.page_end for d in drafts), "a window crossing a page break spans both pages"


def _db_check_all(env: IngestEnv) -> None:
    chunks = env.chunks()
    assert chunks, "no chunk stored"
    doc_ids = {r[0] for r in env.db.rows("SELECT id FROM documents")}
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for c in chunks:
        assert c["document_id"] in doc_ids, "every chunk belongs to a stored document"
        assert c["chunker"], "chunk without strategy id"
        assert isinstance(c["chunker_params"], dict) and c["chunker_params"], "chunk without strategy parameters"
        key = (c["source_url"], c["chunker"], repr(sorted(c["chunker_params"].items())))
        groups[key].append(c)
    for (url, chunker, params), group in groups.items():
        pages = {n: (t, img) for n, t, img in env.pages(url)}
        _check_chunk_set(group, pages, group[0]["page_count"], f"{url} {chunker} {params}", chunker)


@pytest.mark.integration
def test_ac_001_07_stored_chunks_satisfy_invariants(db_env: IngestEnv) -> None:
    """AC-001-07: every stored chunk has one document, strategy + params, a valid page range and real text."""
    migrate_schema(db_env.db)
    a = db_env.serve_pdf("/sites/bsee.gov/files/six.pdf", pdfs.text_pdf(6, words_per_page=150))
    b = db_env.serve_pdf("/sites/bsee.gov/files/469.pdf", REAL_ALERT_PDF.read_bytes())
    c = db_env.serve_pdf("/sites/bsee.gov/files/one.pdf", pdfs.text_pdf(1, words_per_page=20))
    db_env.write_manifest(
        [
            db_env.entry(p)
            for p in ("/sites/bsee.gov/files/six.pdf", "/sites/bsee.gov/files/469.pdf", "/sites/bsee.gov/files/one.pdf")
        ]
    )

    assert_exit(db_env.ingest(), EXIT_OK)

    _db_check_all(db_env)
    for url in (a, b, c):
        assert {ch["chunker"] for ch in db_env.chunks(url)} == {"fixed_words"}, "CHUNKERS=fixed_words"
    assert any(ch["page_start"] < ch["page_end"] for ch in db_env.chunks(a)), "some chunk spans a page break"


@pytest.mark.integration
def test_ac_001_07_two_strategies_coexist_without_mixing(db_env: IngestEnv) -> None:
    """AC-001-07: chunk sets of two strategies for the same document are stored side by side, each intact."""
    from offshore_rag.ingestion.chunking import ChunkerPlan, FixedWordChunker
    from offshore_rag.ingestion.http import PoliteClient
    from offshore_rag.ingestion.manifest import load_manifest
    from offshore_rag.ingestion.pdf import parse_pdf
    from offshore_rag.ingestion.pipeline import run_ingest
    from offshore_rag.ingestion.store import CorpusStore

    migrate_schema(db_env.db)
    data = pdfs.text_pdf(5, words_per_page=140)
    url = db_env.serve_pdf("/sites/bsee.gov/files/five.pdf", data)
    db_env.write_manifest([db_env.entry("/sites/bsee.gov/files/five.pdf")])
    big, small = FixedWordChunker(size=250, overlap=40), FixedWordChunker(size=60, overlap=5)

    with psycopg.connect(db_env.db.url, autocommit=True) as conn:
        client = PoliteClient(user_agent=TEST_USER_AGENT, rate_per_second=50, max_retries=0, timeout=5)
        report = run_ingest(
            entries=load_manifest(db_env.manifest_path),
            client=client,
            store=CorpusStore(conn),
            plan=ChunkerPlan([big, small]),
            data_dir=db_env.data_dir,
        )

    assert [o.status for o in report.documents] == ["ingested"]
    _db_check_all(db_env)
    stored = db_env.chunks(url)
    pages = parse_pdf(data).pages
    for chunker in (big, small):
        mine = [c for c in stored if c["chunker"] == chunker.id and c["chunker_params"] == dict(chunker.params)]
        expected = [(d.ordinal, d.page_start, d.page_end, d.text) for d in chunker.chunk(pages, "safety_alert")]
        got = [(c["ordinal"], c["page_start"], c["page_end"], c["text"]) for c in mine]
        assert sorted(got) == sorted(expected), f"chunk set {chunker.params} mixed with another or incomplete"
    assert len(stored) == len(big.chunk(pages, "safety_alert")) + len(small.chunk(pages, "safety_alert"))
