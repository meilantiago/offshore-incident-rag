"""Self-checks of the synthetic PDF generators (test infrastructure, not acceptance tests)."""

from __future__ import annotations

import re

from tests.support import pdfs


def _page_objects(data: bytes) -> int:
    return len(re.findall(rb"/Type /Page\b", data))


def test_support_text_pdf_has_one_marker_per_page_and_is_deterministic() -> None:
    data = pdfs.text_pdf(4)
    assert data.startswith(b"%PDF-")
    assert _page_objects(data) == 4
    found = [m.decode() for m in re.findall(rb"PAGE-MARKER-\d{4}", data)]
    assert found == [pdfs.marker(k) for k in range(1, 5)]
    assert data == pdfs.text_pdf(4)
    assert data != pdfs.text_pdf(4, tag="VERSION-B")


def test_support_filler_words_are_page_specific() -> None:
    data = pdfs.text_pdf(2, words_per_page=30)
    assert pdfs.filler_word(1, 29).encode() in data
    assert pdfs.filler_word(2, 0).encode() in data
    assert pdfs.filler_word(1, 30).encode() not in data


def test_support_image_only_pdf_has_images_and_no_text() -> None:
    data = pdfs.image_only_pdf(2)
    assert data.startswith(b"%PDF-")
    assert _page_objects(data) == 2
    assert data.count(b"/Subtype /Image") == 2
    assert b"/Font" not in data
    assert pdfs.MARKER_RE.search(data.decode("latin-1")) is None
    assert data == pdfs.image_only_pdf(2)


def test_support_corrupt_pdf_looks_like_pdf_but_has_no_trailer() -> None:
    data = pdfs.corrupt_pdf()
    assert data.startswith(b"%PDF-")
    assert b"trailer" not in data and b"startxref" not in data and b"%%EOF" not in data
