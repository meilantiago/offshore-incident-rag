"""Outcome of an `ingest` run: per-document outcomes, the JSON report and the stdout summary (AC-001-11)."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Status = Literal["ingested", "replaced", "skipped_unchanged", "failed"]
Stage = Literal["download", "parse", "chunk", "store"]
STAGES: tuple[Stage, ...] = ("download", "parse", "chunk", "store")


@dataclass
class DocumentOutcome:
    source_url: str
    status: Status
    stage: Stage | None = None  # failures only
    reason: str | None = None  # failures only
    pages: int = 0  # pages stored by this run
    chunks: int = 0  # chunks stored by this run (all chunkers)
    image_only: bool = False
    image_only_pages: int = 0
    durations_ms: dict[str, float] = field(default_factory=dict)
    chunk_words: list[int] = field(default_factory=list)  # word count of every chunk stored by this run
    doc_type: str = ""
    chunks_by_strategy: dict[str, int] = field(default_factory=dict)
    chunk_ms_by_strategy: dict[str, float] = field(default_factory=dict)
    structure_not_recognized: bool = False  # a chunk is labelled `structure_not_recognized` (AC-002-07)

    def to_json(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "status": self.status,
            "stage": self.stage,
            "reason": self.reason,
            "pages": self.pages,
            "chunks": self.chunks,
            "chunks_by_strategy": self.chunks_by_strategy,
            "structure_not_recognized": self.structure_not_recognized,
            "image_only": self.image_only,
            "durations_ms": {k: round(v, 1) for k, v in self.durations_ms.items()},
        }


@dataclass
class IngestionReport:
    started_at: datetime
    manifest_entries: int
    documents: list[DocumentOutcome]
    durations_ms: dict[str, float]  # total (wall clock of the run) and one per stage, summed over documents
    bytes_downloaded: int
    requests: int
    retries: int

    def _count(self, status: Status) -> int:
        return sum(1 for d in self.documents if d.status == status)

    @property
    def has_failures(self) -> bool:
        return any(d.status == "failed" for d in self.documents)

    @property
    def stored(self) -> list[DocumentOutcome]:
        return [d for d in self.documents if d.status in ("ingested", "replaced")]

    def counts(self) -> dict[str, int]:
        stored = self.stored
        return {
            "manifest_entries": self.manifest_entries,
            "ingested": self._count("ingested"),
            "skipped_unchanged": self._count("skipped_unchanged"),
            "replaced": self._count("replaced"),
            "failed": self._count("failed"),
            "image_only": sum(1 for d in stored if d.image_only),
            "pages": sum(d.pages for d in stored),
            "chunks": sum(d.chunks for d in stored),
        }

    def not_recognized(self) -> list[DocumentOutcome]:
        return [d for d in self.stored if d.structure_not_recognized]

    def chunks_by_strategy(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for d in self.stored:
            for name, n in d.chunks_by_strategy.items():
                totals[name] = totals.get(name, 0) + n
        return totals

    def chunk_ms_by_strategy(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for d in self.stored:
            for name, ms in d.chunk_ms_by_strategy.items():
                totals[name] = totals.get(name, 0.0) + ms
        return totals

    def image_only_page_share(self) -> float | None:
        pages = sum(d.pages for d in self.stored)
        if pages == 0:
            return None
        return round(sum(d.image_only_pages for d in self.stored) / pages, 4)

    def chunk_words(self) -> dict[str, float | None]:
        words = [w for d in self.stored for w in d.chunk_words]
        if not words:
            return {"min": None, "median": None, "max": None}
        return {"min": min(words), "median": statistics.median(words), "max": max(words)}

    def to_json(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.astimezone(UTC).isoformat(),
            "counts": self.counts(),
            "durations_ms": {k: round(v, 1) for k, v in self.durations_ms.items()},
            "bytes_downloaded": self.bytes_downloaded,
            "requests": self.requests,
            "retries": self.retries,
            "image_only_page_share": self.image_only_page_share(),
            "chunk_words": self.chunk_words(),
            "chunks_by_strategy": self.chunks_by_strategy(),
            "chunk_durations_ms_by_strategy": {k: round(v, 1) for k, v in self.chunk_ms_by_strategy().items()},
            "structure_not_recognized": [
                {"source_url": d.source_url, "doc_type": d.doc_type} for d in self.not_recognized()
            ],
            "image_only_documents": [d.source_url for d in self.stored if d.image_only],
            "failures": [
                {"source_url": d.source_url, "stage": d.stage, "reason": d.reason}
                for d in self.documents
                if d.status == "failed"
            ],
            "documents": [d.to_json() for d in self.documents],
        }


def write_report(report: IngestionReport, data_dir: Path) -> Path:
    """Write `DATA_DIR/reports/ingest-<UTC timestamp>.json`; a new file per run, never overwriting one."""
    return write_json_report(report.to_json(), data_dir, "ingest", report.started_at)


def write_json_report(data: dict[str, Any], data_dir: Path, prefix: str, at: datetime) -> Path:
    """Write `DATA_DIR/reports/<prefix>-<UTC timestamp>.json`, never overwriting an existing file."""
    reports = data_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    stamp = at.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    suffix = 1
    while True:
        path = reports / (f"{prefix}-{stamp}.json" if suffix == 1 else f"{prefix}-{stamp}-{suffix}.json")
        try:
            with path.open("x", encoding="utf-8", newline="\n") as f:
                f.write(text)
        except FileExistsError:
            suffix += 1
            continue
        return path


def format_summary(report: IngestionReport) -> str:
    """Human summary for stdout: one `<label>: <n>` line per count and per stage duration."""
    counts = report.counts()
    lines = ["Ingestion summary"]
    lines += [f"  {key.replace('_', ' ').replace('image only', 'image-only')}: {n}" for key, n in counts.items()]
    lines.append("Durations")
    for key in (*STAGES, "total"):
        lines.append(f"  {key}: {report.durations_ms.get(key, 0.0):.0f} ms")
    lines.append(f"Network: {report.bytes_downloaded} bytes in {report.requests} requests ({report.retries} retries)")
    share = report.image_only_page_share()
    lines.append(f"Share of image-only pages: {'n/a' if share is None else f'{share:.1%}'}")
    words = report.chunk_words()
    if words["min"] is None:
        lines.append("Chunk size (words): n/a")
    else:
        lines.append(f"Chunk size (words): min {words['min']}, median {words['median']:g}, max {words['max']}")
    for name, n in report.chunks_by_strategy().items():
        ms = report.chunk_ms_by_strategy().get(name, 0.0)
        lines.append(f"Chunks {name}: {n} ({ms:.0f} ms)")
    unrecognized = report.not_recognized()
    if unrecognized:
        lines.append("Structure not recognized")
        lines += [f"  [{d.doc_type}] {d.source_url}" for d in unrecognized]
    failed = [d for d in report.documents if d.status == "failed"]
    if failed:
        lines.append("Failures")
        lines += [f"  [{d.stage}] {d.reason}: {d.source_url}" for d in failed]
    return "\n".join(lines)
