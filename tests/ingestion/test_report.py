"""AC-001-11: every ingest run past validation writes a machine-readable report and prints a summary."""

from __future__ import annotations

import re

import pytest

from tests.conftest import migrate_schema
from tests.support import pdfs
from tests.support.ingest import (
    COUNT_KEYS,
    DURATION_KEYS,
    EXIT_OK,
    EXIT_PARTIAL,
    IngestEnv,
    assert_exit,
)

pytestmark = pytest.mark.integration

# Labels of the stdout summary: one line per count, "<label>: <number>" (case-insensitive, `_`, `-` or space).
SUMMARY_LABELS = {key: key.replace("_", "[ _-]") for key in COUNT_KEYS}


def _summary_number(stdout: str, label_re: str) -> int:
    m = re.search(rf"(?im)^[\s*\-•|]*{label_re}\b[^\d\n]*(\d+)", stdout)
    assert m, f"summary line for {label_re!r} not found in stdout:\n{stdout}"
    return int(m.group(1))


def _assert_report_shape(report: dict[str, object]) -> None:
    counts = report["counts"]
    durations = report["durations_ms"]
    assert isinstance(counts, dict) and isinstance(durations, dict)
    for key in COUNT_KEYS:
        assert isinstance(counts.get(key), int), f"counts.{key} missing"
    for key in DURATION_KEYS:
        value = durations.get(key)
        assert isinstance(value, int | float) and value >= 0, f"durations_ms.{key} missing"
    assert durations["total"] >= max(durations[k] for k in ("download", "parse", "chunk", "store"))


def test_ac_001_11_report_file_and_stdout_summary(db_env: IngestEnv) -> None:
    """AC-001-11: JSON report under data/ and stdout summary with the same counts and per-stage durations."""
    migrate_schema(db_env.db)
    db_env.serve_pdf("/sites/bsee.gov/files/a.pdf", pdfs.text_pdf(3))
    db_env.serve_pdf("/sites/bsee.gov/files/b.pdf", pdfs.text_pdf(4, tag="B"))
    db_env.serve_pdf("/sites/bsee.gov/files/scan.pdf", pdfs.image_only_pdf(2))
    paths = ["/sites/bsee.gov/files/a.pdf", "/sites/bsee.gov/files/b.pdf", "/sites/bsee.gov/files/scan.pdf"]
    db_env.write_manifest([db_env.entry(p) for p in [*paths, "/sites/bsee.gov/files/gone.pdf"]])

    run = db_env.ingest()

    assert_exit(run, EXIT_PARTIAL)
    reports = db_env.reports()
    assert len(reports) == 1, f"one report per run under {db_env.reports_dir}"
    assert reports[0].resolve().is_relative_to(db_env.data_dir.resolve())
    report = db_env.latest_report()
    _assert_report_shape(report)
    counts = report["counts"]
    docs, pages, chunks = db_env.counts()
    assert counts == {
        "manifest_entries": 4,
        "ingested": 3,
        "skipped_unchanged": 0,
        "replaced": 0,
        "failed": 1,
        "image_only": 1,
        "pages": pages,
        "chunks": chunks,
    } | {k: v for k, v in counts.items() if k not in COUNT_KEYS}
    assert (docs, pages) == (3, 9)
    assert chunks > 0

    for key, label in SUMMARY_LABELS.items():
        assert _summary_number(run.stdout, label) == counts[key], f"stdout {key} differs from the report"
    for stage in DURATION_KEYS:
        _summary_number(run.stdout, stage)  # a duration line per stage and for the whole run


def test_ac_001_11_report_written_for_unchanged_rerun(db_env: IngestEnv) -> None:
    """AC-001-11: a second run (nothing to do) still writes its own report with skipped counts."""
    migrate_schema(db_env.db)
    db_env.serve_pdf("/sites/bsee.gov/files/a.pdf", pdfs.text_pdf(2))
    db_env.write_manifest([db_env.entry("/sites/bsee.gov/files/a.pdf")])
    assert_exit(db_env.ingest(), EXIT_OK)
    first_reports = set(db_env.reports())

    run = db_env.ingest()

    assert_exit(run, EXIT_OK)
    new = set(db_env.reports()) - first_reports
    assert len(new) == 1, "each run writes its own report"
    report = db_env.latest_report()
    _assert_report_shape(report)
    assert report["counts"]["manifest_entries"] == 1
    assert report["counts"]["skipped_unchanged"] == 1
    assert report["counts"]["ingested"] == 0
    assert _summary_number(run.stdout, SUMMARY_LABELS["skipped_unchanged"]) == 1
