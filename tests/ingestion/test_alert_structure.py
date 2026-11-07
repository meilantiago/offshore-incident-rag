"""AC-002-06: `structure_aware` on Safety Alerts.

`tests/fixtures/bsee/safety-alert-526-trimmed.pdf` is Safety Alert 526 (see SOURCES.md): 3 pages, a header block with
`Contact:` and `Phone:` lines, heading lines ending in `:` (`Background:`, `Incident 1 (Figure 1):`, `Incident
Findings:` ...) and two figure captions whose photograph was removed. The MMS-era "Notice No. 7" alert is generated
by tests/support/pdfs.py: a header block and five numbered paragraphs, no heading line.
"""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from tests.support import pdfs
from tests.support.structure import (
    ALERT_PDF,
    ALERT_REMOVAL,
    NO_REMOVAL,
    SIZE_CAP,
    PageRow,
    assert_cuts_at_breaks,
    assert_tiles,
    chunk_pdf,
    concat_words,
    greedy_groups,
    kept_lines,
    kept_words,
    norm,
    norm_label,
    parsed_pages,
    words,
)

CONTACT = "engagement@bsee.gov"
PHONE = "(800) 200-4853"
CAPTIONS = ("Figure 1: Ruptured battery below crane operator", "Figure 2: Battery explosion that led to an employee")


def _alert(size_cap: int | None) -> tuple[list[dict[str, Any]], list[PageRow]]:
    return chunk_pdf(ALERT_PDF.read_bytes(), "safety_alert", size_cap)


def _alert_length() -> int:
    return sum(len(words(text)) for _, text, _ in parsed_pages(ALERT_PDF.read_bytes()))


def test_ac_002_06_alert_within_the_cap_is_one_chunk_with_the_whole_text() -> None:
    """AC-002-06: with a size cap at least the alert's length, the alert is exactly one chunk, pages 1 to 3."""
    cap = _alert_length()

    chunks, pages = _alert(cap)

    assert len(chunks) == 1, f"expected one chunk with size_cap={cap}, got {len(chunks)}"
    (chunk,) = chunks
    assert (chunk["page_start"], chunk["page_end"]) == (1, 3)
    assert words(chunk["text"]) == [w for _, w in kept_words(pages, ALERT_REMOVAL)], (
        "the single chunk is not the whole alert text (minus the Contact and Phone lines)"
    )
    assert chunk.get("section"), "the chunk records a non-empty section label"


@pytest.mark.parametrize("size_cap", [SIZE_CAP, 80])
def test_ac_002_06_smaller_cap_cuts_only_at_heading_lines_or_inside_long_sections(size_cap: int) -> None:
    """AC-002-06: below the alert's length, boundaries fall at heading lines ending in `:` or inside a section
    over the cap (splitting rule); nothing is lost or repeated."""
    assert _alert_length() > size_cap, "fixture precondition: the alert is longer than the cap"

    chunks, pages = _alert(size_cap)

    lines = kept_lines(pages, ALERT_REMOVAL)
    headings = [line for _, line in lines if line.endswith(":")]
    assert len(chunks) >= 2, f"the alert is over the cap {size_cap}; got {len(chunks)} chunk(s)"
    assert_tiles(chunks, kept_words(pages, ALERT_REMOVAL), f"alert cap {size_cap}")
    by_label: dict[str, list[dict[str, Any]]] = {}
    for c in chunks:
        by_label.setdefault(norm_label(c.get("section")), []).append(c)
    for prev, nxt in itertools.pairwise(chunks):
        if norm_label(prev.get("section")) != norm_label(nxt.get("section")):
            opening = [h for h in headings if words(nxt["text"])[: len(words(h))] == words(h)]
            assert opening, (
                f"chunk {nxt['ordinal']} ({nxt.get('section')!r}) starts a new section but not at a heading line "
                f"ending in ':': {' '.join(words(nxt['text'])[:10])!r}"
            )
            assert norm_label(opening[0]) == norm_label(nxt.get("section")), (
                f"chunk {nxt['ordinal']} opens at {opening[0]!r} but is labelled {nxt.get('section')!r}"
            )
        else:
            section = by_label[norm_label(prev.get("section"))]
            assert len(concat_words(section)) > size_cap, (
                f"chunks {prev['ordinal']} and {nxt['ordinal']} split section {prev.get('section')!r}, "
                f"which fits the cap {size_cap}"
            )
    for label, pieces in by_label.items():
        assert_cuts_at_breaks(pieces, size_cap, f"alert section {label!r}")
    for heading in ("Background:", "Incident Findings:"):
        assert any(words(c["text"])[: len(words(heading))] == words(heading) for c in chunks), (
            f"no chunk starts at the heading line {heading!r}"
        )


@pytest.mark.parametrize("size_cap", [None, 80, 100_000], ids=["default-cap", "cap-80", "whole"])
def test_ac_002_06_contact_and_phone_lines_removed_captions_kept(size_cap: int | None) -> None:
    """AC-002-06: no chunk contains the Contact or Phone line; the photo captions stay in the text."""
    chunks, pages = _alert(size_cap)
    page1 = next(text for n, text, _ in pages if n == 1)
    assert CONTACT in page1 and PHONE in page1, "fixture precondition: the header block has Contact and Phone"

    assert chunks, "no structure_aware chunk for the alert fixture"
    text = norm(" ".join(c["text"] for c in chunks))
    assert CONTACT not in text, "the Contact line is in a chunk"
    assert PHONE not in text, "the Phone line is in a chunk"
    assert "Contact:" not in text and "Phone:" not in text
    for caption in CAPTIONS:
        assert caption in text, f"the photo caption {caption!r} must stay in the text"
    assert "Safety Alert No. 526" in text and "Date: Oct. 30, 2026" in text, "only Contact and Phone are removed"


def test_ac_002_06_notice_alert_that_fits_is_one_chunk() -> None:
    """AC-002-06: an MMS-era "Notice No. N" alert with no heading lines that fits the cap is one chunk."""
    paragraphs = pdfs.notice_alert_paragraphs()
    total = sum(len(words(" ".join(p))) for p in paragraphs)
    assert total <= SIZE_CAP, "fixture precondition: the notice fits the default cap"

    chunks, pages = chunk_pdf(pdfs.notice_alert_pdf(), "safety_alert")

    assert len(chunks) == 1, f"a notice of {total} words fits the cap of {SIZE_CAP}; got {len(chunks)} chunks"
    assert words(chunks[0]["text"]) == [w for _, w in kept_words(pages, NO_REMOVAL)]
    assert (chunks[0]["page_start"], chunks[0]["page_end"]) == (1, 1)
    assert chunks[0].get("section") == "alert", "an alert with no heading lines is labelled `alert`"


def test_ac_002_06_notice_alert_over_the_cap_is_split_at_paragraph_breaks() -> None:
    """AC-002-06: a notice over the cap is split at the last paragraph break within the cap, every time."""
    cap = 100
    paragraphs = [words(" ".join(p)) for p in pdfs.notice_alert_paragraphs()]
    assert max(len(p) for p in paragraphs) <= cap < sum(len(p) for p in paragraphs), "fixture precondition"
    expected = [[w for i in group for w in paragraphs[i]] for group in greedy_groups([len(p) for p in paragraphs], cap)]

    chunks, _ = chunk_pdf(pdfs.notice_alert_pdf(), "safety_alert", cap)

    assert [words(c["text"]) for c in chunks] == expected, (
        f"expected {len(expected)} chunks of whole paragraphs ({[len(e) for e in expected]} words), got "
        f"{[len(words(c['text'])) for c in chunks]}"
    )
    assert all(c.get("section") == "alert" for c in chunks), "every chunk of a notice is labelled `alert`"
