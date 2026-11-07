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
    assert pending_migrations(postgres.conn) == ["0001_corpus", "0002_chunk_section"]
    applied = migrate(postgres.conn)
    assert applied == ["0001_corpus", "0002_chunk_section"]
    for table in ("documents", "pages", "chunks", "schema_migrations"):
        assert postgres.table_exists(table), table
    assert pending_migrations(postgres.conn) == []
    assert migrate(postgres.conn) == []
    assert postgres.scalar("SELECT count(*) FROM schema_migrations") == 2


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


_CHUNK_INSERT = (
    "INSERT INTO chunks (document_id, chunker, chunker_params, ordinal, page_start, page_end, text, "
    "char_count, word_count, section) VALUES (%s, 'c', '{}', %s, 1, 1, 'x', 1, 1, %s)"
)


def _document(postgres: PgSchema) -> int:
    postgres.conn.execute(
        "INSERT INTO documents (source_url, doc_type, listing_url, sha256, retrieved_at, raw_path, page_count, "
        "image_only) VALUES ('u', 'safety_alert', 'l', %s, now(), 'p', 1, false)",
        ("a" * 64,),
    )
    return int(postgres.scalar("SELECT id FROM documents WHERE source_url = 'u'"))


def test_ac_002_01_migration_0002_applies_on_clean_schema_and_on_0001(
    postgres: PgSchema, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-002-01: 0002 applies from scratch and on a schema already at 0001."""
    from offshore_rag.db import migrate as m

    original = m._available()
    monkeypatch.setattr(m, "_available", lambda: {k: v for k, v in original.items() if k == "0001_corpus"})
    assert migrate(postgres.conn) == ["0001_corpus"]
    monkeypatch.setattr(m, "_available", lambda: original)
    assert migrate(postgres.conn) == ["0002_chunk_section"]
    assert (
        postgres.scalar(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema = current_schema() "
            "AND table_name = 'chunks' AND column_name = 'section'"
        )
        == 1
    )


def test_ac_002_01_empty_section_rejected_and_null_allowed(postgres: PgSchema) -> None:
    """AC-002-01: `section` is NULL (fixed_words) or non-empty (structure_aware); an empty label is rejected."""
    migrate(postgres.conn)
    doc_id = _document(postgres)
    postgres.conn.execute(_CHUNK_INSERT, (doc_id, 0, None))
    postgres.conn.execute(_CHUNK_INSERT, (doc_id, 1, "Findings"))
    with pytest.raises(psycopg.errors.CheckViolation):
        postgres.conn.execute(_CHUNK_INSERT, (doc_id, 2, ""))
