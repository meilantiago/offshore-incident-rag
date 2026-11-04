"""Synthetic PDFs for tests, generated with fpdf2.

- `text_pdf(n)`: n text pages, page k carries the unique marker `PAGE-MARKER-000k` plus filler words that are
  unique to that page (`p0003w0017`), so tests can tell which page any piece of text came from.
- `image_only_pdf(n)`: n pages that each hold only a raster image and no text layer.
- `corrupt_pdf()`: bytes that start like a PDF but cannot be parsed.

Output is deterministic (fixed creation date, no compression), so the same arguments give the same bytes and the
same sha256.
"""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime

from fpdf import FPDF
from PIL import Image

MARKER_RE = re.compile(r"PAGE-MARKER-\d{4}")
_FIXED_DATE = datetime(2026, 1, 1, tzinfo=UTC)


def marker(page: int) -> str:
    return f"PAGE-MARKER-{page:04d}"


def filler_word(page: int, i: int) -> str:
    return f"p{page:04d}w{i:04d}"


def _new_pdf() -> FPDF:
    pdf = FPDF(format="Letter")
    pdf.set_compression(False)
    pdf.set_creation_date(_FIXED_DATE)
    pdf.set_producer("offshore-incident-rag tests")
    pdf.set_auto_page_break(auto=False)
    return pdf


def _output(pdf: FPDF) -> bytes:
    return bytes(pdf.output())


def text_pdf(n_pages: int, *, words_per_page: int = 120, tag: str = "") -> bytes:
    """N text pages. Page k holds `marker(k)`, `words_per_page` filler words unique to page k, and `tag` if given.

    `tag` lets a test produce a different version of "the same" document (for example `VERSION-B`).
    """
    pdf = _new_pdf()
    pdf.set_font("Helvetica", size=10)
    for k in range(1, n_pages + 1):
        pdf.add_page()
        pdf.set_xy(20, 20)
        head = f"{marker(k)} {tag}".strip()
        pdf.multi_cell(0, 6, head)
        words = " ".join(filler_word(k, i) for i in range(words_per_page))
        pdf.set_x(20)
        pdf.multi_cell(170, 5, words)
    return _output(pdf)


def _raster(seed: int, size: tuple[int, int] = (240, 160)) -> bytes:
    w, h = size
    img = Image.new("RGB", size)
    img.putdata(
        [
            ((x * 7 + seed * 31) % 256, (y * 5 + seed * 17) % 256, ((x + y) * 3) % 256)
            for y in range(h)
            for x in range(w)
        ]
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def image_only_pdf(n_pages: int = 2) -> bytes:
    """N pages, each containing only a raster image (a scanned page, as far as text extraction is concerned)."""
    pdf = _new_pdf()
    for k in range(1, n_pages + 1):
        pdf.add_page()
        pdf.image(io.BytesIO(_raster(k)), x=20, y=20, w=170)
    return _output(pdf)


def corrupt_pdf() -> bytes:
    """A PDF header followed by garbage and no cross-reference table or trailer."""
    return b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R" + bytes(range(256)) * 8
