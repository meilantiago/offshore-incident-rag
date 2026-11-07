"""AC-002-03, AC-002-04: `structure_aware` on the committed district report (MMS Form 2010).

The fixture is `tests/fixtures/bsee/district-mp-42-l-2020.pdf` (see SOURCES.md): page 1 is the checkbox grid, fields
17 to 23 have text (17 is over 250 words), field 24 has only its title, and every page carries the repeated header.
The expected field texts are cut from the parsed pages by hand-written rules (tests/support/structure.py), not by
the code under test.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.support.structure import (
    DISTRICT_HEADER_RE,
    DISTRICT_PDF,
    DISTRICT_REMOVAL,
    SIZE_CAP,
    PageRow,
    assert_cuts_at_breaks,
    chunk_pdf,
    concat_words,
    kept_lines,
    norm,
    norm_label,
    page_lines,
    words,
)

FIELD_TITLES = {
    17: "INVESTIGATION FINDINGS",
    18: "LIST THE PROBABLE CAUSE(S) OF ACCIDENT",
    19: "LIST THE CONTRIBUTING CAUSE(S) OF ACCIDENT",
    20: "LIST THE ADDITIONAL INFORMATION",
    21: "PROPERTY DAMAGED",
    22: "RECOMMENDATIONS TO PREVENT RECURRANCE NARRATIVE",
    23: "POSSIBLE OCS VIOLATIONS RELATED TO ACCIDENT",
    24: "SPECIFY VIOLATIONS DIRECTLY OR INDIRECTLY CONTRIBUTING",
}
# Fields with text besides their title in this fixture (24 holds only "24. SPECIFY ... CONTRIBUTING. NARRATIVE:").
FIELDS_WITH_TEXT = (17, 18, 19, 20, 21, 22, 23)
FIELD_START_RE = re.compile(r"^(\d{1,2})\.\s+\S")
GRID_LABELS = ("FIRE", "EXPLOSION", "FATALITY", "COLLISION", "POLLUTION")


def _fields(pages: list[PageRow]) -> dict[int, list[str]]:
    """Kept lines of each numbered field from 17 on, by field number (a field ends where the next one starts)."""
    fields: dict[int, list[str]] = {}
    current: int | None = None
    for _, line in kept_lines(pages, DISTRICT_REMOVAL):
        m = FIELD_START_RE.match(line)
        if m and 17 <= int(m.group(1)) <= 30:
            current = int(m.group(1))
            fields[current] = []
        if current is not None:
            fields[current].append(line)
    assert set(FIELD_TITLES) <= set(fields), f"fixture fields not found: {sorted(set(FIELD_TITLES) - set(fields))}"
    return fields


def _field_of(label: str | None) -> int | None:
    m = re.search(r"\b(\d{1,2})\b", label or "")  # "17 INVESTIGATION FINDINGS", "Field 17: ..."
    return int(m.group(1)) if m else None


def _chunks(size_cap: int | None = None) -> tuple[list[dict[str, Any]], dict[int, list[str]], list[PageRow]]:
    chunks, pages = chunk_pdf(DISTRICT_PDF.read_bytes(), "district_report", size_cap)
    return chunks, _fields(pages), pages


def _field_chunks(chunks: list[dict[str, Any]], number: int) -> list[dict[str, Any]]:
    return [c for c in chunks if _field_of(c.get("section")) == number]


@pytest.mark.parametrize("size_cap", [None, 60], ids=["default-cap", "cap-60"])
def test_ac_002_03_every_filled_field_is_in_chunks_labelled_with_its_number_and_title(size_cap: int | None) -> None:
    """AC-002-03: each field 17-24 with text is in chunks whose label names its number and title; all its words."""
    chunks, fields, _ = _chunks(size_cap)

    assert chunks, "no structure_aware chunk for the district fixture"
    for number in FIELDS_WITH_TEXT:
        mine = _field_chunks(chunks, number)
        assert mine, f"no chunk labelled with field {number}; labels: {sorted({str(c.get('section')) for c in chunks})}"
        for c in mine:
            assert norm_label(FIELD_TITLES[number]) in norm_label(c["section"]), (
                f"label {c['section']!r} does not name field {number} {FIELD_TITLES[number]}"
            )
        assert concat_words(mine) == words(" ".join(fields[number])), (
            f"the chunks of field {number}, in order, are not exactly the words of field {number}"
        )


@pytest.mark.parametrize("size_cap", [None, 60], ids=["default-cap", "cap-60"])
def test_ac_002_03_no_chunk_holds_text_from_two_fields(size_cap: int | None) -> None:
    """AC-002-03: a chunk labelled with a field holds only that field's text; no other chunk holds field text."""
    chunks, fields, _ = _chunks(size_cap)

    assert chunks, "no structure_aware chunk for the district fixture"
    field_text = {n: norm(" ".join(lines)) for n, lines in fields.items()}
    for c in chunks:
        text = norm(c["text"])
        number = _field_of(c.get("section"))
        if number is not None and number in FIELD_TITLES:
            assert text in field_text[number], (
                f"chunk {c['ordinal']} labelled {c['section']!r} holds text outside field {number}: {text[:120]!r}"
            )
        else:
            for n in FIELDS_WITH_TEXT:
                for line in fields[n]:
                    if len(words(line)) >= 3:
                        assert norm(line) not in text, (
                            f"chunk {c['ordinal']} labelled {c.get('section')!r} holds text of field {n}: {line!r}"
                        )


def test_ac_002_03_long_field_is_split_within_the_cap_without_overlap() -> None:
    """AC-002-03: field 17 (over 250 words) is split by the splitting rule into pieces of at most 250 words."""
    chunks, fields, _ = _chunks()
    field17 = words(" ".join(fields[17]))
    assert len(field17) > SIZE_CAP, "fixture precondition: field 17 is longer than the size cap"

    pieces = _field_chunks(chunks, 17)

    assert len(pieces) >= 2, f"field 17 has {len(field17)} words and must be split; got {len(pieces)} chunk(s)"
    assert len({c["section"] for c in pieces}) == 1, "the pieces of one field share its section label"
    assert concat_words(pieces) == field17, "the pieces of field 17 overlap, skip or reorder words"
    assert_cuts_at_breaks(pieces, SIZE_CAP, "field 17")


def test_ac_002_03_fields_split_with_a_small_cap_follow_the_splitting_rule() -> None:
    """AC-002-03: with the size cap set to 60, every field over 60 words is split at breaks, without overlap."""
    chunks, fields, _ = _chunks(60)

    split = 0
    for number in FIELDS_WITH_TEXT:
        pieces = _field_chunks(chunks, number)
        assert concat_words(pieces) == words(" ".join(fields[number])), f"field {number}: words lost or repeated"
        if len(words(" ".join(fields[number]))) > 60:
            split += 1
            assert len(pieces) >= 2, f"field {number} is over the cap of 60 and must be split"
        assert_cuts_at_breaks(pieces, 60, f"field {number}")
    assert split >= 1, "fixture precondition: at least one field is over 60 words"


@pytest.mark.parametrize("size_cap", [None, 60], ids=["default-cap", "cap-60"])
def test_ac_002_04_no_chunk_contains_page_one_text(size_cap: int | None) -> None:
    """AC-002-04: no chunk starts on or contains page 1: no grid option labels, no loose page-1 field."""
    chunks, _, pages = _chunks(size_cap)
    page1 = next(text for n, text, _ in pages if n == 1)
    assert all(label in page1 for label in GRID_LABELS), "fixture precondition: page 1 holds the checkbox grid"

    body = norm(" ".join(line for _, line in kept_lines(pages, DISTRICT_REMOVAL)))

    assert chunks, "no structure_aware chunk for the district fixture"
    for c in chunks:
        assert c["page_start"] >= 2, f"chunk {c['ordinal']} starts on page 1"
        found = [label for label in GRID_LABELS if re.search(rf"\b{label}\b", c["text"])]
        assert not found, f"chunk {c['ordinal']} contains checkbox-grid labels {found}"
        for line in page_lines(page1):
            if len(words(line)) >= 3 and not DISTRICT_HEADER_RE.search(line) and norm(line) not in body:
                assert norm(line) not in norm(c["text"]), f"chunk {c['ordinal']} contains page-1 text {line!r}"


@pytest.mark.parametrize("size_cap", [None, 60], ids=["default-cap", "cap-60"])
def test_ac_002_04_no_chunk_contains_a_repeated_page_header_line(size_cap: int | None) -> None:
    """AC-002-04: no chunk contains `PAGE: N OF`, `MMS - FORM 2010`, `EV2010R` or `For Public Release`."""
    chunks, _, pages = _chunks(size_cap)
    assert sum(len(DISTRICT_HEADER_RE.findall(t)) for n, t, _ in pages if n > 1) >= 6, "fixture precondition"

    assert chunks, "no structure_aware chunk for the district fixture"
    for c in chunks:
        m = DISTRICT_HEADER_RE.search(c["text"])
        assert m is None, f"chunk {c['ordinal']} ({c.get('section')!r}) contains the page header {m.group(0)!r}"
