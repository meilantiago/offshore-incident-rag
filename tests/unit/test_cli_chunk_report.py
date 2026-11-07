"""`offshore-rag chunk-report`: JSON file, stdout table and exit codes (spec 002 T11, T92)."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from offshore_rag.cli import app
from offshore_rag.db.migrate import migrate
from offshore_rag.ingestion.structural_report import (
    StaleChunkSet,
    StrategyMetrics,
    StructuralReport,
    format_structural_summary,
    write_structural_report,
)
from tests.conftest import PgSchema
from tests.support import pdfs
from tests.support.http_server import FixtureServer

runner = CliRunner()


@pytest.fixture
def server() -> Iterator[FixtureServer]:
    with FixtureServer() as s:
        yield s


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MANIFEST_PATH", str(tmp_path / "manifest.jsonl"))
    monkeypatch.setenv("HTTP_RATE_PER_SECOND", "100")
    monkeypatch.setenv("HTTP_MAX_RETRIES", "0")
    monkeypatch.setenv("CHUNKERS", "fixed_words")
    return tmp_path


def _reports(env: Path) -> list[str]:
    reports = env / "data" / "reports"
    return sorted(p.name for p in reports.glob("chunks-*.json")) if reports.exists() else []


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _ingest(env: Path, monkeypatch: pytest.MonkeyPatch, postgres: PgSchema, server: FixtureServer) -> None:
    migrate(postgres.conn)
    monkeypatch.setenv("DATABASE_URL", postgres.url)
    server.add("/a.pdf", pdfs.text_pdf(2))
    (env / "manifest.jsonl").write_text(
        json.dumps({"doc_type": "safety_alert", "listing_url": server.url("/l"), "source_url": server.url("/a.pdf")})
        + "\n",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["ingest"]).exit_code == 0


def _metrics(strategy: str, doc_type: str) -> StrategyMetrics:
    return StrategyMetrics(
        strategy=strategy,
        doc_type=doc_type,
        documents=1,
        chunks=2,
        structure_not_recognized=0,
        size_words={"min": 10, "p10": 11, "median": 15, "p90": 19, "max": 20},
        multi_page_share=0.5,
        page_header_share=0.0,
        checkbox_grid_share=None,
        boundary_crossing_share=0.0,
        missing_sections=[{"source_url": "https://example.test/a.pdf", "sections": ["Background"]}],
    )


def test_write_structural_report_never_overwrites(tmp_path: Path) -> None:
    report = StructuralReport(
        datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), ["fixed_words"], [_metrics("fixed_words", "x")]
    )

    first = write_structural_report(report, tmp_path)
    second = write_structural_report(report, tmp_path)

    assert first.parent == tmp_path / "reports" and first.name.startswith("chunks-") and first.suffix == ".json"
    assert first != second
    assert json.loads(first.read_text(encoding="utf-8"))["entries"][0]["chunks"] == 2


def test_summary_is_a_table_per_strategy_and_doc_type_with_missing_sections() -> None:
    report = StructuralReport(datetime(2026, 1, 2, tzinfo=UTC), ["fixed_words"], [_metrics("fixed_words", "panel")])

    out = format_structural_summary(report)

    for word in ("fixed_words", "panel", "p10", "median", "p90", "header", "grid", "crossing", "not recognized"):
        assert word in out
    assert "n/a" in out  # no grid share outside district reports
    assert "Background" in out and "https://example.test/a.pdf" in out


def test_summary_lists_stale_chunk_sets_and_the_rechunk_hint() -> None:
    stale = StaleChunkSet("https://example.test/b.pdf", "panel", "structure_aware", 4)
    report = StructuralReport(
        datetime(2026, 1, 2, tzinfo=UTC), ["fixed_words"], [_metrics("fixed_words", "panel")], [stale]
    )

    out = format_structural_summary(report)

    assert "Stale chunk sets: 1" in out
    assert "https://example.test/b.pdf" in out and "structure_aware" in out and "4" in out
    assert out.rstrip().endswith('run "offshore-rag rechunk" to rebuild them')
    clean = format_structural_summary(StructuralReport(report.generated_at, ["fixed_words"], report.entries))
    assert "rechunk" not in clean


def test_unreachable_database_exits_1_without_password(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:secret-pw-1@127.0.0.1:{port}/db1")
    result = runner.invoke(app, ["chunk-report"])
    assert result.exit_code == 1
    assert str(port) in result.output and "secret-pw-1" not in result.output
    assert _reports(env) == []


@pytest.mark.integration
def test_default_strategies_are_those_stored(
    env: Path, monkeypatch: pytest.MonkeyPatch, postgres: PgSchema, server: FixtureServer
) -> None:
    _ingest(env, monkeypatch, postgres, server)

    result = runner.invoke(app, ["chunk-report"])

    assert result.exit_code == 0, result.output
    [name] = _reports(env)
    data = json.loads((env / "data" / "reports" / name).read_text(encoding="utf-8"))
    assert data["strategies"] == ["fixed_words"]
    assert name in result.output and "fixed_words" in result.output


@pytest.mark.integration
def test_explicit_strategy_without_chunks_exits_1_and_writes_nothing(
    env: Path, monkeypatch: pytest.MonkeyPatch, postgres: PgSchema, server: FixtureServer
) -> None:
    _ingest(env, monkeypatch, postgres, server)

    ok = runner.invoke(app, ["chunk-report", "--strategy", "fixed_words"])
    assert ok.exit_code == 0, ok.output
    written = _reports(env)

    result = runner.invoke(app, ["chunk-report", "--strategy", "fixed_words", "--strategy", "structure_aware"])

    assert result.exit_code == 1
    assert "structure_aware" in result.output
    assert _reports(env) == written


@pytest.mark.integration
def test_empty_corpus_exits_1(env: Path, monkeypatch: pytest.MonkeyPatch, postgres: PgSchema) -> None:
    migrate(postgres.conn)
    monkeypatch.setenv("DATABASE_URL", postgres.url)

    result = runner.invoke(app, ["chunk-report"])

    assert result.exit_code == 1
    assert "no chunks" in result.output
    assert _reports(env) == []


@pytest.mark.integration
def test_stale_chunk_set_exits_3_with_the_file_written_and_the_rechunk_hint(
    env: Path, monkeypatch: pytest.MonkeyPatch, postgres: PgSchema, server: FixtureServer
) -> None:
    _ingest(env, monkeypatch, postgres, server)
    postgres.conn.execute("UPDATE chunks SET text = 'words never on any stored page' WHERE ordinal = 0")

    result = runner.invoke(app, ["chunk-report"])

    assert result.exit_code == 3, result.output
    [name] = _reports(env)
    data = json.loads((env / "data" / "reports" / name).read_text(encoding="utf-8"))
    [item] = data["stale_chunk_sets"]
    assert item == {
        "source_url": server.url("/a.pdf"),
        "doc_type": "safety_alert",
        "strategy": "fixed_words",
        "ordinal": 0,
    }
    assert name in result.output and "offshore-rag rechunk" in result.output
