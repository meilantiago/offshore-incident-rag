"""`FixedWordChunker` and `chunkers_from_config` (T09)."""

from __future__ import annotations

import itertools
import re

import pytest

from offshore_rag.ingestion.chunking import (
    ChunkDraft,
    Chunker,
    FixedWordChunker,
    UnknownChunkerError,
    chunkers_from_config,
)
from offshore_rag.ingestion.pdf import PageText


def _page(number: int, n_words: int, *, image_only: bool = False) -> PageText:
    words = [f"p{number}w{i}" for i in range(n_words)]
    # several words per line, with stray spacing, as extracted text comes out
    lines = [" ".join(words[i : i + 7]) for i in range(0, len(words), 7)]
    return PageText(number=number, text="\n".join(lines) + "\n", image_only=image_only)


def _pages_of(text: str) -> set[int]:
    return {int(m) for m in re.findall(r"\bp(\d+)w\d+\b", text)}


def _window(pages: list[PageText], start: int, end: int) -> str:
    by_number = {p.number: p.text for p in pages}
    return re.sub(r"\s+", " ", " ".join(by_number[n] for n in range(start, end + 1))).strip()


def test_identity_and_params() -> None:
    chunker = FixedWordChunker(size=250, overlap=40)
    assert chunker.id == "fixed_words"
    assert dict(chunker.params) == {"size": 250, "overlap": 40}
    assert isinstance(chunker, Chunker)


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (10, 10), (10, -1), (5, 7)])
def test_invalid_params_rejected(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        FixedWordChunker(size=size, overlap=overlap)


def test_page_ranges_follow_the_words_when_a_window_spans_pages() -> None:
    pages = [_page(1, 30), _page(2, 30), _page(3, 30)]
    drafts = FixedWordChunker(size=25, overlap=5).chunk(pages)
    assert any(d.page_start < d.page_end for d in drafts)
    for d in drafts:
        contributing = _pages_of(d.text)
        assert (d.page_start, d.page_end) == (min(contributing), max(contributing))
        assert set(range(d.page_start, d.page_end + 1)) == contributing
        assert d.text in _window(pages, d.page_start, d.page_end)


def test_words_are_joined_by_single_spaces_across_page_breaks() -> None:
    pages = [_page(1, 3), _page(2, 3)]
    (draft,) = FixedWordChunker(size=10, overlap=2).chunk(pages)
    assert draft == ChunkDraft(ordinal=0, page_start=1, page_end=2, text="p1w0 p1w1 p1w2 p2w0 p2w1 p2w2")


def test_overlap_is_exactly_overlap_words() -> None:
    pages = [_page(1, 47), _page(2, 61)]
    drafts = FixedWordChunker(size=20, overlap=6).chunk(pages)
    assert len(drafts) > 2
    for a, b in itertools.pairwise(drafts):
        assert a.text.split()[-6:] == b.text.split()[:6]
        assert a.text.split()[-7] != b.text.split()[0]
    all_words = [w for p in pages for w in p.text.split()]
    rebuilt = drafts[0].text.split() + [w for d in drafts[1:] for w in d.text.split()[6:]]
    assert rebuilt == all_words, "windows cover every word once, in order, apart from the overlap"


def test_no_empty_chunks_and_every_text_page_covered() -> None:
    pages = [_page(1, 3), _page(2, 0), _page(3, 120), _page(4, 1)]
    drafts = FixedWordChunker(size=50, overlap=10).chunk(pages)
    assert all(d.text.strip() for d in drafts)
    covered = {n for d in drafts for n in range(d.page_start, d.page_end + 1)}
    assert {1, 3, 4} <= covered
    assert [d.ordinal for d in drafts] == list(range(len(drafts)))


def test_image_only_pages_produce_no_chunks() -> None:
    scan = PageText(number=2, text="12 of 14", image_only=True)
    assert FixedWordChunker(size=50, overlap=10).chunk([PageText(1, "", True), scan]) == []


def test_windows_do_not_cross_an_image_only_page() -> None:
    pages = [_page(1, 10), PageText(number=2, text="Fig 3", image_only=True), _page(3, 10)]
    drafts = FixedWordChunker(size=50, overlap=10).chunk(pages)
    assert [(d.page_start, d.page_end) for d in drafts] == [(1, 1), (3, 3)]
    assert "Fig" not in " ".join(d.text for d in drafts)
    for d in drafts:
        assert d.text in _window(pages, d.page_start, d.page_end)


def test_short_document_is_one_chunk() -> None:
    assert FixedWordChunker(size=250, overlap=40).chunk([_page(1, 20)]) == [
        ChunkDraft(ordinal=0, page_start=1, page_end=1, text=" ".join(f"p1w{i}" for i in range(20)))
    ]


def test_chunkers_from_config_builds_the_configured_list() -> None:
    (chunker,) = chunkers_from_config(["fixed_words"])
    assert isinstance(chunker, FixedWordChunker)
    assert dict(chunker.params) == {"size": 250, "overlap": 40}
    assert chunkers_from_config([]) == []


def test_chunkers_from_config_unknown_name() -> None:
    with pytest.raises(UnknownChunkerError, match=r"semantic.*fixed_words"):
        chunkers_from_config(["fixed_words", "semantic"])
