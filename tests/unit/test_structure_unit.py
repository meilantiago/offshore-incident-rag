"""`detect_structure` (spec 002, T04 district reports, T05 panel reports and Safety Alerts)."""

from __future__ import annotations

import pytest

from offshore_rag.ingestion.pdf import PageText, parse_pdf
from offshore_rag.ingestion.structure import DocumentStructure, Segment, detect_structure
from tests.support import pdfs
from tests.support.ingest import FIXTURES

DISTRICT = FIXTURES / "district-mp-42-l-2020.pdf"
PANEL = FIXTURES / "panel-mms-2009-042-trimmed.pdf"
ALERT = FIXTURES / "safety-alert-526-trimmed.pdf"


def _pages(data: bytes) -> list[PageText]:
    return parse_pdf(data).pages


def _detect(data: bytes, doc_type: str) -> DocumentStructure:
    structure = detect_structure(_pages(data), doc_type)  # type: ignore[arg-type]
    assert structure is not None
    return structure


def _segment_text(structure: DocumentStructure, segment: Segment) -> list[str]:
    return [line.text for line in structure.lines[segment.first : segment.last + 1] if not line.removed]


def _labels(structure: DocumentStructure) -> list[str]:
    return [s.label for s in structure.segments]


# -- district reports (Form 2010) ------------------------------------------------------------------------------
def test_district_page_one_and_header_lines_are_removed() -> None:
    structure = _detect(DISTRICT.read_bytes(), "district_report")

    page1 = [line for line in structure.lines if line.page == 1]
    assert page1 and all(line.removed for line in page1)
    for line in structure.lines:
        if any(h in line.text for h in ("For Public Release", "MMS - FORM 2010", "EV2010R")):
            assert line.removed, line.text
    kept = [line.text for line in structure.lines if not line.removed]
    assert kept[0] == "17. INVESTIGATION FINDINGS:"


def test_district_one_segment_per_field_labelled_number_and_title() -> None:
    structure = _detect(DISTRICT.read_bytes(), "district_report")

    labels = _labels(structure)
    assert labels[:8] == [
        "17 INVESTIGATION FINDINGS",
        "18 LIST THE PROBABLE CAUSE(S) OF ACCIDENT",
        "19 LIST THE CONTRIBUTING CAUSE(S) OF ACCIDENT",
        "20 LIST THE ADDITIONAL INFORMATION",
        "21 PROPERTY DAMAGED",
        "22 RECOMMENDATIONS TO PREVENT RECURRANCE NARRATIVE",
        "23 POSSIBLE OCS VIOLATIONS RELATED TO ACCIDENT",
        "24 SPECIFY VIOLATIONS DIRECTLY OR INDIRECTLY CONTRIBUTING",
    ]
    assert labels[8].startswith("25 ")
    assert all(s.kind == "narrative" for s in structure.segments)
    by_label = {s.label: s for s in structure.segments}
    field20 = _segment_text(structure, by_label["20 LIST THE ADDITIONAL INFORMATION"])
    assert field20 == ["20. LIST THE ADDITIONAL INFORMATION:", "N/A"]
    field24 = _segment_text(structure, by_label["24 SPECIFY VIOLATIONS DIRECTLY OR INDIRECTLY CONTRIBUTING"])
    assert field24 == ["24. SPECIFY VIOLATIONS DIRECTLY OR INDIRECTLY CONTRIBUTING. NARRATIVE:"]


def test_district_text_before_field_17_is_preamble() -> None:
    data = pdfs.lines_pdf(
        [
            ["ACCIDENT INVESTIGATION REPORT", "FIRE", "EXPLOSION"],
            ["For Public Release", "Opening note about the case.", "17. INVESTIGATION FINDINGS:", "Some text."],
        ]
    )

    structure = _detect(data, "district_report")

    assert [(s.label, s.kind) for s in structure.segments] == [
        ("preamble", "preamble"),
        ("17 INVESTIGATION FINDINGS", "narrative"),
    ]
    assert _segment_text(structure, structure.segments[0]) == ["Opening note about the case."]


def test_district_without_fields_is_not_recognized() -> None:
    assert detect_structure(_pages(pdfs.district_without_fields_pdf()), "district_report") is None


def test_district_image_only_page_has_no_lines() -> None:
    structure = _detect(pdfs.district_with_image_page_pdf(), "district_report")

    assert 3 not in {line.page for line in structure.lines}
    assert structure.image_only_pages == frozenset({3})


# -- panel reports ---------------------------------------------------------------------------------------------
def test_panel_contents_and_figure_list_pages_are_removed() -> None:
    structure = _detect(PANEL.read_bytes(), "panel_report")

    for line in structure.lines:
        if line.page in (1, 2):
            assert line.removed, line.text


def test_panel_page_number_lines_are_removed() -> None:
    structure = _detect(PANEL.read_bytes(), "panel_report")

    for page in range(3, 8):
        first = next(line for line in structure.lines if line.page == page)
        assert first.text.isdigit() and first.removed
    assert not any(line.text.isdigit() and not line.removed for line in structure.lines)


def test_panel_segments_from_contents_entries() -> None:
    structure = _detect(PANEL.read_bytes(), "panel_report")

    assert [(s.label, s.kind) for s in structure.segments] == [
        ("acronyms", "acronyms"),
        ("Executive Summary", "narrative"),
        ("Introduction", "narrative"),
        ("Authority", "narrative"),
        ("Background", "narrative"),
    ]
    first, *_ = _segment_text(structure, structure.segments[1])
    assert first.startswith("Executive Summary")


def test_panel_title_page_is_preamble() -> None:
    data = pdfs.lines_pdf(
        [
            ["OCS Report", "Investigation of a Dropped Load"],
            ["i", "Contents", "Executive Summary 1", "Findings 2"],
            ["1", "Executive Summary", "The summary text.", "Findings", "The findings text."],
        ]
    )

    structure = _detect(data, "panel_report")

    assert [(s.label, s.kind) for s in structure.segments] == [
        ("preamble", "preamble"),
        ("Executive Summary", "narrative"),
        ("Findings", "narrative"),
    ]
    assert _segment_text(structure, structure.segments[0]) == ["OCS Report", "Investigation of a Dropped Load"]


def test_panel_without_headings_is_not_recognized() -> None:
    assert detect_structure(_pages(pdfs.panel_without_headings_pdf()), "panel_report") is None


# -- Safety Alerts ---------------------------------------------------------------------------------------------
def test_alert_contact_and_phone_lines_are_removed() -> None:
    structure = _detect(ALERT.read_bytes(), "safety_alert")

    removed = [line.text for line in structure.lines if line.removed]
    assert removed == ["Contact: engagement@bsee.gov", "Phone: (800) 200-4853"]


def test_alert_segments_at_heading_lines_ending_in_colon() -> None:
    structure = _detect(ALERT.read_bytes(), "safety_alert")

    assert [(s.label, s.kind) for s in structure.segments] == [
        ("preamble", "preamble"),
        ("Background", "narrative"),
        ("Incident 1 (Figure 1)", "narrative"),
        ("Incident 2 (Figure 2)", "narrative"),
        ("Incident Findings", "narrative"),
    ]
    assert _segment_text(structure, structure.segments[0]) == [
        "Inspect Batteries and Charging Systems to",
        "Prevent Ruptures",
    ]


def test_alert_without_heading_lines_is_one_alert_segment() -> None:
    structure = _detect(pdfs.notice_alert_pdf(), "safety_alert")

    assert [(s.label, s.kind) for s in structure.segments] == [("alert", "narrative")]
    assert not any(line.removed for line in structure.lines)


@pytest.mark.parametrize("doc_type", ["district_report", "panel_report", "safety_alert"])
def test_segments_are_ordered_and_disjoint(doc_type: str) -> None:
    data = {"district_report": DISTRICT, "panel_report": PANEL, "safety_alert": ALERT}[doc_type].read_bytes()
    structure = _detect(data, doc_type)

    previous = -1
    for segment in structure.segments:
        assert previous < segment.first <= segment.last < len(structure.lines)
        previous = segment.last
