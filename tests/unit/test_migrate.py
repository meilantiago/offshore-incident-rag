"""Migrations on an empty schema (AC-001-12) and an unreachable database."""

from __future__ import annotations

import socket

import psycopg
import pytest

from offshore_rag.config import Settings
from offshore_rag.db.connection import DatabaseUnavailable, connect
from offshore_rag.db.migrate import migrate, pending_migrations
from tests.conftest import PgSchema

pytestmark = pytest.mark.integration


def test_migrate_creates_tables_and_is_idempotent(postgres: PgSchema) -> None:
    assert pending_migrations(postgres.conn) == ["0001_corpus"]
    applied = migrate(postgres.conn)
    assert applied == ["0001_corpus"]
    for table in ("documents", "pages", "chunks", "schema_migrations"):
        assert postgres.table_exists(table), table
    assert pending_migrations(postgres.conn) == []
    assert migrate(postgres.conn) == []
    assert postgres.scalar("SELECT count(*) FROM schema_migrations") == 1


def test_checks_are_enforced(postgres: PgSchema) -> None:
    migrate(postgres.conn)
    insert = (
        "INSERT INTO documents (source_url, doc_type, listing_url, sha256, retrieved_at, raw_path, page_count, "
        "image_only) VALUES (%s, %s, 'l', %s, now(), 'p', %s, false)"
    )
    sha = "a" * 64
    with pytest.raises(psycopg.errors.CheckViolation):
        postgres.conn.execute(insert, ("u1", "bogus", sha, 1))
    with pytest.raises(psycopg.errors.CheckViolation):
        postgres.conn.execute(insert, ("u2", "safety_alert", sha, 0))
    postgres.conn.execute(insert, ("u3", "safety_alert", sha, 2))
    with pytest.raises(psycopg.errors.UniqueViolation):
        postgres.conn.execute(insert, ("u3", "panel_report", sha, 2))
    doc_id = postgres.scalar("SELECT id FROM documents WHERE source_url = 'u3'")
    with pytest.raises(psycopg.errors.CheckViolation):
        postgres.conn.execute(
            "INSERT INTO pages (document_id, page_number, text, image_only, char_count) VALUES (%s, 0, '', true, 0)",
            (doc_id,),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        postgres.conn.execute(
            "INSERT INTO chunks (document_id, chunker, chunker_params, ordinal, page_start, page_end, text, "
            "char_count, word_count) VALUES (%s, 'c', '{}', 0, 2, 1, 'x', 1, 1)",
            (doc_id,),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        postgres.conn.execute(
            "INSERT INTO chunks (document_id, chunker, chunker_params, ordinal, page_start, page_end, text, "
            "char_count, word_count) VALUES (%s, 'c', '{}', 0, 1, 1, '', 0, 0)",
            (doc_id,),
        )


def test_unreachable_database_raises_without_password() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    settings = Settings(database_url=f"postgresql://u:pa55w0rd-xyz@127.0.0.1:{port}/somedb", _env_file=None)  # type: ignore[arg-type]
    with pytest.raises(DatabaseUnavailable) as exc:
        connect(settings)
    msg = str(exc.value)
    assert "pa55w0rd-xyz" not in msg
    assert "127.0.0.1" in msg
    assert str(port) in msg
    assert "somedb" in msg


def test_missing_database_url_raises() -> None:
    with pytest.raises(DatabaseUnavailable, match="DATABASE_URL"):
        connect(Settings(_env_file=None))
