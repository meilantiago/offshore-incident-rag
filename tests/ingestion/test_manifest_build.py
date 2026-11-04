"""AC-001-01: building the manifest from recorded BSEE listing and detail pages served locally."""

from __future__ import annotations

import json

from tests.support.http_server import FixtureServer
from tests.support.ingest import EXIT_OK, FIXTURES, IngestEnv, assert_exit, run_cli

# Listing paths as published in spec.md "Data and provenance". Panel and district answer 301 on bsee.gov to the
# `offshore-incident-investigations/` paths; the local server reproduces that redirect.
SA_LISTING = "/guidance-and-regulations/guidance/safety-alerts-program"
PANEL_LISTING = "/what-we-do/incident-investigations/panel-investigation-reports"
PANEL_LISTING_CANONICAL = (
    "/what-we-do/incident-investigations/offshore-incident-investigations/panel-investigation-reports"
)
DISTRICT_LISTING = "/what-we-do/incident-investigations/district-investigation-reports"
DISTRICT_LISTING_CANONICAL = (
    "/what-we-do/incident-investigations/offshore-incident-investigations/district-investigation-reports"
)

SA_TEMPLATE_PDF = "/sites/bsee.gov/files/2026-10/MMA%20Safety%20Alert%20526_Prevent%20Battery%20Ruptures_30OCT26.pdf"
PANEL_TEMPLATE_PDF = "/sites/bsee.gov/files/2023-05/bsee-panel-investigation-final-report-gc40_23mar2023.pdf"

# detail page path -> PDF href on that page
SA_DETAILS = {
    "/safety-alerts/mma-safety-alert-526-prevent-battery-ruptures": SA_TEMPLATE_PDF,
    "/improper-use-of-hand-tools-and-unplanned-deviations-from-job-tasks-results-in-injuries": (
        "/sites/bsee.gov/files/2026-08/Safety%20Alert%20523%20Hand%20Tools.pdf"
    ),
    "/safety-alerts/control-portable-electronic-device-use-to-prevent-ignition-hazards-offshore": (
        "/sites/bsee.gov/files/2026-08/Safety%20Alert%20521%20Portable%20Electronic%20Devices.pdf"
    ),
    "/safety-alerts/bsee-safety-alert-469-bsee-identifies-medical-evacuation-and-emergency-hazards-during": (
        "/sites/bsee.gov/files/2023-10/BSEE%20Safety%20Alert%20469%20-%20BSEE%20Identifies%20Medical%20Evacuation"
        "%20and%20Emergency%20Hazards%20During%20Risk-Based%20Inspections.pdf"
    ),
}
PANEL_DETAILS = {
    "/panel-investigation/bsee-panel-investigation-final-report-gc40": PANEL_TEMPLATE_PDF,
    "/panel-investigation/investigation-of-march-25-2022-hydraulic-workover-unit-failure-fatality": (
        "/sites/bsee.gov/files/2024-08/MP%2064%20No-19%20Report%2030May24.pdf"
    ),
}
# District rows link straight to the PDF. One link has no leading slash on the live page: it must resolve against
# the site root (resolved against the page path it is a 404 on bsee.gov, see tests/fixtures/bsee/SOURCES.md).
DISTRICT_PDFS = [
    "/sites/bsee.gov/files/2026-10/SM%2058%20Byron%20Energy%207-30-2026%20-%20For%20Public%20Release%20%281%29.pdf",
    "/sites/bsee.gov/files/2026-10/MC%20724%20Hess%20Corporation%2030-Jul-2026.pdf",
    "/sites/bsee.gov/files/cox-hi-472-a-21-oct-2022.pdf",
    "/sites/bsee.gov/files/2023-06/GC%20205_Chevron_13-SEP-2022.pdf",
]


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def serve_bsee(server: FixtureServer, *, empty_safety_alerts: bool = False) -> None:
    """Publish the recorded BSEE pages on the local server, with paths as on bsee.gov."""
    empty_sa = _fixture("safety_alerts_listing_empty.html")
    if empty_safety_alerts:
        server.add_html(SA_LISTING, empty_sa, any_query=True)
    else:
        page0 = _fixture("safety_alerts_listing_page0.html")
        server.add_html(SA_LISTING, empty_sa, any_query=True)  # any page past the end
        server.add_html(SA_LISTING, page0)
        server.add_html(SA_LISTING + "?page=0", page0)
        server.add_html(SA_LISTING + "?page=1", _fixture("safety_alerts_listing_page1.html"))
    sa_detail = _fixture("safety_alert_detail.html")
    for path, pdf in SA_DETAILS.items():
        server.add_html(path, sa_detail.replace(SA_TEMPLATE_PDF, pdf))

    panel0 = _fixture("panel_listing_page0.html")
    for listing in (PANEL_LISTING, PANEL_LISTING_CANONICAL):
        server.add_html(listing, _fixture("panel_listing_empty.html"), any_query=True)
        server.add_html(listing, panel0)
        server.add_html(listing + "?page=0", panel0)
    panel_detail = _fixture("panel_detail.html")
    for path, pdf in PANEL_DETAILS.items():
        server.add_html(path, panel_detail.replace(PANEL_TEMPLATE_PDF, pdf))

    server.add_html(DISTRICT_LISTING_CANONICAL, _fixture("district_listing.html"))
    server.redirect(DISTRICT_LISTING, DISTRICT_LISTING_CANONICAL)


def _read_manifest(env: IngestEnv) -> list[dict[str, object]]:
    lines = env.manifest_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_ac_001_01_manifest_lists_every_pdf_with_type_and_provenance(http_env: IngestEnv) -> None:
    """AC-001-01: one entry per PDF with document type, absolute source URL and the page it was found on."""
    serve_bsee(http_env.server)
    base = http_env.server.base_url

    run = run_cli("build-manifest")

    assert_exit(run, EXIT_OK)
    entries = _read_manifest(http_env)
    by_url = {str(e["source_url"]): e for e in entries}

    expected: dict[str, tuple[str, set[str]]] = {}
    for detail, pdf in SA_DETAILS.items():
        expected[base + pdf] = ("safety_alert", {base + detail})
    for detail, pdf in PANEL_DETAILS.items():
        expected[base + pdf] = ("panel_report", {base + detail})
    district_pages = {base + DISTRICT_LISTING, base + DISTRICT_LISTING_CANONICAL}
    for pdf in DISTRICT_PDFS:
        expected[base + pdf] = ("district_report", district_pages)

    assert sorted(by_url) == sorted(expected), "manifest must hold exactly the PDFs linked from the listings"
    for url, (doc_type, listing_urls) in expected.items():
        entry = by_url[url]
        assert entry["doc_type"] == doc_type, url
        assert entry["listing_url"] in listing_urls, f"{url}: listing_url {entry['listing_url']!r}"
        assert url.startswith("http://") or url.startswith("https://")


def test_ac_001_01_manifest_has_no_duplicate_source_url(http_env: IngestEnv) -> None:
    """AC-001-01: a row repeated across listing pages still yields one manifest entry."""
    serve_bsee(http_env.server)

    assert_exit(run_cli("build-manifest"), EXIT_OK)

    urls = [e["source_url"] for e in _read_manifest(http_env)]
    assert len(urls) == len(set(urls))
    repeated = http_env.server.url(SA_DETAILS[next(k for k in SA_DETAILS if "portable-electronic" in k)])
    assert urls.count(repeated) == 1


def test_ac_001_01_two_builds_are_byte_identical(http_env: IngestEnv) -> None:
    """AC-001-01: building twice from the same input produces byte-identical files (sorted, keys sorted)."""
    serve_bsee(http_env.server)

    assert_exit(run_cli("build-manifest"), EXIT_OK)
    first = http_env.manifest_path.read_bytes()
    http_env.manifest_path.unlink()
    assert_exit(run_cli("build-manifest"), EXIT_OK)
    second = http_env.manifest_path.read_bytes()

    assert first == second
    assert b"\r\n" not in first
    lines = first.decode("utf-8").splitlines()
    urls = [json.loads(line)["source_url"] for line in lines]
    assert urls == sorted(urls)
    for line in lines:
        assert list(json.loads(line)) == sorted(json.loads(line))


def test_ac_001_01_listing_with_zero_rows_fails(http_env: IngestEnv) -> None:
    """AC-001-01: a listing that yields no entries means the parser is out of date: the build fails."""
    serve_bsee(http_env.server, empty_safety_alerts=True)

    run = run_cli("build-manifest")

    assert run.exception is None or isinstance(run.exception, SystemExit), run.describe()
    assert run.exit_code != EXIT_OK, run.describe()
    assert "safety" in run.output.lower(), "the error should say which listing came back empty"
