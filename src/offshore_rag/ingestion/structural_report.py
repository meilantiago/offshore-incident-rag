"""The structural report of stored chunk sets (spec 002 AC-002-10..12, plan.md#Structural report).

For each stored document, structure detection is re-run on its stored pages and two word streams are built: the full
one (every word of every text page) and the kept one (removed content left out), each word tagged with its line.
Each chunk is located by searching its words from the first word of its `page_start` in the stream it was cut from
(full for `fixed_words`, kept for `structure_aware`); a chunk that cannot be located raises `ChunkLocationError`.

Per (strategy, document type) the report holds: documents, chunks and structure-not-recognized documents; chunk size
in words (min, p10, median, p90, max); the shares of chunks spanning more than one page, holding a district page-header
line, holding the whole district checkbox grid (FIRE, EXPLOSION, FATALITY, COLLISION) and crossing a field or section
boundary (a segment starts strictly inside the chunk's span); and the documents whose `narrative` or `acronyms`
segments have no word in any chunk. Documents with no detected structure count in the totals but not in the crossing
and missing metrics. Shares are fractions in [0, 1].
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from offshore_rag.ingestion.chunking import DocType
from offshore_rag.ingestion.manifest import DOC_TYPES
from offshore_rag.ingestion.pdf import PageText
from offshore_rag.ingestion.report import write_json_report
from offshore_rag.ingestion.store import ReportChunk
from offshore_rag.ingestion.structure import DISTRICT_HEADER, DocumentStructure, Segment, detect_structure
from offshore_rag.ingestion.structure_aware import whole_alert_if_it_fits

STRUCTURE_AWARE = "structure_aware"
GRID_LABELS = ("FIRE", "EXPLOSION", "FATALITY", "COLLISION")
_GRID = [re.compile(rf"\b{label}\b") for label in GRID_LABELS]
_MEASURED_KINDS = ("narrative", "acronyms")


class ReportSource(Protocol):
    def chunks_for_report(self, strategies: Sequence[str] | None) -> list[ReportChunk]: ...

    def load_pages(self, document_id: int) -> list[PageText]: ...


class NoChunksError(ValueError):
    """A requested strategy has no stored chunk (AC-002-12)."""

    def __init__(self, strategies: Sequence[str]) -> None:
        self.strategies = list(strategies)
        if strategies:
            names = ", ".join(strategies)
            super().__init__(f"no chunks stored for strategy {names}; run `offshore-rag rechunk` with it first")
        else:
            super().__init__("no chunks stored in the database; run `offshore-rag ingest` first")


class ChunkLocationError(ValueError):
    """A stored chunk whose words are not found in its document's stored pages."""


@dataclass
class StrategyMetrics:
    strategy: str
    doc_type: str
    documents: int
    chunks: int
    structure_not_recognized: int
    size_words: dict[str, float]
    multi_page_share: float
    page_header_share: float
    checkbox_grid_share: float | None  # district reports only
    boundary_crossing_share: float | None  # None when no chunk belongs to a recognized document
    missing_sections: list[dict[str, Any]]  # [{"source_url": ..., "sections": [...]}]

    def to_json(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "doc_type": self.doc_type,
            "documents": self.documents,
            "chunks": self.chunks,
            "structure_not_recognized": self.structure_not_recognized,
            "size_words": self.size_words,
            "multi_page_share": self.multi_page_share,
            "page_header_share": self.page_header_share,
            "checkbox_grid_share": self.checkbox_grid_share,
            "boundary_crossing_share": self.boundary_crossing_share,
            "missing_sections": self.missing_sections,
        }


@dataclass
class StructuralReport:
    generated_at: datetime
    strategies: list[str]
    entries: list[StrategyMetrics]

    def to_json(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.astimezone(UTC).isoformat(),
            "strategies": self.strategies,
            "entries": [e.to_json() for e in self.entries],
        }


def size_distribution(sizes: Sequence[int]) -> dict[str, float]:
    """min, p10, median, p90 and max of `sizes` (percentiles by linear interpolation between closest ranks)."""
    ordered = sorted(sizes)
    if not ordered:
        raise ValueError("no sizes")

    def percentile(q: float) -> float:
        pos = q * (len(ordered) - 1)
        low, high = math.floor(pos), math.ceil(pos)
        return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)

    return {
        "min": ordered[0],
        "p10": percentile(0.1),
        "median": statistics.median(ordered),
        "p90": percentile(0.9),
        "max": ordered[-1],
    }


@dataclass
class _Acc:
    documents: set[int] = field(default_factory=set)
    not_recognized: set[int] = field(default_factory=set)
    sizes: list[int] = field(default_factory=list)
    multi_page: int = 0
    header: int = 0
    grid: int = 0
    measured: int = 0
    crossing: int = 0
    missing: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class _Stream:
    words: list[str]
    lines: list[int]  # line index of each word
    pages: list[int]  # page of each word
    first_by_page: dict[int, int]  # position of the first word of each page


def _stream(structure: DocumentStructure, kept_only: bool) -> _Stream:
    words: list[str] = []
    lines: list[int] = []
    pages: list[int] = []
    first_by_page: dict[int, int] = {}
    for i, line in enumerate(structure.lines):
        if kept_only and line.removed:
            continue
        first_by_page.setdefault(line.page, len(words))
        for word in line.text.split():
            words.append(word)
            lines.append(i)
            pages.append(line.page)
    return _Stream(words, lines, pages, first_by_page)


def _locate(stream: _Stream, chunk: ReportChunk) -> tuple[int, int]:
    """Positions (first, last) of the chunk's words in the stream, searched from the first word of `page_start`."""
    target = chunk.text.split()
    start = stream.first_by_page.get(chunk.page_start)
    if target and start is not None:
        n = len(target)
        for pos in range(start, len(stream.words) - n + 1):
            if stream.pages[pos] != chunk.page_start:
                break  # the first word of a chunk is on its page_start
            if stream.words[pos] == target[0] and stream.words[pos : pos + n] == target:
                return pos, pos + n - 1
    raise ChunkLocationError(
        f"chunk {chunk.ordinal} of {chunk.chunker} in {chunk.source_url} (pages {chunk.page_start}-{chunk.page_end}) "
        "cannot be located in the stored pages"
    )


def _segments(structure: DocumentStructure, strategy: str, chunks: Sequence[ReportChunk]) -> list[Segment]:
    if strategy == STRUCTURE_AWARE and chunks[0].doc_type == "safety_alert":
        cap = chunks[0].chunker_params.get("size_cap")
        if isinstance(cap, int):
            return whole_alert_if_it_fits(structure, cap).segments
    return structure.segments


def _measure_document(acc: _Acc, structure: DocumentStructure, strategy: str, chunks: Sequence[ReportChunk]) -> None:
    stream = _stream(structure, kept_only=strategy == STRUCTURE_AWARE)
    segments = _segments(structure, strategy, chunks)
    covered: set[int] = set()
    for chunk in chunks:
        first, last = _locate(stream, chunk)
        first_line, last_line = stream.lines[first], stream.lines[last]
        covered.update(stream.lines[first : last + 1])
        acc.measured += 1
        if any(first_line < s.first <= last_line for s in segments):
            acc.crossing += 1
    missing = [
        s.label
        for s in segments
        if s.kind in _MEASURED_KINDS
        and not any(i in covered for i in range(s.first, s.last + 1) if not structure.lines[i].removed)
    ]
    if missing:
        acc.missing.append({"source_url": chunks[0].source_url, "sections": missing})


def _share(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


def build_structural_report(
    source: ReportSource,
    strategies: Sequence[str] | None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> StructuralReport:
    """The report of the given strategies (every stored strategy when `None`); `NoChunksError` if one has none."""
    generated_at = now()
    chunks = source.chunks_for_report(strategies)
    found = sorted({c.chunker for c in chunks})
    requested = list(dict.fromkeys(strategies)) if strategies is not None else found
    absent = [s for s in requested if s not in found]
    if absent or not requested:
        raise NoChunksError(absent)

    by_doc: dict[int, dict[str, list[ReportChunk]]] = {}
    for c in chunks:
        by_doc.setdefault(c.document_id, {}).setdefault(c.chunker, []).append(c)

    accs: dict[tuple[str, str], _Acc] = {}
    for document_id, sets in by_doc.items():
        doc_type = next(iter(sets.values()))[0].doc_type
        structure = detect_structure(source.load_pages(document_id), cast(DocType, doc_type))
        for strategy, doc_chunks in sets.items():
            doc_chunks.sort(key=lambda c: c.ordinal)
            acc = accs.setdefault((strategy, doc_type), _Acc())
            acc.documents.add(document_id)
            for c in doc_chunks:
                acc.sizes.append(len(c.text.split()))
                acc.multi_page += c.page_end > c.page_start
                acc.header += bool(DISTRICT_HEADER.search(c.text))
                acc.grid += all(g.search(c.text) for g in _GRID)
            if structure is None:
                acc.not_recognized.add(document_id)
            else:
                _measure_document(acc, structure, strategy, doc_chunks)

    entries = [
        _metrics(strategy, doc_type, accs[(strategy, doc_type)])
        for strategy in requested
        for doc_type in (*DOC_TYPES, *sorted({d for _, d in accs} - set(DOC_TYPES)))
        if (strategy, doc_type) in accs
    ]
    return StructuralReport(generated_at, requested, entries)


def _metrics(strategy: str, doc_type: str, acc: _Acc) -> StrategyMetrics:
    n = len(acc.sizes)
    return StrategyMetrics(
        strategy=strategy,
        doc_type=doc_type,
        documents=len(acc.documents),
        chunks=n,
        structure_not_recognized=len(acc.not_recognized),
        size_words=size_distribution(acc.sizes),
        multi_page_share=_share(acc.multi_page, n),
        page_header_share=_share(acc.header, n),
        checkbox_grid_share=_share(acc.grid, n) if doc_type == "district_report" else None,
        boundary_crossing_share=_share(acc.crossing, acc.measured) if acc.measured else None,
        missing_sections=acc.missing,
    )


def write_structural_report(report: StructuralReport, data_dir: Path) -> Path:
    """Write `DATA_DIR/reports/chunks-<UTC timestamp>.json`; a new file per run, never overwriting one."""
    return write_json_report(report.to_json(), data_dir, "chunks", report.generated_at)


_COLUMNS = (
    ("strategy", 16),
    ("doc_type", 16),
    ("docs", 5),
    ("chunks", 6),
    ("not recognized", 14),
    ("min", 5),
    ("p10", 6),
    ("median", 6),
    ("p90", 6),
    ("max", 5),
    ("multi-page", 10),
    ("page header", 11),
    ("checkbox grid", 13),
    ("boundary crossing", 17),
)


def _pct(share: float | None) -> str:
    return "n/a" if share is None else f"{share:.1%}"


def format_structural_summary(report: StructuralReport) -> str:
    """Human summary for stdout: one row per (strategy, document type), then the missing fields or sections."""
    lines = ["Structural report (chunk size in words, shares of chunks)"]
    lines.append("  ".join(name.ljust(width) for name, width in _COLUMNS).rstrip())
    for e in report.entries:
        size = e.size_words
        cells = (
            e.strategy,
            e.doc_type,
            str(e.documents),
            str(e.chunks),
            str(e.structure_not_recognized),
            *(f"{size[k]:g}" for k in ("min", "p10", "median", "p90", "max")),
            _pct(e.multi_page_share),
            _pct(e.page_header_share),
            _pct(e.checkbox_grid_share),
            _pct(e.boundary_crossing_share),
        )
        lines.append("  ".join(c.ljust(w) for c, (_, w) in zip(cells, _COLUMNS, strict=True)).rstrip())
    missing = [(e, m) for e in report.entries for m in e.missing_sections]
    lines.append(f"Missing fields or sections: {len(missing) or 'none'}")
    for e, m in missing:
        lines.append(f"  [{e.strategy}, {e.doc_type}] {m['source_url']}: {'; '.join(m['sections'])}")
    return "\n".join(lines)
