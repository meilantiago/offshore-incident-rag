"""AC-002-05: `structure_aware` on the committed panel report fixture.

`tests/fixtures/bsee/panel-mms-2009-042-trimmed.pdf` is pages 3-9 of OCS Report MMS 2009-042 (see SOURCES.md):
page 1 Contents, page 2 List of Figures (and Tables), pages 3-4 Abbreviations and Acronyms, pages 5-6 Executive
Summary (over 250 words), page 7 Introduction, Authority and Background. Every page starts with its page-number line.
Spec open question 15: coverage is checked against the headings present in the fixture, not every Contents entry.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.structure import (
    PANEL_PDF,
    PANEL_REMOVAL,
    SIZE_CAP,
    PageRow,
    assert_cuts_at_breaks,
    chunk_pdf,
    concat_words,
    kept_lines,
    norm,
    norm_label,
    page_lines,
    with_label,
    words,
)

ACRONYMS_HEADING = "Abbreviations and Acronyms"
SECTION_TITLES = ("Executive Summary", "Introduction", "Authority", "Background")
CONTENTS_PAGE, FIGURES_PAGE = 1, 2


def _sections(pages: list[PageRow]) -> dict[str, list[str]]:
    """Kept lines of each section, keyed by its title (`acronyms` for the list of acronyms)."""
    headings = {norm_label(t): t for t in SECTION_TITLES} | {norm_label(ACRONYMS_HEADING): "acronyms"}
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for _, line in kept_lines(pages, PANEL_REMOVAL):
        key = headings.get(norm_label(line))
        if key is not None:
            assert key not in sections, f"fixture precondition: heading {line!r} appears twice"
            current = key
            sections[key] = []
        assert current is not None, f"fixture precondition: text before the first heading: {line!r}"
        sections[current].append(line)
    assert set(sections) == {*SECTION_TITLES, "acronyms"}, f"fixture headings: {sorted(sections)}"
    return sections


def _chunks(size_cap: int | None = None) -> tuple[list[dict[str, Any]], dict[str, list[str]], list[PageRow]]:
    chunks, pages = chunk_pdf(PANEL_PDF.read_bytes(), "panel_report", size_cap)
    return chunks, _sections(pages), pages


@pytest.mark.parametrize("size_cap", [None, 60], ids=["default-cap", "cap-60"])
def test_ac_002_05_every_heading_is_in_a_chunk_labelled_with_its_section_title(size_cap: int | None) -> None:
    """AC-002-05: each section heading in the fixture opens chunks labelled with that section's title."""
    chunks, sections, _ = _chunks(size_cap)

    assert chunks, "no structure_aware chunk for the panel fixture"
    for title in SECTION_TITLES:
        mine = with_label(chunks, title)
        assert mine, f"no chunk labelled {title!r}; labels: {sorted({str(c.get('section')) for c in chunks})}"
        heading = words(sections[title][0])
        assert words(mine[0]["text"])[: len(heading)] == heading, f"the heading of {title!r} is not in its chunk"


@pytest.mark.parametrize("size_cap", [None, 60], ids=["default-cap", "cap-60"])
def test_ac_002_05_no_chunk_holds_text_from_two_sections(size_cap: int | None) -> None:
    """AC-002-05: the chunks of each label are exactly that section's words; no chunk mixes two sections."""
    chunks, sections, _ = _chunks(size_cap)

    assert chunks, "no structure_aware chunk for the panel fixture"
    known = {norm_label(k) for k in sections}
    stray = [(c["ordinal"], c.get("section")) for c in chunks if norm_label(c.get("section")) not in known]
    assert not stray, f"chunks with a label that is no section of the fixture: {stray}"
    for key, lines in sections.items():
        assert concat_words(with_label(chunks, key)) == words(" ".join(lines)), (
            f"the chunks labelled {key!r} are not exactly the words of that section"
        )


@pytest.mark.parametrize("size_cap", [SIZE_CAP, 60])
def test_ac_002_05_long_sections_are_split_within_the_cap(size_cap: int) -> None:
    """AC-002-05: a section over the size cap is split by the splitting rule into pieces within the cap."""
    chunks, sections, _ = _chunks(size_cap)
    summary = words(" ".join(sections["Executive Summary"]))
    assert len(summary) > SIZE_CAP, "fixture precondition: the Executive Summary is longer than 250 words"

    for key in sections:
        pieces = with_label(chunks, key)
        assert all(len(words(c["text"])) <= size_cap for c in pieces), f"{key}: a chunk is over the cap {size_cap}"
    pieces = with_label(chunks, "Executive Summary")
    assert len(pieces) >= 2, "the Executive Summary is over the cap and must be split"
    assert_cuts_at_breaks(pieces, size_cap, "Executive Summary")


@pytest.mark.parametrize("size_cap", [None, 60], ids=["default-cap", "cap-60"])
def test_ac_002_05_acronym_list_is_in_its_own_chunks_labelled_acronyms(size_cap: int | None) -> None:
    """AC-002-05: the list of acronyms is in its own chunk or chunks, labelled `acronyms`."""
    chunks, sections, _ = _chunks(size_cap)

    mine = [c for c in chunks if c.get("section") == "acronyms"]
    assert mine, f"no chunk labelled 'acronyms'; labels: {sorted({str(c.get('section')) for c in chunks})}"
    assert concat_words(mine) == words(" ".join(sections["acronyms"])), "acronym chunks are not exactly the list"
    others = norm(" ".join(c["text"] for c in chunks if c.get("section") != "acronyms"))
    for line in sections["acronyms"][1:]:
        if len(words(line)) >= 3:
            assert norm(line) not in others, f"acronym line {line!r} is also in a chunk of another label"


@pytest.mark.parametrize("size_cap", [None, 60], ids=["default-cap", "cap-60"])
def test_ac_002_05_contents_and_figure_list_are_in_no_chunk(size_cap: int | None) -> None:
    """AC-002-05: the Contents page and the figure-list page produce no chunk text."""
    chunks, _, pages = _chunks(size_cap)
    front = {n: text for n, text, _ in pages if n in (CONTENTS_PAGE, FIGURES_PAGE)}
    assert "Contents" in front[CONTENTS_PAGE] and "List of Figures" in front[FIGURES_PAGE], "fixture precondition"

    body = norm(" ".join(line for _, line in kept_lines(pages, PANEL_REMOVAL)))

    assert chunks, "no structure_aware chunk for the panel fixture"
    for c in chunks:
        assert c["page_start"] > FIGURES_PAGE, f"chunk {c['ordinal']} starts on a front-matter page"
        for n, text in front.items():
            for line in page_lines(text):
                # Lines that also occur in the body (a Contents entry repeated in the acronym list) prove nothing.
                if len(words(line)) >= 3 and norm(line) not in body:
                    assert norm(line) not in norm(c["text"]), f"chunk {c['ordinal']} holds page {n} line {line!r}"


@pytest.mark.parametrize("size_cap", [None, 60], ids=["default-cap", "cap-60"])
def test_ac_002_05_no_chunk_contains_a_page_number_line(size_cap: int | None) -> None:
    """AC-002-05: the first line of each page, which holds only its page number, is in no chunk."""
    chunks, _, pages = _chunks(size_cap)
    body = [(n, page_lines(text)) for n, text, _ in pages if n > FIGURES_PAGE]
    assert all(lines[0].isdigit() for _, lines in body), "fixture precondition: page-number first lines"

    texts = [norm(c["text"]) for c in chunks]
    assert texts, "no structure_aware chunk for the panel fixture"
    for i, (n, lines) in enumerate(body):
        number = lines[0]
        joined_after = norm(f"{number} {lines[1]}")
        assert not any(joined_after in t for t in texts), f"page {n}: its number {number!r} opens a chunk run"
        if i > 0:
            joined_before = norm(f"{body[i - 1][1][-1]} {number}")
            assert not any(joined_before in t for t in texts), f"page {n}: its number {number!r} follows page text"
    total = sum(len(words(t)) for t in texts)
    kept = sum(len(words(line)) for _, line in kept_lines(pages, PANEL_REMOVAL))
    assert total == kept, f"chunks hold {total} words, the pages minus removed content hold {kept}"
