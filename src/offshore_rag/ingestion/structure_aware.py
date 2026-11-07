"""The `structure_aware` chunking strategy (spec 002, plan #Chunking).

Each segment found by `detect_structure` (a district field, a panel section, an alert section) is chunked on its own,
so no chunk holds text from two segments. A segment's kept words (removed content left out) that fit the size cap are
one chunk; a longer segment is cut by the splitting rule: at the last paragraph break within the cap, else at the
last sentence break within the cap, else at the cap word. No overlap. A segment is also cut at an image-only page,
so no chunk's page range includes one (AC-002-08).

A Safety Alert whose whole kept text fits the cap is one chunk labelled `alert`, whatever its heading lines
(AC-002-06). A document whose structure is not recognized falls back to fixed windows of `size_cap` words with no
overlap, labelled `structure_not_recognized` (AC-002-07).

Text follows the joining rule of `fixed_words`: words joined by single spaces, `page_start`/`page_end` the pages of
the first and last word. The section label goes in `ChunkDraft.section`, never in the text.

Breaks are heuristics (plan #Chunking): a paragraph break follows a line followed by a blank line, a line followed by
a bullet line, or a line ending in `.`, `:`, `?` or `!` shorter than 75% of the median line length of its page. A
sentence break follows any word ending in `.`, `:`, `?` or `!` (closing quotes or brackets allowed).
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from offshore_rag.ingestion.chunking import ChunkDraft, DocType, FixedWordChunker
from offshore_rag.ingestion.pdf import PageText
from offshore_rag.ingestion.structure import ALERT, DocumentStructure, Line, Segment, detect_structure

NOT_RECOGNIZED = "structure_not_recognized"
VERSION = 2  # 2: Contents leaders with `…` no longer end up in panel section labels (T90)

_BREAK_END = re.compile(r"[.:?!][\"')\]]*$")
_BULLET = re.compile(r"^([•�\-–]|\d+[.)]|[a-z][.)])$")
_SHORT_LINE_RATIO = 0.75


@dataclass(frozen=True)
class _Word:
    text: str
    page: int
    paragraph_after: bool
    sentence_after: bool


class StructureAwareChunker:
    def __init__(self, *, size_cap: int = 250) -> None:
        if size_cap < 1:
            raise ValueError(f"size_cap must be at least 1, got {size_cap}")
        self._size_cap = size_cap

    @property
    def id(self) -> str:
        return "structure_aware"

    @property
    def params(self) -> Mapping[str, int | str]:
        return {"size_cap": self._size_cap, "version": VERSION}

    def chunk(self, pages: Sequence[PageText], doc_type: DocType) -> list[ChunkDraft]:
        structure = detect_structure(pages, doc_type)
        if structure is None:
            return self._fallback(pages, doc_type)
        if doc_type == "safety_alert":
            structure = whole_alert_if_it_fits(structure, self._size_cap)
        medians = _median_line_lengths(structure.lines)
        drafts: list[ChunkDraft] = []
        for segment in structure.segments:
            words = _segment_words(structure.lines, segment, medians)
            for run in _runs(words, structure.image_only_pages):
                for piece in _split(run, self._size_cap):
                    text = " ".join(w.text for w in piece)
                    drafts.append(ChunkDraft(len(drafts), piece[0].page, piece[-1].page, text, segment.label))
        return drafts

    def _fallback(self, pages: Sequence[PageText], doc_type: DocType) -> list[ChunkDraft]:
        windows = FixedWordChunker(size=self._size_cap, overlap=0).chunk(pages, doc_type)
        return [replace(d, section=NOT_RECOGNIZED) for d in windows]


def whole_alert_if_it_fits(structure: DocumentStructure, size_cap: int) -> DocumentStructure:
    """A Safety Alert's segments as `structure_aware` chunks them: one `alert` segment when its kept text fits the cap
    (AC-002-06). Shared with the structural report, so both use the same boundaries."""
    kept = [i for i, line in enumerate(structure.lines) if not line.removed]
    if not kept or sum(len(structure.lines[i].text.split()) for i in kept) > size_cap:
        return structure
    whole = Segment(ALERT, kept[0], len(structure.lines) - 1, "narrative")
    return replace(structure, segments=[whole])


def _median_line_lengths(lines: Sequence[Line]) -> dict[int, float]:
    by_page: dict[int, list[int]] = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(len(line.text))
    return {page: statistics.median(lengths) for page, lengths in by_page.items()}


def _starts_with_bullet(line: Line) -> bool:
    return bool(_BULLET.match(line.text.split()[0]))


def _segment_words(lines: Sequence[Line], segment: Segment, medians: Mapping[int, float]) -> list[_Word]:
    kept = [lines[i] for i in range(segment.first, segment.last + 1) if not lines[i].removed]
    words: list[_Word] = []
    for k, line in enumerate(kept):
        nxt = kept[k + 1] if k + 1 < len(kept) else None
        paragraph = (
            line.blank_after
            or (nxt is not None and _starts_with_bullet(nxt))
            or (bool(_BREAK_END.search(line.text)) and len(line.text) < _SHORT_LINE_RATIO * medians[line.page])
        )
        tokens = line.text.split()
        for j, token in enumerate(tokens):
            last = j == len(tokens) - 1
            words.append(_Word(token, line.page, paragraph and last, bool(_BREAK_END.search(token))))
    return words


def _runs(words: Sequence[_Word], image_only_pages: frozenset[int]) -> list[list[_Word]]:
    """The words cut wherever an image-only page lies between two consecutive words."""
    runs: list[list[_Word]] = []
    for word in words:
        if runs and not any(runs[-1][-1].page < p < word.page for p in image_only_pages):
            runs[-1].append(word)
        else:
            runs.append([word])
    return runs


def _split(words: Sequence[_Word], cap: int) -> list[Sequence[_Word]]:
    """The splitting rule (spec 002 #Definitions): last paragraph break, else last sentence break, else the cap."""
    pieces: list[Sequence[_Word]] = []
    start = 0
    while len(words) - start > cap:
        window = words[start : start + cap]
        size = next((j + 1 for j in range(cap - 1, -1, -1) if window[j].paragraph_after), 0)
        size = size or next((j + 1 for j in range(cap - 1, -1, -1) if window[j].sentence_after), cap)
        pieces.append(words[start : start + size])
        start += size
    if start < len(words):
        pieces.append(words[start:])
    return pieces
