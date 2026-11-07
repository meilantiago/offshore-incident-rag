"""Structure detection for `structure_aware` chunking (spec 002, plan #Structure detection).

`detect_structure` turns the stored pages of one document into a `DocumentStructure`: its **lines** (page, text,
`removed` flag) and its **segments** (section label, first and last line index, kind). It is pure and line-based on
the text `parse_pdf` stores; it returns `None` when the structure of the document type is not found (AC-002-07).

Lines are the stripped, non-blank lines of every text page; image-only pages contribute no line. Removed content
(spec 002 #Definitions) stays in `lines` with `removed=True`, so the chunker and the structural report see the same
boundaries.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from offshore_rag.ingestion.chunking import DocType
from offshore_rag.ingestion.pdf import PageText

SegmentKind = Literal["narrative", "acronyms", "preamble"]

PREAMBLE = "preamble"
ACRONYMS = "acronyms"
ALERT = "alert"


@dataclass(frozen=True)
class Line:
    page: int
    text: str
    removed: bool = False
    blank_after: bool = False  # a blank line follows it on its page


@dataclass(frozen=True)
class Segment:
    label: str
    first: int  # index into `DocumentStructure.lines`, inclusive
    last: int  # inclusive
    kind: SegmentKind


@dataclass(frozen=True)
class DocumentStructure:
    lines: list[Line]
    segments: list[Segment]
    image_only_pages: frozenset[int]


def detect_structure(pages: Sequence[PageText], doc_type: DocType) -> DocumentStructure | None:
    """The structure of one document, or `None` when it is not recognized for its document type."""
    detectors: dict[str, Callable[[Sequence[PageText]], DocumentStructure | None]] = {
        "district_report": _district,
        "panel_report": _panel,
        "safety_alert": _alert,
    }
    try:
        detect = detectors[doc_type]
    except KeyError:
        raise ValueError(f"unknown document type {doc_type!r}") from None
    return detect(sorted(pages, key=lambda p: p.number))


# -- shared -----------------------------------------------------------------------------------------------------
def _page_lines(pages: Sequence[PageText]) -> list[Line]:
    lines: list[Line] = []
    for page in pages:
        if page.image_only:
            continue
        start = len(lines)
        for raw in page.text.splitlines():
            text = raw.strip()
            if text:
                lines.append(Line(page.number, text))
            elif len(lines) > start:
                lines[-1] = Line(page.number, lines[-1].text, blank_after=True)
        if len(lines) > start:  # a blank after the last line of a page separates nothing
            last = lines[-1]
            lines[-1] = Line(last.page, last.text)
    return lines


def _image_only(pages: Sequence[PageText]) -> frozenset[int]:
    return frozenset(p.number for p in pages if p.image_only)


def _remove(lines: list[Line], indexes: set[int]) -> list[Line]:
    return [Line(ln.page, ln.text, True, ln.blank_after) if i in indexes else ln for i, ln in enumerate(lines)]


def _segments(lines: list[Line], starts: list[tuple[int, str, SegmentKind]]) -> list[Segment]:
    """Segments from their start lines (in order); kept lines before the first start form a `preamble`."""
    segments: list[Segment] = []
    first_start = starts[0][0] if starts else len(lines)
    kept_before = [i for i in range(first_start) if not lines[i].removed]
    if kept_before:
        segments.append(Segment(PREAMBLE, kept_before[0], first_start - 1, "preamble"))
    for n, (start, label, kind) in enumerate(starts):
        end = starts[n + 1][0] - 1 if n + 1 < len(starts) else len(lines) - 1
        segments.append(Segment(label, start, end, kind))
    return segments


def _key(text: str) -> str:
    """Case, punctuation and underscores ignored, whitespace normalized."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.lower()).split())


def _pages_of(lines: list[Line]) -> dict[int, list[int]]:
    by_page: dict[int, list[int]] = {}
    for i, line in enumerate(lines):
        by_page.setdefault(line.page, []).append(i)
    return by_page


# -- district reports (MMS Form 2010) ---------------------------------------------------------------------------
_DISTRICT_FIELDS = {
    17: ("INVESTIGATION FINDINGS",),
    18: ("LIST THE PROBABLE CAUSE(S) OF ACCIDENT",),
    19: ("LIST THE CONTRIBUTING CAUSE(S) OF ACCIDENT",),
    20: ("LIST THE ADDITIONAL INFORMATION",),
    21: ("PROPERTY DAMAGED",),
    22: ("RECOMMENDATIONS TO PREVENT RECURRANCE NARRATIVE", "RECOMMENDATIONS TO PREVENT RECURRENCE NARRATIVE"),
    23: ("POSSIBLE OCS VIOLATIONS RELATED TO ACCIDENT",),
    24: ("SPECIFY VIOLATIONS DIRECTLY OR INDIRECTLY CONTRIBUTING",),
    25: ("DATE OF ONSITE INVESTIGATION",),
}
DISTRICT_HEADER = re.compile(r"For Public Release|MMS - FORM 2010|EV2010R|PAGE:\s*\d+\s+OF\b", re.IGNORECASE)
_DISTRICT_TOP_LINE = re.compile(r"\d{1,3}|\d{2}-[A-Z]{3}-\d{4}", re.IGNORECASE)  # bare page count, header date
_NUMBERED = re.compile(r"^(\d{1,2})\.?\s+(\S.*)$")
_LATER_FIELD = re.compile(r"^(\d{1,2})\.\s+([A-Z][^:]*)")


def _field_start(text: str, after: int) -> tuple[int, str] | None:
    """`(number, label)` when `text` opens a narrative field numbered above `after`."""
    m = _NUMBERED.match(text)
    if m is None or int(m.group(1)) <= after:
        return None
    number, rest = int(m.group(1)), " ".join(m.group(2).upper().split())
    for title in _DISTRICT_FIELDS.get(number, ()):
        if rest.startswith(title):
            return number, f"{number} {_DISTRICT_FIELDS[number][0]}"
    if number > max(_DISTRICT_FIELDS):
        later = _LATER_FIELD.match(text)
        if later is not None:
            return number, f"{number} {' '.join(later.group(2).split())}"
    return None


def _district(pages: Sequence[PageText]) -> DocumentStructure | None:
    lines = _page_lines(pages)
    removed: set[int] = set()
    for page, indexes in _pages_of(lines).items():
        if page == 1:
            removed.update(indexes)
            continue
        removed.update(i for i in indexes if DISTRICT_HEADER.search(lines[i].text))
        top = next((i for i in indexes if i not in removed), None)
        if top is not None and _DISTRICT_TOP_LINE.fullmatch(lines[top].text):
            removed.add(top)
    lines = _remove(lines, removed)

    starts: list[tuple[int, str, SegmentKind]] = []
    numbers: list[int] = []
    for i, line in enumerate(lines):
        if line.removed:
            continue
        found = _field_start(line.text, numbers[-1] if numbers else 16)
        if found is not None:
            numbers.append(found[0])
            starts.append((i, found[1], "narrative"))
    if not any(17 <= n <= 24 for n in numbers):
        return None
    return DocumentStructure(lines, _segments(lines, starts), _image_only(pages))


# -- panel reports ----------------------------------------------------------------------------------------------
_PAGE_NUMBER = re.compile(r"\d+|[ivxlcdm]+", re.IGNORECASE)
_CONTENTS_KEYS = ("contents", "table of contents")
_FIGURE_LIST_KEYS = frozenset(
    {"list of figures", "figures", "list of tables", "tables", "list of figures and tables", "list of illustrations"}
)
_ACRONYM_KEYS = frozenset(
    {"acronyms", "abbreviations", "abbreviations and acronyms", "acronyms and abbreviations", "list of acronyms"}
)
_CONTENTS_ENTRY = re.compile(r"^(.*?\S)[\s._]+(\d+|[ivxlc]+)$")


def _panel(pages: Sequence[PageText]) -> DocumentStructure | None:
    lines = _page_lines(pages)
    removed: set[int] = set()
    contents_pages: list[list[int]] = []
    for indexes in _pages_of(lines).values():
        for i in (indexes[0], indexes[-1]):
            if _PAGE_NUMBER.fullmatch(lines[i].text):
                removed.add(i)
        body = [i for i in indexes if i not in removed]
        head = _key(lines[body[0]].text) if body else ""
        if head in _CONTENTS_KEYS:
            contents_pages.append(body)
            removed.update(indexes)
        elif head in _FIGURE_LIST_KEYS:
            removed.update(indexes)
    if not contents_pages:
        return None
    lines = _remove(lines, removed)

    titles: dict[str, str] = {}
    for body in contents_pages:
        for i in body[1:]:
            m = _CONTENTS_ENTRY.match(lines[i].text)
            if m is not None:
                title = " ".join(m.group(1).replace("_", " ").split())
                if _key(title):
                    titles.setdefault(_key(title), title)

    starts: list[tuple[int, str, SegmentKind]] = []
    for i, line in enumerate(lines):
        key = _key(line.text)
        if line.removed or key not in titles:
            continue
        if key in _ACRONYM_KEYS:
            starts.append((i, ACRONYMS, "acronyms"))
        else:
            starts.append((i, titles[key], "narrative"))
    if not starts:
        return None
    return DocumentStructure(lines, _segments(lines, starts), _image_only(pages))


# -- Safety Alerts ----------------------------------------------------------------------------------------------
_CONTACT_PHONE = re.compile(r"^(Contact|Phone):", re.IGNORECASE)
_HEADING_MAX_WORDS = 8


def _is_alert_heading(text: str) -> bool:
    # Starts like a heading: a line ending in ':' that starts in lowercase continues a sentence ("the following:").
    return text.endswith(":") and len(text.split()) <= _HEADING_MAX_WORDS and not text[0].islower()


def _alert(pages: Sequence[PageText]) -> DocumentStructure:
    lines = _page_lines(pages)
    lines = _remove(lines, {i for i, ln in enumerate(lines) if ln.page == 1 and _CONTACT_PHONE.match(ln.text)})
    starts: list[tuple[int, str, SegmentKind]] = [
        (i, line.text[:-1].strip(), "narrative")
        for i, line in enumerate(lines)
        if not line.removed and _is_alert_heading(line.text) and line.text[:-1].strip()
    ]
    if not starts:
        kept = [i for i, line in enumerate(lines) if not line.removed]
        segments = [Segment(ALERT, kept[0], len(lines) - 1, "narrative")] if kept else []
        return DocumentStructure(lines, segments, _image_only(pages))
    return DocumentStructure(lines, _segments(lines, starts), _image_only(pages))
