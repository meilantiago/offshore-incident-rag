"""Build the manifest by walking the BSEE listing pages with the polite client."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urljoin

import structlog

from offshore_rag.ingestion.http import PoliteClient
from offshore_rag.ingestion.listings import (
    ListingLink,
    parse_district_listing,
    parse_panel_detail,
    parse_panel_listing,
    parse_safety_alert_detail,
    parse_safety_alert_listing,
)
from offshore_rag.ingestion.manifest import ManifestEntry

log = structlog.get_logger()

SAFETY_ALERTS_PATH = "/guidance-and-regulations/guidance/safety-alerts-program"
PANEL_PATH = "/what-we-do/incident-investigations/panel-investigation-reports"
DISTRICT_PATH = "/what-we-do/incident-investigations/district-investigation-reports"
MAX_PAGES = 500


class ManifestBuildError(Exception):
    """A listing could not be turned into manifest entries (the HTML probably changed)."""


def build_manifest(client: PoliteClient, base_url: str, listings_dir: Path) -> list[ManifestEntry]:
    base = base_url.rstrip("/")
    listings_dir.mkdir(parents=True, exist_ok=True)

    def fetch_html(url: str) -> str:
        if not client.allowed(url):
            raise ManifestBuildError(f"robots.txt disallows {url}")
        content = client.get(url).content
        slug = re.sub(r"[^A-Za-z0-9]+", "_", url.split("://", 1)[-1]).strip("_")[:150]
        (listings_dir / f"{slug}.html").write_bytes(content)
        return content.decode("utf-8", errors="replace")

    entries: dict[str, ManifestEntry] = {}

    def add(entry: ManifestEntry) -> None:
        entries.setdefault(entry.source_url, entry)

    def walk(
        name: str,
        path: str,
        doc_type: str,
        parse_listing: Callable[[str], list[ListingLink]],
        parse_detail: Callable[[str], str | None],
    ) -> None:
        found = 0
        details: dict[str, str] = {}
        for page in range(MAX_PAGES):
            rows = parse_listing(fetch_html(f"{base}{path}?page={page}"))
            if not rows:
                break
            for row in rows:
                detail_url = _resolve(base, row.href)
                if detail_url not in details:
                    href = parse_detail(fetch_html(detail_url))
                    if href is None:
                        raise ManifestBuildError(f"{name}: no PDF link on detail page {detail_url}")
                    details[detail_url] = _resolve(base, href)
                add(ManifestEntry(doc_type, details[detail_url], detail_url, row.title))
                found += 1
        else:
            raise ManifestBuildError(f"{name} listing: more than {MAX_PAGES} pages, giving up")
        if found == 0:
            raise ManifestBuildError(f"{name} listing yielded no entries: the page layout may have changed")
        log.info("listing walked", listing=name, rows=found)

    walk("safety alerts", SAFETY_ALERTS_PATH, "safety_alert", parse_safety_alert_listing, parse_safety_alert_detail)
    walk("panel reports", PANEL_PATH, "panel_report", parse_panel_listing, parse_panel_detail)

    district_url = f"{base}{DISTRICT_PATH}"
    district_rows = parse_district_listing(fetch_html(district_url))
    if not district_rows:
        raise ManifestBuildError("district reports listing yielded no entries: the page layout may have changed")
    for row in district_rows:
        add(ManifestEntry("district_report", _resolve(base, row.href), district_url, row.title))
    log.info("listing walked", listing="district reports", rows=len(district_rows))

    return sorted(entries.values(), key=lambda e: e.source_url)


def _resolve(base: str, href: str) -> str:
    """Links resolve against the site root: BSEE's district links without a leading slash mean root-relative."""
    return urljoin(base + "/", href)
