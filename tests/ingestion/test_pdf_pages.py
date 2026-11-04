"""AC-001-05: pages are stored numbered as in the original PDF, each with its own text and no other page's."""

from __future__ import annotations

import pytest

from tests.conftest import migrate_schema
from tests.support import pdfs
from tests.support.ingest import EXIT_OK, REAL_ALERT_PDF, IngestEnv, assert_exit, norm_ws

# A phrase that appears on exactly one page of the committed Safety Alert 469 (3 pages).
REAL_ALERT_PAGE_PHRASES = {
    1: "Performance-Based Risk Inspection",
    2: "S-61 SAR helicopters",
    3: "automatic external defibrillator placement",
}


def _assert_markers(pages: list[tuple[int, str]], n: int) -> None:
    assert [number for number, _ in pages] == list(range(1, n + 1))
    for number, text in pages:
        assert pdfs.MARKER_RE.findall(text) == [pdfs.marker(number)], f"page {number}: {text[:200]!r}"


def test_ac_001_05_parse_pdf_keeps_page_numbers_and_text() -> None:
    """AC-001-05: parse_pdf on an N-page PDF gives N pages, page k holds marker k and no other marker."""
    from offshore_rag.ingestion.pdf import parse_pdf

    n = 7
    parsed = parse_pdf(pdfs.text_pdf(n))

    _assert_markers([(p.number, p.text) for p in parsed.pages], n)
    assert not any(p.image_only for p in parsed.pages)


def test_ac_001_05_parse_pdf_real_safety_alert_pages() -> None:
    """AC-001-05: on the committed Safety Alert 469, each page's text is that page's and not another's."""
    from offshore_rag.ingestion.pdf import parse_pdf

    parsed = parse_pdf(REAL_ALERT_PDF.read_bytes())

    assert [p.number for p in parsed.pages] == [1, 2, 3]
    for page in parsed.pages:
        text = norm_ws(page.text)
        for k, phrase in REAL_ALERT_PAGE_PHRASES.items():
            assert (phrase in text) == (k == page.number), f"page {page.number} / phrase of page {k}"


@pytest.mark.integration
def test_ac_001_05_stored_pages_match_the_original_pdf(db_env: IngestEnv) -> None:
    """AC-001-05: after ingest, exactly N pages are stored, numbered 1..N, page k with marker k only."""
    migrate_schema(db_env.db)
    n = 9
    url = db_env.serve_pdf("/sites/bsee.gov/files/nine-pages.pdf", pdfs.text_pdf(n))
    real_url = db_env.serve_pdf("/sites/bsee.gov/files/2023-10/alert-469.pdf", REAL_ALERT_PDF.read_bytes())
    db_env.write_manifest(
        [
            db_env.entry("/sites/bsee.gov/files/nine-pages.pdf"),
            db_env.entry("/sites/bsee.gov/files/2023-10/alert-469.pdf"),
        ]
    )

    assert_exit(db_env.ingest(), EXIT_OK)

    _assert_markers([(number, text) for number, text, _ in db_env.pages(url)], n)
    doc = db_env.document(url)
    assert doc is not None and doc["page_count"] == n

    real_pages = db_env.pages(real_url)
    assert [number for number, _, _ in real_pages] == [1, 2, 3]
    for number, text, _ in real_pages:
        for k, phrase in REAL_ALERT_PAGE_PHRASES.items():
            assert (phrase in norm_ws(text)) == (k == number), f"stored page {number} / phrase of page {k}"
