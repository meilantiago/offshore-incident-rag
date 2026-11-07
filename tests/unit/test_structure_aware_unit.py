"""`StructureAwareChunker` (spec 002, T06): splitting rule, image-only cuts, fallback, parameters."""

from __future__ import annotations

import pytest

from offshore_rag.ingestion.chunking import ChunkDraft, Chunker, ChunkerPlan
from offshore_rag.ingestion.pdf import PageText
from offshore_rag.ingestion.structure_aware import NOT_RECOGNIZED, StructureAwareChunker


def _page(number: int, lines: list[str]) -> PageText:
    return PageText(number=number, text="\n".join(lines), image_only=False)


def _image_page(number: int) -> PageText:
    return PageText(number=number, text="", image_only=True)


def _sizes(drafts: list[ChunkDraft]) -> list[int]:
    return [len(d.text.split()) for d in drafts]


def _all_words(pages: list[PageText]) -> list[str]:
    return [w for p in pages if not p.image_only for w in p.text.split()]


GRID = ["ACCIDENT INVESTIGATION REPORT", "FIRE", "EXPLOSION", "MMS - FORM 2010 PAGE: 1 OF 3"]


def test_identity_and_params() -> None:
    chunker = StructureAwareChunker()

    assert chunker.id == "structure_aware"
    assert dict(chunker.params) == {"size_cap": 250, "version": 1}
    assert isinstance(chunker, Chunker)


@pytest.mark.parametrize("size_cap", [0, -5])
def test_invalid_size_cap_is_rejected(size_cap: int) -> None:
    with pytest.raises(ValueError, match="size_cap"):
        StructureAwareChunker(size_cap=size_cap)


def test_registered_in_the_strategy_registry() -> None:
    from offshore_rag.config import Settings

    settings = Settings(_env_file=None, chunkers=["fixed_words", "structure_aware"])  # type: ignore[call-arg]
    chunkers = ChunkerPlan.from_settings(settings).for_doc_type("panel_report")

    assert [c.id for c in chunkers] == ["fixed_words", "structure_aware"]
    assert dict(chunkers[1].params) == {"size_cap": 250, "version": 1}


def test_cut_at_the_last_paragraph_break_within_the_cap() -> None:
    # Paragraphs end at a short line ending in '.'; "kk." is a sentence break, but a paragraph break wins.
    pages = [_page(1, ["aa bb cc dd ee ff gg hh", "ii jj.", "kk. Ll mm nn oo pp qq rr", "ss tt."])]

    drafts = StructureAwareChunker(size_cap=12).chunk(pages, "safety_alert")

    assert [d.text for d in drafts] == ["aa bb cc dd ee ff gg hh ii jj.", "kk. Ll mm nn oo pp qq rr ss tt."]
    assert {d.section for d in drafts} == {"alert"}


def test_cut_at_the_last_sentence_break_then_at_the_cap_word() -> None:
    pages = [_page(1, ["aa bb cc. Dd ee ff gg hh", "ii jj kk ll. Mm nn oo pp", "qq rr ss tt uu vv ww xx"])]

    drafts = StructureAwareChunker(size_cap=10).chunk(pages, "safety_alert")

    assert _sizes(drafts) == [3, 9, 10, 2]
    assert drafts[0].text == "aa bb cc."
    assert drafts[1].text.endswith("ll.")
    assert [w for d in drafts for w in d.text.split()] == _all_words(pages)
    assert [d.ordinal for d in drafts] == [0, 1, 2, 3]


def test_hard_cut_at_the_cap_without_any_break() -> None:
    words = [f"w{i:02d}" for i in range(25)]
    pages = [_page(1, [" ".join(words[i : i + 5]) for i in range(0, 25, 5)])]

    drafts = StructureAwareChunker(size_cap=10).chunk(pages, "safety_alert")

    assert _sizes(drafts) == [10, 10, 5]
    assert [w for d in drafts for w in d.text.split()] == words


def test_alert_that_fits_the_cap_is_one_chunk_even_with_headings() -> None:
    pages = [
        _page(1, ["Title of the alert", "Contact: someone@example.gov", "Background:", "Some text here."]),
        _page(2, ["Recommendations:", "Do this."]),
    ]

    drafts = StructureAwareChunker(size_cap=50).chunk(pages, "safety_alert")

    assert len(drafts) == 1
    assert (drafts[0].page_start, drafts[0].page_end) == (1, 2)
    assert drafts[0].text == "Title of the alert Background: Some text here. Recommendations: Do this."
    assert drafts[0].section == "alert"


def test_alert_over_the_cap_is_cut_at_its_heading_lines() -> None:
    pages = [_page(1, ["Title of the alert", "Background:", "Some text here.", "Recommendations:", "Do this now."])]

    drafts = StructureAwareChunker(size_cap=5).chunk(pages, "safety_alert")

    assert [(d.section, d.text) for d in drafts] == [
        ("preamble", "Title of the alert"),
        ("Background", "Background: Some text here."),
        ("Recommendations", "Recommendations: Do this now."),
    ]


def test_district_fields_removed_content_and_labels() -> None:
    pages = [
        _page(1, GRID),
        _page(
            2,
            [
                "17. INVESTIGATION FINDINGS:",
                "For Public Release",
                "The crew lifted the load.",
                "18. LIST THE PROBABLE CAUSE(S) OF ACCIDENT:",
                "Inattention.",
                "MMS - FORM 2010 PAGE: 2 OF 2",
                "EV2010R 05-JAN-2021",
            ],
        ),
    ]

    drafts = StructureAwareChunker().chunk(pages, "district_report")

    assert [(d.section, d.text, d.page_start, d.page_end) for d in drafts] == [
        ("17 INVESTIGATION FINDINGS", "17. INVESTIGATION FINDINGS: The crew lifted the load.", 2, 2),
        ("18 LIST THE PROBABLE CAUSE(S) OF ACCIDENT", "18. LIST THE PROBABLE CAUSE(S) OF ACCIDENT: Inattention.", 2, 2),
    ]


def test_a_segment_is_cut_at_an_image_only_page() -> None:
    pages = [
        _page(1, GRID),
        _page(2, ["17. INVESTIGATION FINDINGS:", "before the photograph"]),
        _image_page(3),
        _page(4, ["after the photograph", "18. LIST THE PROBABLE CAUSE(S) OF ACCIDENT:", "Unknown."]),
    ]

    drafts = StructureAwareChunker().chunk(pages, "district_report")

    assert [(d.section, d.page_start, d.page_end, d.text) for d in drafts] == [
        ("17 INVESTIGATION FINDINGS", 2, 2, "17. INVESTIGATION FINDINGS: before the photograph"),
        ("17 INVESTIGATION FINDINGS", 4, 4, "after the photograph"),
        ("18 LIST THE PROBABLE CAUSE(S) OF ACCIDENT", 4, 4, "18. LIST THE PROBABLE CAUSE(S) OF ACCIDENT: Unknown."),
    ]


def test_a_segment_crosses_a_text_page_break() -> None:
    pages = [
        _page(1, GRID),
        _page(2, ["17. INVESTIGATION FINDINGS:", "first part", "MMS - FORM 2010 PAGE: 2 OF 3"]),
        _page(3, ["For Public Release", "second part"]),
    ]

    drafts = StructureAwareChunker().chunk(pages, "district_report")

    assert [(d.page_start, d.page_end, d.text) for d in drafts] == [
        (2, 3, "17. INVESTIGATION FINDINGS: first part second part")
    ]


@pytest.mark.parametrize("doc_type", ["district_report", "panel_report"])
def test_unrecognized_structure_falls_back_to_labelled_fixed_windows(doc_type: str) -> None:
    words = [f"w{i:02d}" for i in range(27)]
    pages = [
        _page(1, [" ".join(words[0:9])]),
        _page(2, [" ".join(words[9:18])]),
        _image_page(3),
        _page(4, [" ".join(words[18:27])]),
    ]

    drafts = StructureAwareChunker(size_cap=10).chunk(pages, doc_type)  # type: ignore[arg-type]

    assert _sizes(drafts) == [10, 8, 9]
    assert [(d.page_start, d.page_end) for d in drafts] == [(1, 2), (2, 2), (4, 4)]
    assert [w for d in drafts for w in d.text.split()] == words
    assert {d.section for d in drafts} == {NOT_RECOGNIZED}
    assert [d.ordinal for d in drafts] == [0, 1, 2]
