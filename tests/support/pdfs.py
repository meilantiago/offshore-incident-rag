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


# -- spec 002: documents with (or without) the structure of each BSEE document type -----------------------------
#
# Every text page is written line by line (one `cell` per line), so the extracted lines are exactly the lines given
# here. `None` in a page list is an image-only page. Prose is deterministic: sentences built from a fixed vocabulary
# plus one token unique to the document and position (`<tag>s003w07`), so a test can tell where any word came from.

_VOCAB = [
    "crew",
    "valve",
    "crane",
    "line",
    "deck",
    "pressure",
    "rig",
    "hose",
    "sling",
    "load",
    "operator",
    "platform",
    "well",
    "casing",
    "pump",
    "gauge",
    "lift",
    "tool",
    "panel",
    "cable",
    "block",
    "hoist",
    "work",
    "permit",
    "hazard",
    "inspection",
    "procedure",
    "supervisor",
    "shift",
    "equipment",
]


def lines_pdf(pages: list[list[str] | None]) -> bytes:
    """One page per item: a list of text lines, or None for a page holding only a raster image."""
    pdf = _new_pdf()
    for k, lines in enumerate(pages, start=1):
        pdf.add_page()
        if lines is None:
            pdf.image(io.BytesIO(_raster(100 + k)), x=20, y=20, w=170)
            continue
        pdf.set_font("Helvetica", size=9)
        pdf.set_xy(15, 15)
        for line in lines:
            pdf.set_x(15)
            pdf.cell(0, 4.6, line, new_x="LMARGIN", new_y="NEXT")
    return _output(pdf)


def prose_lines(tag: str, n_sentences: int, words_per_sentence: int = 11, words_per_line: int = 12) -> list[str]:
    """Deterministic prose: `n_sentences` sentences, wrapped at `words_per_line` words per line."""
    words: list[str] = []
    for s in range(n_sentences):
        sentence = [f"{tag}s{s:03d}w{0:02d}".capitalize()]
        sentence += [
            _VOCAB[(s * 7 + i * 3) % len(_VOCAB)] if i % 4 else f"{tag}s{s:03d}w{i:02d}"
            for i in range(1, words_per_sentence)
        ]
        sentence[-1] += "."
        words += sentence
    return [" ".join(words[i : i + words_per_line]) for i in range(0, len(words), words_per_line)]


# -- MMS Form 2010 (district reports) --------------------------------------------------------------------------

FORM2010_GRID_LABELS = ("FIRE", "EXPLOSION", "FATALITY", "COLLISION")
FORM2010_HEADER_RE = re.compile(r"^(For Public Release|MMS - FORM 2010 PAGE: \d+ OF \d+|EV2010R \d{2}-[A-Z]{3}-\d{4})$")


def _form2010_grid(n_pages: int) -> list[str]:
    return [
        "UNITED STATES DEPARTMENT OF THE INTERIOR",
        "BUREAU OF SAFETY AND ENVIRONMENTAL ENFORCEMENT",
        "ACCIDENT INVESTIGATION REPORT",
        "For Public Release",
        "1. OCCURRED STRUCTURAL DAMAGE",
        "DATE: 14-MAR-2019 TIME: 1015 HOURS CRANE",
        "2. OPERATOR: Example Offshore LLC OTHER LIFTING",
        "4. LEASE: 00999 AREA: SS LATITUDE:",
        "BLOCK: 77 LONGITUDE:",
        "X PRODUCTION",
        "FATALITY",
        "POLLUTION",
        "FIRE 12. WIND DIRECTION:",
        "EXPLOSION SPEED: M.P.H.",
        "16. STATEMENT TAKEN: COLLISION HISTORIC >$25K <=$25K",
        f"MMS - FORM 2010 PAGE: 1 OF {n_pages}",
        "EV2010R 02-MAY-2019",
    ]


def _form2010_page(k: int, n_pages: int, body: list[str]) -> list[str]:
    return [
        *body[:1],
        "For Public Release",
        *body[1:],
        f"MMS - FORM 2010 PAGE: {k} OF {n_pages}",
        "EV2010R 02-MAY-2019",
    ]


def district_with_image_page_pdf() -> bytes:
    """Form 2010, 4 pages: 1 grid, 2 field 17, 3 image-only, 4 rest of field 17 and fields 18-19.

    Field 17 runs across the image-only page, so a chunk that crossed it would span pages 2..4.
    """
    p2 = ["17. INVESTIGATION FINDINGS:", "INCIDENT SUMMARY:", *prose_lines("imgA", 12)]
    p4 = [
        *prose_lines("imgB", 6),
        "18. LIST THE PROBABLE CAUSE(S) OF ACCIDENT:",
        *prose_lines("imgC", 3),
        "19. LIST THE CONTRIBUTING CAUSE(S) OF ACCIDENT:",
        *prose_lines("imgD", 2),
    ]
    return lines_pdf([_form2010_grid(4), _form2010_page(2, 4, p2), None, _form2010_page(4, 4, p4)])


def district_without_fields_pdf() -> bytes:
    """A district report whose narrative has no numbered fields 17-24 (structure not recognized)."""
    p2 = ["INCIDENT SUMMARY", *prose_lines("nofA", 26)]
    p3 = [*prose_lines("nofB", 22), "BSEE INVESTIGATION", *prose_lines("nofC", 8)]
    return lines_pdf([_form2010_grid(3), _form2010_page(2, 3, p2), _form2010_page(3, 3, p3)])


def panel_without_headings_pdf() -> bytes:
    """A panel report with a title page and prose, but no Contents page and no section headings."""
    title = [
        "OCS Report",
        "MMS 2001-099",
        "Investigation of Dropped Load",
        "South Timbalier Block 88",
        "U.S. Department of the Interior",
        "Minerals Management Service",
    ]
    return lines_pdf([title, ["1", *prose_lines("nohA", 28)], ["2", *prose_lines("nohB", 25)]])


# -- MMS-era Safety Alert ("Notice No. N") ---------------------------------------------------------------------

_NOTICE_SIZES = (38, 51, 40, 27, 50)  # words per numbered paragraph: 12 per full line plus a short last line


def notice_alert_paragraphs() -> list[list[str]]:
    """The lines of each paragraph of the generated notice, the header block first.

    No line ends in `:` and none is a Contact or Phone line. Every paragraph ends with a short line ending in `.`, and
    no other line ends in `.`; numbered paragraphs start with `N.`.
    """
    header = [
        "U.S. Department of the Interior",
        "Minerals Management Service",
        "Gulf of Mexico OCS Region",
        "Safety Alert",
        "Notice No. 7",
        "Issued March 3, 1993.",
    ]
    paragraphs = [header]
    for n, size in enumerate(_NOTICE_SIZES, start=1):
        words = [f"{n}.", f"Notice{n}w00"] + [
            _VOCAB[(n * 5 + i) % len(_VOCAB)] if i % 5 else f"n{n}w{i:02d}" for i in range(2, size)
        ]
        words[-1] += "."
        paragraphs.append([" ".join(words[i : i + 12]) for i in range(0, len(words), 12)])
    return paragraphs


def notice_alert_pdf() -> bytes:
    """One page: an MMS-era alert, header block and five numbered paragraphs, with no heading lines."""
    return lines_pdf([[line for para in notice_alert_paragraphs() for line in para]])
