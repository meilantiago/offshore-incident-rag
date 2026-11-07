"""`parse_pdf`: page-accurate text, image-only detection, normalization and parse errors (T08)."""

from __future__ import annotations

import io
import unicodedata

import pytest
from fpdf import FPDF

from offshore_rag.ingestion.pdf import PdfParseError, normalize_text, parse_pdf
from tests.support import pdfs


def test_n_pages_each_with_its_own_marker() -> None:
    parsed = parse_pdf(pdfs.text_pdf(5))
    assert [p.number for p in parsed.pages] == [1, 2, 3, 4, 5]
    for page in parsed.pages:
        assert pdfs.MARKER_RE.findall(page.text) == [pdfs.marker(page.number)]
        assert pdfs.filler_word(page.number, 0) in page.text
        assert not page.image_only


def test_image_only_pages_are_flagged() -> None:
    parsed = parse_pdf(pdfs.image_only_pdf(2))
    assert [(p.number, p.image_only) for p in parsed.pages] == [(1, True), (2, True)]


def test_short_text_page_is_image_only() -> None:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=10)
    pdf.add_page()
    pdf.text(20, 20, "12  of  14")  # a page number on a scan: under 20 non-whitespace characters
    parsed = parse_pdf(bytes(pdf.output()))
    assert parsed.pages[0].image_only


@pytest.mark.parametrize("data", [pdfs.corrupt_pdf(), b"", b"not a pdf at all"])
def test_corrupt_bytes_raise_parse_error(data: bytes) -> None:
    with pytest.raises(PdfParseError):
        parse_pdf(data)


def test_encrypted_pdf_raises_parse_error() -> None:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=10)
    pdf.add_page()
    pdf.text(20, 20, "secret text that should not be readable without the password")
    pdf.set_encryption(owner_password="owner", user_password="user")
    buf = io.BytesIO()
    pdf.output(buf)
    with pytest.raises(PdfParseError, match=r"encrypted|password"):
        parse_pdf(buf.getvalue())


def test_text_is_nfc_with_unix_line_endings() -> None:
    parsed = parse_pdf(pdfs.text_pdf(2, words_per_page=200))
    for page in parsed.pages:
        assert "\r" not in page.text
        assert "\n" in page.text, "multi-line pages keep their line breaks"
        assert unicodedata.is_normalized("NFC", page.text)
        assert all(line == line.rstrip() for line in page.text.split("\n"))


def test_normalize_text_rules() -> None:
    raw = "été  \r\nofﬁce   \rwaﬄe\x00 \r\n"
    assert normalize_text(raw) == "été\noffice\nwaffle"
