"""Ingestion report: JSON file and stdout summary (T12)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from offshore_rag.ingestion.report import DocumentOutcome, IngestionReport, format_summary, write_report


def _report() -> IngestionReport:
    docs = [
        DocumentOutcome("http://x/a.pdf", "ingested", pages=3, chunks=4, chunk_words=[250, 250, 100, 40]),
        DocumentOutcome("http://x/scan.pdf", "ingested", pages=2, image_only=True, image_only_pages=2),
        DocumentOutcome("http://x/b.pdf", "replaced", pages=1, chunks=1, chunk_words=[12]),
        DocumentOutcome("http://x/c.pdf", "skipped_unchanged"),
        DocumentOutcome("http://x/gone.pdf", "failed", stage="download", reason="http_404"),
    ]
    return IngestionReport(
        started_at=datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC),
        manifest_entries=5,
        documents=docs,
        durations_ms={"total": 900.0, "download": 300.0, "parse": 200.0, "chunk": 50.0, "store": 100.0},
        bytes_downloaded=12345,
        requests=7,
        retries=1,
    )


def test_report_json_has_counts_failures_and_stats(tmp_path: Path) -> None:
    path = write_report(_report(), tmp_path)
    assert path.parent == tmp_path / "reports" and path.name.startswith("ingest-")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["counts"] == {
        "manifest_entries": 5,
        "ingested": 2,
        "skipped_unchanged": 1,
        "replaced": 1,
        "failed": 1,
        "image_only": 1,
        "pages": 6,
        "chunks": 5,
    }
    assert data["failures"] == [{"source_url": "http://x/gone.pdf", "stage": "download", "reason": "http_404"}]
    assert data["durations_ms"]["total"] == 900.0
    assert set(data["durations_ms"]) == {"total", "download", "parse", "chunk", "store"}
    assert (data["bytes_downloaded"], data["requests"], data["retries"]) == (12345, 7, 1)
    assert data["image_only_documents"] == ["http://x/scan.pdf"]
    assert data["image_only_page_share"] == round(2 / 6, 4)
    assert data["chunk_words"] == {"min": 12, "median": 100, "max": 250}
    assert [d["status"] for d in data["documents"]][-1] == "failed"


def test_two_reports_in_the_same_second_get_distinct_files(tmp_path: Path) -> None:
    a, b = write_report(_report(), tmp_path), write_report(_report(), tmp_path)
    assert a != b and a.exists() and b.exists()


def test_summary_shows_the_same_numbers() -> None:
    text = format_summary(_report())
    for line in (
        "manifest entries: 5",
        "ingested: 2",
        "skipped unchanged: 1",
        "replaced: 1",
        "failed: 1",
        "image-only: 1",
        "pages: 6",
        "chunks: 5",
    ):
        assert f"\n  {line}\n" in f"\n{text}\n"
    for stage in ("download", "parse", "chunk", "store", "total"):
        assert any(line.strip().startswith(f"{stage}: ") for line in text.splitlines())
    assert "12345 bytes" in text and "7 requests" in text and "1 retries" in text
    assert "http://x/gone.pdf" in text and "http_404" in text
    assert "min 12, median 100, max 250" in text


def test_empty_run_has_no_share_and_no_chunk_stats(tmp_path: Path) -> None:
    report = IngestionReport(
        started_at=datetime(2026, 11, 4, tzinfo=UTC),
        manifest_entries=1,
        documents=[DocumentOutcome("http://x/c.pdf", "skipped_unchanged")],
        durations_ms=dict.fromkeys(("total", "download", "parse", "chunk", "store"), 0.0),
        bytes_downloaded=0,
        requests=1,
        retries=0,
    )
    data = json.loads(write_report(report, tmp_path).read_text(encoding="utf-8"))
    assert data["image_only_page_share"] is None
    assert data["chunk_words"] == {"min": None, "median": None, "max": None}
    assert not report.has_failures
    assert "n/a" in format_summary(report)
