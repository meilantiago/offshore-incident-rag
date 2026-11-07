"""Self-checks of the synthetic PDF generators (test infrastructure, not acceptance tests)."""

from __future__ import annotations

import re
from pathlib import Path

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


def test_support_spec002_generators_are_deterministic_and_shaped() -> None:
    from offshore_rag.ingestion.pdf import parse_pdf

    for make, flags in (
        (pdfs.district_with_image_page_pdf, [False, False, True, False]),
        (pdfs.district_without_fields_pdf, [False, False, False]),
        (pdfs.panel_without_headings_pdf, [False, False, False]),
        (pdfs.notice_alert_pdf, [False]),
    ):
        data = make()
        assert data == make()
        assert [p.image_only for p in parse_pdf(data).pages] == flags, make.__name__
    without = " ".join(p.text for p in parse_pdf(pdfs.district_without_fields_pdf()).pages)
    assert not re.search(r"(?m)^\s*(1[7-9]|2[0-4])\.\s", without), "no Form 2010 fields 17-24"
    assert "Contents" not in " ".join(p.text for p in parse_pdf(pdfs.panel_without_headings_pdf()).pages)


def test_support_notice_alert_text_is_its_paragraphs() -> None:
    from offshore_rag.ingestion.pdf import parse_pdf

    (page,) = parse_pdf(pdfs.notice_alert_pdf()).pages
    paragraphs = pdfs.notice_alert_paragraphs()
    assert page.text.split() == " ".join(line for p in paragraphs for line in p).split()
    lines = [line.strip() for line in page.text.splitlines() if line.strip()]
    assert not any(line.endswith(":") for line in lines), "no heading lines"
    assert not any(re.match(r"(?i)(contact|phone)", line) for line in lines)


def test_support_trim_pdf_keeps_whole_pages_and_blanks_photographs(tmp_path: Path) -> None:
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    from offshore_rag.ingestion.pdf import parse_pdf
    from tests.support.structure import DISTRICT_PDF
    from tests.support.trim_pdf import trim_pdf

    out = tmp_path / "two.pdf"
    assert trim_pdf(DISTRICT_PDF, out, [2, 3]) == []
    original = parse_pdf(DISTRICT_PDF.read_bytes()).pages
    assert [p.text for p in parse_pdf(out.read_bytes()).pages] == [p.text for p in original[1:]]

    photo = tmp_path / "photo.pdf"
    src = tmp_path / "with-image.pdf"
    src.write_bytes(pdfs.district_with_image_page_pdf())
    dropped = trim_pdf(src, photo, drop_images_over=10_000)
    assert [d.page for d in dropped] == [3]
    doc = pdfium.PdfDocument(str(photo))
    assert not list(doc[2].get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]))
    assert [p.text for p in parse_pdf(photo.read_bytes()).pages] == [p.text for p in parse_pdf(src.read_bytes()).pages]
    assert len(photo.read_bytes()) < len(src.read_bytes()) / 2, "the photograph's pixel data is gone from the file"
