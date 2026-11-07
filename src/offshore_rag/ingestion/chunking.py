"""Chunking strategies. Each produces `ChunkDraft`s for one document and never crosses documents.

`FixedWordChunker` concatenates the words of the text pages, keeping for every word the page it came from (the
offset -> page map, at word granularity), and cuts windows of `size` words that overlap by `overlap` words.

Joining rule: a chunk's text is its words joined by single spaces, including across a page break. Words never span
a page break (a page's text is split on whitespace on its own). So `page_start`/`page_end` are exactly the pages of
the chunk's first and last word, every page between them contributes all of its words, and the chunk text equals a
slice of the whitespace-normalized concatenation (pages joined by a space) of the pages in its range (AC-001-07).

Image-only pages contribute no text, and a window never crosses one: the text pages are chunked in runs of
consecutive text pages. Otherwise a chunk's page range would include an image-only page whose residual text (a page
number, a caption) is not in the chunk, and the chunk text would not be a slice of its pages' text.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from offshore_rag.ingestion.pdf import PageText


@dataclass(frozen=True)
class ChunkDraft:
    ordinal: int
    page_start: int
    page_end: int
    text: str


@runtime_checkable
class Chunker(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def params(self) -> Mapping[str, int | str]: ...

    def chunk(self, pages: Sequence[PageText]) -> list[ChunkDraft]: ...


class UnknownChunkerError(ValueError):
    """`CHUNKERS` names a strategy that does not exist."""


class FixedWordChunker:
    def __init__(self, *, size: int = 250, overlap: int = 40) -> None:
        if size < 1:
            raise ValueError(f"size must be at least 1, got {size}")
        if not 0 <= overlap < size:
            raise ValueError(f"overlap must be in [0, size), got overlap={overlap} size={size}")
        self._size = size
        self._overlap = overlap

    @property
    def id(self) -> str:
        return "fixed_words"

    @property
    def params(self) -> Mapping[str, int | str]:
        return {"size": self._size, "overlap": self._overlap}

    def chunk(self, pages: Sequence[PageText]) -> list[ChunkDraft]:
        drafts: list[ChunkDraft] = []
        for run in _text_runs(pages):
            for start_page, end_page, words in self._windows(run):
                drafts.append(ChunkDraft(len(drafts), start_page, end_page, " ".join(words)))
        return drafts

    def _windows(self, words: list[tuple[str, int]]) -> list[tuple[int, int, list[str]]]:
        step = self._size - self._overlap
        out: list[tuple[int, int, list[str]]] = []
        start = 0
        while True:
            window = words[start : start + self._size]
            out.append((window[0][1], window[-1][1], [w for w, _ in window]))
            if start + self._size >= len(words):
                return out
            start += step


def _text_runs(pages: Sequence[PageText]) -> list[list[tuple[str, int]]]:
    """Words of each run of consecutive text pages, each word tagged with its page number."""
    runs: list[list[tuple[str, int]]] = []
    current: list[tuple[str, int]] = []
    previous: int | None = None
    for page in sorted(pages, key=lambda p: p.number):
        words = [] if page.image_only else page.text.split()
        if not words or (previous is not None and page.number != previous + 1):
            if current:
                runs.append(current)
            current = []
        current.extend((w, page.number) for w in words)
        previous = page.number
    if current:
        runs.append(current)
    return runs


_REGISTRY: dict[str, Callable[[], Chunker]] = {
    "fixed_words": lambda: FixedWordChunker(size=250, overlap=40),
}


def chunkers_from_config(names: Sequence[str]) -> list[Chunker]:
    """Build the chunkers named in `CHUNKERS`, in order. Raises `UnknownChunkerError` for an unknown name."""
    unknown = [n for n in names if n not in _REGISTRY]
    if unknown:
        raise UnknownChunkerError(
            f"unknown chunker(s): {', '.join(unknown)} (available: {', '.join(sorted(_REGISTRY))})"
        )
    return [_REGISTRY[n]() for n in names]
