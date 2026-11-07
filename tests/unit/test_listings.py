"""Listing and detail parsers on the recorded BSEE fixtures (AC-001-01)."""

from __future__ import annotations

from offshore_rag.ingestion.listings import (
    parse_district_listing,
    parse_panel_detail,
    parse_panel_listing,
    parse_safety_alert_detail,
    parse_safety_alert_listing,
)
from tests.support.ingest import FIXTURES


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_safety_alert_listing_rows() -> None:
    rows = parse_safety_alert_listing(_html("safety_alerts_listing_page0.html"))
    assert [r.href for r in rows] == [
        "/safety-alerts/mma-safety-alert-526-prevent-battery-ruptures",
        "/improper-use-of-hand-tools-and-unplanned-deviations-from-job-tasks-results-in-injuries",
        "/safety-alerts/control-portable-electronic-device-use-to-prevent-ignition-hazards-offshore",
    ]
    assert rows[0].title == "MMA Safety Alert 526_Prevent Battery Ruptures"


def test_panel_listing_rows() -> None:
    rows = parse_panel_listing(_html("panel_listing_page0.html"))
    assert [r.href for r in rows] == [
        "/panel-investigation/investigation-of-march-25-2022-hydraulic-workover-unit-failure-fatality",
        "/panel-investigation/bsee-panel-investigation-final-report-gc40",
    ]
    assert rows[1].title == "BSEE Panel Investigation Final Report GC40"


def test_details_return_the_pdf_href() -> None:
    assert parse_safety_alert_detail(_html("safety_alert_detail.html")) == (
        "/sites/bsee.gov/files/2026-10/MMA%20Safety%20Alert%20526_Prevent%20Battery%20Ruptures_30OCT26.pdf"
    )
    assert parse_panel_detail(_html("panel_detail.html")) == (
        "/sites/bsee.gov/files/2023-05/bsee-panel-investigation-final-report-gc40_23mar2023.pdf"
    )
    assert parse_panel_detail("<html><body><a href='/x'>no pdf</a></body></html>") is None


def test_district_listing_keeps_links_as_published() -> None:
    hrefs = [r.href for r in parse_district_listing(_html("district_listing.html"))]
    assert len(hrefs) == 4
    assert "sites/bsee.gov/files/cox-hi-472-a-21-oct-2022.pdf" in hrefs  # no leading slash, resolved by the builder
    assert all(h.lower().endswith(".pdf") for h in hrefs)


def test_pages_without_rows_return_empty_lists() -> None:
    assert parse_safety_alert_listing(_html("safety_alerts_listing_empty.html")) == []
    assert parse_panel_listing(_html("panel_listing_empty.html")) == []
    assert parse_district_listing("<html><body><p>nothing</p></body></html>") == []
