"""`offshore-rag ingest`: validation, fatal checks and exit codes (T13)."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from offshore_rag.cli import app
from offshore_rag.db.migrate import migrate
from tests.conftest import PgSchema
from tests.support import pdfs
from tests.support.http_server import FixtureServer

runner = CliRunner()


@pytest.fixture
def server() -> Iterator[FixtureServer]:
    with FixtureServer() as s:
        yield s


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, server: FixtureServer) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MANIFEST_PATH", str(tmp_path / "manifest.jsonl"))
    monkeypatch.setenv("HTTP_RATE_PER_SECOND", "100")
    monkeypatch.setenv("HTTP_MAX_RETRIES", "0")
    monkeypatch.setenv("CHUNKERS", "fixed_words")
    return tmp_path


def _manifest(tmp: Path, server: FixtureServer, paths: list[str]) -> None:
    lines = [
        json.dumps({"doc_type": "safety_alert", "listing_url": server.url("/l"), "source_url": server.url(p)})
        for p in paths
    ]
    (tmp / "manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_invalid_manifest_exits_1_before_any_request(env: Path, server: FixtureServer) -> None:
    (env / "manifest.jsonl").write_text('{"doc_type": "safety_alert"}\n', encoding="utf-8")
    result = runner.invoke(app, ["ingest"])
    assert result.exit_code == 1, result.output
    assert "line 1" in result.output and "source_url" in result.output
    assert server.requests == []


def test_unknown_chunker_exits_1(env: Path, server: FixtureServer, monkeypatch: pytest.MonkeyPatch) -> None:
    _manifest(env, server, ["/a.pdf"])
    monkeypatch.setenv("CHUNKERS", "nope")
    result = runner.invoke(app, ["ingest"])
    assert result.exit_code == 1 and "nope" in result.output
    assert server.requests == []


def test_unreachable_database_exits_1_before_any_request(
    env: Path, server: FixtureServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    _manifest(env, server, ["/a.pdf"])
    port = _free_port()
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:secret-pw-1@127.0.0.1:{port}/db1")
    result = runner.invoke(app, ["ingest"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert str(port) in result.output and "secret-pw-1" not in result.output
    assert server.requests == []


@pytest.mark.integration
def test_unmigrated_database_exits_1_before_any_request(
    env: Path, server: FixtureServer, monkeypatch: pytest.MonkeyPatch, postgres: PgSchema
) -> None:
    _manifest(env, server, ["/a.pdf"])
    monkeypatch.setenv("DATABASE_URL", postgres.url)
    result = runner.invoke(app, ["ingest"])
    assert result.exit_code == 1
    assert "migrat" in result.output.lower()
    assert server.requests == []
    assert not postgres.table_exists("documents")


@pytest.mark.integration
def test_partial_failure_exits_3_and_success_exits_0(
    env: Path, server: FixtureServer, monkeypatch: pytest.MonkeyPatch, postgres: PgSchema
) -> None:
    migrate(postgres.conn)
    monkeypatch.setenv("DATABASE_URL", postgres.url)
    server.add("/a.pdf", pdfs.text_pdf(2))
    _manifest(env, server, ["/a.pdf", "/missing.pdf"])
    partial = runner.invoke(app, ["ingest"])
    assert partial.exit_code == 3, partial.output
    reports = sorted((env / "data" / "reports").glob("ingest-*.json"))
    assert len(reports) == 1 and str(reports[0]) in partial.output.replace("\n", "")

    _manifest(env, server, ["/a.pdf"])
    ok = runner.invoke(app, ["ingest"])
    assert ok.exit_code == 0, ok.output
    assert "skipped unchanged: 1" in ok.output
