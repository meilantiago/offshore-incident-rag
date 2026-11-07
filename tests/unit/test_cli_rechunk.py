"""`offshore-rag rechunk`: exit codes and fatal checks (spec 002 T09)."""

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
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MANIFEST_PATH", str(tmp_path / "manifest.jsonl"))
    monkeypatch.setenv("HTTP_RATE_PER_SECOND", "100")
    monkeypatch.setenv("HTTP_MAX_RETRIES", "0")
    monkeypatch.setenv("CHUNKERS", "fixed_words")
    return tmp_path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_invalid_config_exits_1_before_database_access(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()  # nothing listens: reaching the database would name the port in a connection error
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:secret-pw-1@127.0.0.1:{port}/db1")
    monkeypatch.setenv("CHUNKERS", "nope")
    result = runner.invoke(app, ["rechunk"])
    assert result.exit_code == 1
    assert "CHUNKERS" in result.output and "nope" in result.output and str(port) not in result.output


def test_unreachable_database_exits_1_without_password(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:secret-pw-1@127.0.0.1:{port}/db1")
    result = runner.invoke(app, ["rechunk"])
    assert result.exit_code == 1
    assert str(port) in result.output and "secret-pw-1" not in result.output


@pytest.mark.integration
def test_unmigrated_database_exits_1(env: Path, monkeypatch: pytest.MonkeyPatch, postgres: PgSchema) -> None:
    monkeypatch.setenv("DATABASE_URL", postgres.url)
    result = runner.invoke(app, ["rechunk"])
    assert result.exit_code == 1
    assert "migrat" in result.output.lower()
    assert not postgres.table_exists("documents")


@pytest.mark.integration
def test_rechunk_exits_0_and_prints_the_summary(
    env: Path, monkeypatch: pytest.MonkeyPatch, postgres: PgSchema, server: FixtureServer
) -> None:
    migrate(postgres.conn)
    monkeypatch.setenv("DATABASE_URL", postgres.url)
    server.add("/a.pdf", pdfs.text_pdf(2))
    (env / "manifest.jsonl").write_text(
        json.dumps({"doc_type": "safety_alert", "listing_url": server.url("/l"), "source_url": server.url("/a.pdf")})
        + "\n",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["ingest"]).exit_code == 0
    server.clear_requests()
    monkeypatch.setenv("CHUNKERS", "fixed_words,structure_aware")
    result = runner.invoke(app, ["rechunk"])
    assert result.exit_code == 0, result.output
    assert "documents processed: 1" in result.output and "structure_aware" in result.output
    assert server.requests == []
