"""`build_structural_report` on hand-built chunks (spec 002 T10, T92, AC-002-10, AC-002-11, AC-002-13)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest

from offshore_rag.ingestion.chunking import FixedWordChunker
from offshore_rag.ingestion.pdf import PageText
from offshore_rag.ingestion.store import ReportChunk
from offshore_rag.ingestion.structural_report import (
    NoChunksError,
    StaleChunkSet,
    StrategyMetrics,
    StructuralReport,
    build_structural_report,
    size_distribution,
)
from offshore_rag.ingestion.structure_aware import StructureAwareChunker

FIXED = "fixed_words"
STRUCTURE = "structure_aware"
FIELD_17 = "17 INVESTIGATION FINDINGS"
FIELD_18 = "18 LIST THE PROBABLE CAUSE(S) OF ACCIDENT"

DISTRICT_PAGES = [
    PageText(1, "MMS - FORM 2010\nFIRE EXPLOSION FATALITY COLLISION\nLease 123", False),
    PageText(
        2,
        "For Public Release\n17. INVESTIGATION FINDINGS:\nThe crane boom failed.\n"
        "18. LIST THE PROBABLE CAUSE(S) OF ACCIDENT:\nWorn sling.",
        False,
    ),
]
DISTRICT_ALL = " ".join(" ".join(p.text.split()) for p in DISTRICT_PAGES)
TEXT_17 = "17. INVESTIGATION FINDINGS: The crane boom failed."
TEXT_18 = "18. LIST THE PROBABLE CAUSE(S) OF ACCIDENT: Worn sling."
UNRECOGNIZED_PAGES = [PageText(1, "A district report without any numbered field.", False)]


@dataclass
class FakeSource:
    pages: dict[int, list[PageText]] = field(default_factory=dict)
    chunks: list[ReportChunk] = field(default_factory=list)

    def chunks_for_report(self, strategies: Sequence[str] | None) -> list[ReportChunk]:
        return [c for c in self.chunks if strategies is None or c.chunker in strategies]

    def load_pages(self, document_id: int) -> list[PageText]:
        return self.pages[document_id]


def _chunk(
    doc: int,
    chunker: str,
    ordinal: int,
    pages: tuple[int, int],
    text: str,
    section: str | None = None,
    doc_type: str = "district_report",
    params: dict[str, Any] | None = None,
) -> ReportChunk:
    return ReportChunk(
        document_id=doc,
        source_url=f"https://example.test/{doc}.pdf",
        doc_type=doc_type,
        chunker=chunker,
        chunker_params=params or {},
        ordinal=ordinal,
        page_start=pages[0],
        page_end=pages[1],
        text=text,
        section=section,
    )


def _entry(report: StructuralReport, strategy: str, doc_type: str = "district_report") -> StrategyMetrics:
    [entry] = [e for e in report.entries if (e.strategy, e.doc_type) == (strategy, doc_type)]
    return entry


def _district_source() -> FakeSource:
    return FakeSource(
        {1: DISTRICT_PAGES},
        [
            _chunk(1, FIXED, 0, (1, 2), DISTRICT_ALL),
            _chunk(1, STRUCTURE, 0, (2, 2), TEXT_17, FIELD_17),
            _chunk(1, STRUCTURE, 1, (2, 2), TEXT_18, FIELD_18),
        ],
    )


def test_size_distribution_percentiles() -> None:
    assert size_distribution(list(range(1, 12))) == {"min": 1, "p10": 2, "median": 6, "p90": 10, "max": 11}
    assert size_distribution([7]) == {"min": 7, "p10": 7, "median": 7, "p90": 7, "max": 7}
    assert size_distribution([1, 2])["median"] == 1.5


def test_fixed_words_chunk_spanning_the_grid_and_two_fields() -> None:
    entry = _entry(build_structural_report(_district_source(), None), FIXED)

    assert (entry.documents, entry.chunks, entry.structure_not_recognized) == (1, 1, 0)
    n = len(DISTRICT_ALL.split())
    assert entry.size_words == {"min": n, "p10": n, "median": n, "p90": n, "max": n}
    assert entry.multi_page_share == 1.0
    assert entry.page_header_share == 1.0
    assert entry.checkbox_grid_share == 1.0
    assert entry.boundary_crossing_share == 1.0
    assert entry.missing_sections == []


def test_structure_aware_chunks_carry_no_noise() -> None:
    entry = _entry(build_structural_report(_district_source(), [STRUCTURE]), STRUCTURE)

    assert (entry.documents, entry.chunks) == (1, 2)
    assert entry.multi_page_share == 0.0
    assert entry.page_header_share == 0.0
    assert entry.checkbox_grid_share == 0.0
    assert entry.boundary_crossing_share == 0.0
    assert entry.missing_sections == []


def test_segment_in_no_chunk_is_named_as_missing() -> None:
    source = _district_source()
    source.chunks = [c for c in source.chunks if c.chunker == STRUCTURE and c.ordinal == 0]

    entry = _entry(build_structural_report(source, None), STRUCTURE)

    assert entry.missing_sections == [{"source_url": "https://example.test/1.pdf", "sections": [FIELD_18]}]


def test_unrecognized_document_counts_in_totals_but_not_in_crossing() -> None:
    source = _district_source()
    source.pages[2] = UNRECOGNIZED_PAGES
    source.chunks.append(_chunk(2, FIXED, 0, (1, 1), " ".join(UNRECOGNIZED_PAGES[0].text.split())))

    entry = _entry(build_structural_report(source, [FIXED]), FIXED)

    assert (entry.documents, entry.chunks, entry.structure_not_recognized) == (2, 2, 1)
    assert entry.page_header_share == 0.5
    assert entry.boundary_crossing_share == 1.0  # only the chunk of the recognized document is measured


def test_grid_share_is_for_district_reports_only() -> None:
    pages = [PageText(1, "Safety Alert 9\nFIRE EXPLOSION FATALITY COLLISION words.", False)]
    drafts = FixedWordChunker(size=250, overlap=0).chunk(pages, "safety_alert")
    source = FakeSource(
        {5: pages},
        [_chunk(5, FIXED, d.ordinal, (d.page_start, d.page_end), d.text, doc_type="safety_alert") for d in drafts],
    )

    entry = _entry(build_structural_report(source, None), FIXED, "safety_alert")

    assert entry.checkbox_grid_share is None


def test_alert_kept_whole_does_not_cross_its_headings() -> None:
    pages = [PageText(1, "Safety Alert 9\nContact: J. Doe\nBackground:\nA fire.\nRecommendations:\nCheck it.", False)]
    chunker = StructureAwareChunker()
    drafts = chunker.chunk(pages, "safety_alert")
    assert len(drafts) == 1
    source = FakeSource(
        {5: pages},
        [
            _chunk(
                5,
                STRUCTURE,
                d.ordinal,
                (d.page_start, d.page_end),
                d.text,
                d.section,
                "safety_alert",
                {**chunker.params},
            )
            for d in drafts
        ],
    )

    entry = _entry(build_structural_report(source, None), STRUCTURE, "safety_alert")

    assert entry.boundary_crossing_share == 0.0
    assert entry.missing_sections == []


def test_chunk_that_cannot_be_located_marks_its_set_stale() -> None:
    """AC-002-13: the set is left out of every metric of its entry and listed with the first ordinal not located."""
    source = _district_source()
    source.pages[2] = DISTRICT_PAGES
    source.chunks += [
        _chunk(2, STRUCTURE, 0, (2, 2), TEXT_17, FIELD_17),
        _chunk(2, STRUCTURE, 1, (2, 2), "words that are nowhere", "x"),
        _chunk(2, STRUCTURE, 2, (2, 2), "nor are these", "x"),
        _chunk(2, FIXED, 0, (1, 2), DISTRICT_ALL),
    ]

    report = build_structural_report(source, None)

    assert report.stale_chunk_sets == [
        StaleChunkSet("https://example.test/2.pdf", "district_report", STRUCTURE, 1),
    ]
    stale = _entry(report, STRUCTURE)
    assert (stale.documents, stale.chunks, stale.structure_not_recognized) == (1, 2, 0)
    assert stale.size_words == size_distribution([len(TEXT_17.split()), len(TEXT_18.split())])
    assert stale.multi_page_share == 0.0 and stale.boundary_crossing_share == 0.0
    assert stale.missing_sections == []
    assert (_entry(report, FIXED).documents, _entry(report, FIXED).chunks) == (2, 2)  # not stale: untouched
    assert report.to_json()["stale_chunk_sets"] == [
        {"source_url": "https://example.test/2.pdf", "doc_type": "district_report", "strategy": STRUCTURE, "ordinal": 1}
    ]


def test_entry_whose_only_set_is_stale_is_left_out() -> None:
    source = _district_source()
    source.chunks = [c for c in source.chunks if c.chunker == FIXED]
    source.chunks.append(_chunk(1, STRUCTURE, 0, (2, 2), "words that are nowhere", "x"))

    report = build_structural_report(source, None)

    assert [(e.strategy, e.doc_type) for e in report.entries] == [(FIXED, "district_report")]
    assert [s.ordinal for s in report.stale_chunk_sets] == [0]


def test_report_without_stale_sets_has_an_empty_list() -> None:
    report = build_structural_report(_district_source(), None)

    assert report.stale_chunk_sets == []
    assert report.to_json()["stale_chunk_sets"] == []


def test_requested_strategy_without_chunks_raises_naming_it() -> None:
    source = _district_source()
    source.chunks = [c for c in source.chunks if c.chunker == FIXED]

    with pytest.raises(NoChunksError, match=STRUCTURE):
        build_structural_report(source, [FIXED, STRUCTURE])
    with pytest.raises(NoChunksError):
        build_structural_report(FakeSource(), None)


def test_report_json_has_one_entry_per_strategy_and_doc_type() -> None:
    data = build_structural_report(_district_source(), None).to_json()

    assert data["strategies"] == [FIXED, STRUCTURE]
    assert [(e["strategy"], e["doc_type"]) for e in data["entries"]] == [
        (FIXED, "district_report"),
        (STRUCTURE, "district_report"),
    ]
    assert data["entries"][0]["chunks"] == 1
