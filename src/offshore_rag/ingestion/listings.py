"""Parsers for the BSEE listing and detail pages. They return hrefs exactly as published; callers resolve them."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag


@dataclass(frozen=True)
class ListingLink:
    href: str
    title: str


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _text(node: Tag) -> str:
    return " ".join(node.get_text(" ").split())


def _is_pdf(href: str) -> bool:
    return urlsplit(href.strip()).path.lower().endswith(".pdf")


def _view_rows(html: str, link_cell_class: str, title_cell_class: str) -> list[ListingLink]:
    rows: list[ListingLink] = []
    for tr in _soup(html).select("table tbody tr"):
        link = tr.select_one(f"td.{link_cell_class} a[href]")
        if link is None:
            continue
        title_cell = tr.select_one(f"td.{title_cell_class}")
        title = _text(title_cell) if title_cell is not None else ""
        rows.append(ListingLink(str(link["href"]).strip(), title or _text(link)))
    return rows


def parse_safety_alert_listing(html: str) -> list[ListingLink]:
    """Rows of the Safety Alerts table: the title cell links to the detail page."""
    return _view_rows(html, "views-field-title", "views-field-title")


def parse_panel_listing(html: str) -> list[ListingLink]:
    """Rows of the panel reports table: the document-number cell links to the detail page."""
    return _view_rows(html, "views-field-field-document-number", "views-field-title")


def _first_pdf(html: str) -> str | None:
    soup = _soup(html)
    scopes = soup.select(".field--name-field-document-attachment") or [soup]
    for scope in scopes:
        for a in scope.select("a[href]"):
            href = str(a["href"]).strip()
            if _is_pdf(href):
                return href
    return None


def parse_safety_alert_detail(html: str) -> str | None:
    """The PDF href of a Safety Alert detail page, or None when the page has no PDF attachment."""
    return _first_pdf(html)


def parse_panel_detail(html: str) -> str | None:
    """The PDF href of a panel report detail page, or None when the page has no PDF attachment."""
    return _first_pdf(html)


def parse_district_listing(html: str) -> list[ListingLink]:
    """Every PDF linked from the year tables; the title is the row's cells joined (date, lease, block, type)."""
    rows: list[ListingLink] = []
    for tr in _soup(html).select("table tr"):
        link = next((a for a in tr.select("a[href]") if _is_pdf(str(a["href"]))), None)
        if link is None:
            continue
        rows.append(ListingLink(str(link["href"]).strip(), _text(tr)))
    return rows
