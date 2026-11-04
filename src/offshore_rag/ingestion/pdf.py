"""Page-accurate PDF text extraction with pypdfium2 (ADR-0002).

Page `k` of `ParsedPdf.pages` is page `k` of the PDF (1-based). Text is normalized: Unicode NFC, `\\n` line
endings, ligatures expanded, NUL characters dropped, trailing spaces trimmed on every line. A page is image-only when
its text has fewer than `IMAGE_ONLY_MIN_CHARS` non-whitespace characters.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import pypdfium2 as pdfium

IMAGE_ONLY_MIN_CHARS = 20

_LIGATURES = str.maketrans(
    {
        "ﬀ": "ff",
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬅ": "st",
        "ﬆ": "st",
        "\x00": None,
    }
)
_TRAILING_SPACE = re.compile(r"[^\S\n]+$", re.MULTILINE)


class PdfParseError(Exception):
    """The PDF is corrupt, encrypted or otherwise unreadable (ingestion stage `parse`)."""


@dataclass(frozen=True)
class PageText:
    number: int
    text: str
    image_only: bool


@dataclass(frozen=True)
class ParsedPdf:
    pages: list[PageText]

    @property
    def page_count(self) -> int:
        return len(self.pages)


def normalize_text(raw: str) -> str:
    """NFC, `\\n` line endings, ligatures expanded, NULs dropped, trailing whitespace trimmed per line and at the end."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n").translate(_LIGATURES)
    text = unicodedata.normalize("NFC", text)
    return _TRAILING_SPACE.sub("", text).rstrip("\n")


def is_image_only(text: str) -> bool:
    return sum(1 for ch in text if not ch.isspace()) < IMAGE_ONLY_MIN_CHARS


def parse_pdf(data: bytes) -> ParsedPdf:
    """Extract normalized text page by page. Raises `PdfParseError` for corrupt or encrypted input."""
    if not data:
        raise PdfParseError("empty file")
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        raise PdfParseError(_describe(e)) from e
    try:
        pages: list[PageText] = []
        for index in range(len(doc)):
            page = doc[index]
            try:
                textpage = page.get_textpage()
                try:
                    raw: str = textpage.get_text_range()
                finally:
                    textpage.close()
            finally:
                page.close()
            text = normalize_text(raw)
            pages.append(PageText(number=index + 1, text=text, image_only=is_image_only(text)))
    except pdfium.PdfiumError as e:
        raise PdfParseError(_describe(e)) from e
    finally:
        doc.close()
    if not pages:
        raise PdfParseError("the PDF has no pages")
    return ParsedPdf(pages=pages)


def _describe(error: Exception) -> str:
    message = str(error)
    if "password" in message.lower():
        return f"encrypted PDF (password required): {message}"
    return f"unreadable PDF: {message}"
