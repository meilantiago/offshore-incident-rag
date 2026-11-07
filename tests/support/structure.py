"""Helpers for the structure-aware chunking acceptance tests (spec 002).

The expectations here are written by hand from the spec and from the committed fixtures, never derived from the code
under test: which pages and lines of each fixture are *removed content* (spec 002 #Definitions), how a text is cut
into words, and the checks that a chunk set tiles a word stream.

Production modules are imported inside the helpers, so each test fails on its own (ImportError) while the
implementation does not exist yet.
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests.support import pdfs
from tests.support.ingest import FIXTURES, IngestEnv

DISTRICT_PDF = FIXTURES / "district-mp-42-l-2020.pdf"
PANEL_PDF = FIXTURES / "panel-mms-2009-042-trimmed.pdf"
ALERT_PDF = FIXTURES / "safety-alert-526-trimmed.pdf"

FIXED = "fixed_words"
STRUCTURE = "structure_aware"
DOC_TYPES = ("safety_alert", "panel_report", "district_report")
SIZE_CAP = 250
NOT_RECOGNIZED = "structure_not_recognized"

# Repeated Form 2010 page-header lines (spec 002 AC-002-04), as they appear in the district fixture.
DISTRICT_HEADER_RE = re.compile(r"For Public Release|MMS - FORM 2010|EV2010R|PAGE:\s*\d+\s+OF\b")
PAGE_NUMBER_RE = re.compile(r"\d+|[ivxlcdm]+", re.IGNORECASE)
CONTACT_PHONE_RE = re.compile(r"^(Contact|Phone):", re.IGNORECASE)
BREAK_END_RE = re.compile(r"[.:?!][\"')\]]*$")
BULLET_RE = re.compile(r"^([••�\-–]|\d+[.)]|[a-z][.)])$")


# -- text -----------------------------------------------------------------------------------------------------
def words(text: str) -> list[str]:
    return text.split()


def norm(text: str) -> str:
    return " ".join(text.split())


def norm_label(text: str | None) -> str:
    """Case, punctuation and underscores ignored: `Executive Summary __` == `executive summary`."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", (text or "").lower()).split())


def page_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


# -- removed content per document (spec 002 #Definitions) ----------------------------------------------------------
LineRule = Callable[[int, int, int, str], bool]  # (page number, line index, lines on the page, line) -> removed


@dataclass(frozen=True)
class Removal:
    pages: frozenset[int] = frozenset()
    line: LineRule | None = None


def _district_line(page: int, index: int, n: int, line: str) -> bool:
    return bool(DISTRICT_HEADER_RE.search(line))


def _panel_line(page: int, index: int, n: int, line: str) -> bool:
    return index in (0, n - 1) and bool(PAGE_NUMBER_RE.fullmatch(line))


def _alert_line(page: int, index: int, n: int, line: str) -> bool:
    return page == 1 and bool(CONTACT_PHONE_RE.match(line))


NO_REMOVAL = Removal()
DISTRICT_REMOVAL = Removal(frozenset({1}), _district_line)  # page 1 (grid) and the page-header lines
PANEL_REMOVAL = Removal(frozenset({1, 2}), _panel_line)  # Contents, figure list, page-number lines
ALERT_REMOVAL = Removal(frozenset(), _alert_line)  # the Contact and Phone lines


PageRow = tuple[int, str, bool]  # (page number, text, image_only)


def parsed_pages(data: bytes) -> list[PageRow]:
    parse_pdf = importlib.import_module("offshore_rag.ingestion.pdf").parse_pdf
    return [(p.number, p.text, bool(p.image_only)) for p in parse_pdf(data).pages]


def kept_lines(pages: Iterable[PageRow], removal: Removal) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for number, text, image_only in pages:
        if image_only or number in removal.pages:
            continue
        lines = page_lines(text)
        for i, line in enumerate(lines):
            if removal.line is not None and removal.line(number, i, len(lines), line):
                continue
            out.append((number, line))
    return out


def kept_words(pages: Iterable[PageRow], removal: Removal) -> list[tuple[int, str]]:
    return [(n, w) for n, line in kept_lines(pages, removal) for w in words(line)]


# -- chunks ---------------------------------------------------------------------------------------------------
def rows_from_drafts(drafts: Sequence[Any]) -> list[dict[str, Any]]:
    """ChunkDraft objects (plan.md#Chunker interface) as the dicts the database tests use."""
    return [
        {
            "ordinal": d.ordinal,
            "page_start": d.page_start,
            "page_end": d.page_end,
            "text": d.text,
            "section": getattr(d, "section", None),
        }
        for d in drafts
    ]


def structure_aware(size_cap: int | None = None) -> Any:
    module = importlib.import_module("offshore_rag.ingestion.structure_aware")
    cls = module.StructureAwareChunker
    return cls() if size_cap is None else cls(size_cap=size_cap)


def chunk_pdf(data: bytes, doc_type: str, size_cap: int | None = None) -> tuple[list[dict[str, Any]], list[PageRow]]:
    """Chunk a PDF with `structure_aware` (`Chunker.chunk(pages, doc_type)`); returns rows sorted by ordinal."""
    parse_pdf = importlib.import_module("offshore_rag.ingestion.pdf").parse_pdf
    parsed = parse_pdf(data)
    drafts = structure_aware(size_cap).chunk(parsed.pages, doc_type)
    pages = [(p.number, p.text, bool(p.image_only)) for p in parsed.pages]
    return sorted(rows_from_drafts(drafts), key=lambda r: r["ordinal"]), pages


def concat_words(chunks: Iterable[dict[str, Any]]) -> list[str]:
    return [w for c in chunks for w in words(c["text"])]


def with_label(chunks: Iterable[dict[str, Any]], title: str) -> list[dict[str, Any]]:
    return [c for c in chunks if norm_label(c.get("section")) == norm_label(title)]


def assert_tiles(chunks: Sequence[dict[str, Any]], stream: Sequence[tuple[int, str]], label: str) -> None:
    """AC-002-08: in ordinal order, each chunk is the next contiguous run of `stream` (kept words tagged with their
    page): its first word comes from page_start, its last from page_end, nothing skipped, repeated or reordered."""
    ordered = sorted(chunks, key=lambda c: c["ordinal"])
    pos = 0
    for c in ordered:
        ws = words(c["text"])
        assert ws, f"{label}: chunk {c['ordinal']} is empty"
        got = [w for _, w in stream[pos : pos + len(ws)]]
        assert got == ws, (
            f"{label}: chunk {c['ordinal']} (pages {c['page_start']}-{c['page_end']}) is not the next run of kept words"
            f"\n  chunk starts: {' '.join(ws[:12])!r}\n  expected:     {' '.join(w for _, w in stream[pos : pos + 12])!r}"
        )
        first_page, last_page = stream[pos][0], stream[pos + len(ws) - 1][0]
        assert c["page_start"] == first_page, (
            f"{label}: chunk {c['ordinal']} page_start {c['page_start']} != {first_page}"
        )
        assert c["page_end"] == last_page, f"{label}: chunk {c['ordinal']} page_end {c['page_end']} != {last_page}"
        pos += len(ws)
    assert pos == len(stream), f"{label}: {len(stream) - pos} kept words are in no chunk: {stream[pos : pos + 12]}"


def assert_cuts_at_breaks(pieces: Sequence[dict[str, Any]], cap: int, label: str) -> None:
    """Splitting rule (spec 002 #Definitions) for the consecutive pieces of one field or section.

    Every piece has at most `cap` words. A piece that is not the last ends at a paragraph or sentence break (its last
    word ends in `.`, `:`, `?` or `!`, or the next piece starts with a bullet) whenever such a break exists within the
    cap; only when none exists may it be a hard cut, which then is exactly `cap` words.
    """
    for i, piece in enumerate(pieces):
        ws = words(piece["text"])
        assert 0 < len(ws) <= cap, f"{label}: piece {i} has {len(ws)} words (cap {cap})"
        if i == len(pieces) - 1:
            continue
        nxt = words(pieces[i + 1]["text"])
        at_break = bool(BREAK_END_RE.search(ws[-1])) or bool(BULLET_RE.match(nxt[0]))
        if at_break:
            continue
        window = (ws + nxt)[:cap]
        candidates = [j for j, w in enumerate(window[:-1]) if BREAK_END_RE.search(w)]
        assert not candidates and len(ws) == cap, (
            f"{label}: piece {i} ends mid-sentence ({' '.join(ws[-6:])!r} | {' '.join(nxt[:6])!r}) although a break "
            f"exists within the cap after {window[candidates[-1]]!r}"
            if candidates
            else f"{label}: hard cut of {len(ws)} words is not at the cap ({cap})"
        )


def greedy_groups(sizes: Sequence[int], cap: int) -> list[list[int]]:
    """Indexes of consecutive units packed greedily under `cap` (every unit fits): the cut at the last unit
    boundary within the cap, which is the splitting rule when the units are paragraphs."""
    groups: list[list[int]] = [[]]
    total = 0
    for i, size in enumerate(sizes):
        if groups[-1] and total + size > cap:
            groups.append([])
            total = 0
        groups[-1].append(i)
        total += size
    return groups


# -- documents used by the database tests ---------------------------------------------------------------------
@dataclass(frozen=True)
class Doc:
    name: str
    doc_type: str
    data: Callable[[], bytes]
    removal: Removal
    recognized: bool = True
    path: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", f"/sites/bsee.gov/files/spec002/{self.name}.pdf")


DISTRICT = Doc("district-mp-42-l-2020", "district_report", DISTRICT_PDF.read_bytes, DISTRICT_REMOVAL)
PANEL = Doc("panel-mms-2009-042", "panel_report", PANEL_PDF.read_bytes, PANEL_REMOVAL)
ALERT = Doc("safety-alert-526", "safety_alert", ALERT_PDF.read_bytes, ALERT_REMOVAL)
COMMITTED = (DISTRICT, PANEL, ALERT)

IMAGE_PAGE_DISTRICT = Doc("district-image-page", "district_report", pdfs.district_with_image_page_pdf, DISTRICT_REMOVAL)
NOTICE_ALERT = Doc("notice-no-7", "safety_alert", pdfs.notice_alert_pdf, NO_REMOVAL)
UNRECOGNIZED_DISTRICT = Doc(
    "district-without-fields", "district_report", pdfs.district_without_fields_pdf, NO_REMOVAL, recognized=False
)
UNRECOGNIZED_PANEL = Doc(
    "panel-without-headings", "panel_report", pdfs.panel_without_headings_pdf, NO_REMOVAL, recognized=False
)


def serve_docs(env: IngestEnv, docs: Iterable[Doc]) -> dict[str, Doc]:
    """Serve each document on the local server and write the manifest; returns the documents by source URL."""
    by_url: dict[str, Doc] = {}
    entries = []
    for doc in docs:
        url = env.serve_pdf(doc.path, doc.data())
        by_url[url] = doc
        entries.append(env.entry(doc.path, doc.doc_type, title=doc.name))
    env.write_manifest(entries)
    return by_url


def chunk_rows(env: IngestEnv, url: str, chunker: str) -> list[dict[str, Any]]:
    return [c for c in env.chunks(url) if c["chunker"] == chunker]


def set_strategies(env: IngestEnv, chunkers: Sequence[str], by_doc_type: dict[str, list[str]] | None = None) -> None:
    env.setenv("CHUNKERS", ",".join(chunkers))
    if by_doc_type is None:
        env.monkeypatch.delenv("CHUNKERS_BY_DOC_TYPE", raising=False)
    else:
        env.setenv("CHUNKERS_BY_DOC_TYPE", json.dumps(by_doc_type))


def chunk_counts(env: IngestEnv) -> dict[tuple[str, str], int]:
    """Chunk rows per (source URL, strategy)."""
    return {
        (url, chunker): n
        for url, chunker, n in env.db.rows(
            "SELECT d.source_url, c.chunker, count(*) FROM chunks c JOIN documents d ON d.id = c.document_id "
            "GROUP BY 1, 2"
        )
    }


def report_files(reports_dir: Path) -> set[str]:
    return {p.name for p in reports_dir.glob("*")} if reports_dir.exists() else set()
