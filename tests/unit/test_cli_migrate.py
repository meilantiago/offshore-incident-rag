"""`offshore-rag db migrate` (AC-001-12)."""

from __future__ import annotations

import socket

import pytest
from typer.testing import CliRunner

from offshore_rag.cli import app
from tests.conftest import PgSchema

runner = CliRunner()


@pytest.mark.integration
def test_db_migrate_applies_migrations(postgres: PgSchema, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", postgres.url)
    result = runner.invoke(app, ["db", "migrate"])
    assert result.exit_code == 0, result.output
    assert "0001_corpus" in result.output
    assert "0002_chunk_section" in result.output
    assert postgres.table_exists("documents")
    again = runner.invoke(app, ["db", "migrate"])
    assert again.exit_code == 0, again.output


def test_db_migrate_unreachable_database_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setenv("DATABASE_URL", f"postgresql://u:pa55w0rd-xyz@127.0.0.1:{port}/somedb")
    result = runner.invoke(app, ["db", "migrate"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "127.0.0.1" in result.output
    assert str(port) in result.output
    assert "somedb" in result.output
    assert "pa55w0rd-xyz" not in result.output
