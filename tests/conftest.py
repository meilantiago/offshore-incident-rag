"""Shared pytest configuration. Acceptance tests carry their AC id (`AC-NNN-XX`) in the name or docstring.

The `postgres` fixture gives each test a fresh, empty schema in the database at `TEST_DATABASE_URL`
(`docker compose up -d db`). `PgSchema.url` is a connection URL whose `search_path` points at that schema, so the
code under test (which reads `DATABASE_URL`) works inside it. The schema is NOT migrated: tests that need the corpus
tables call `migrate_schema(pg)`, which runs the production migrations.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

TEST_DB_ENV = "TEST_DATABASE_URL"


@dataclass
class PgSchema:
    schema: str
    url: str  # TEST_DATABASE_URL + options=-csearch_path=<schema>; pass it as DATABASE_URL
    base_url: str  # TEST_DATABASE_URL as given
    conn: psycopg.Connection[Any]  # autocommit connection with search_path set, for assertions

    @property
    def params(self) -> dict[str, Any]:
        return conninfo_to_dict(self.base_url)

    def scalar(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> Any:
        row = self.conn.execute(sql, params).fetchone()
        return None if row is None else row[0]

    def rows(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[tuple[Any, ...]]:
        return self.conn.execute(sql, params).fetchall()

    def table_exists(self, name: str) -> bool:
        return bool(self.scalar("SELECT to_regclass(%s) IS NOT NULL", (f"{self.schema}.{name}",)))


def with_search_path(url: str, schema: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}options={quote(f'-csearch_path={schema}', safe='')}"


def migrate_schema(pg: PgSchema) -> None:
    """Apply the production migrations to the test schema (offshore_rag.db.migrate, plan.md#Package layout)."""
    from offshore_rag.db.migrate import migrate

    migrate(pg.conn)


@pytest.fixture
def postgres() -> Iterator[PgSchema]:
    base = os.environ.get(TEST_DB_ENV)
    if not base:
        pytest.fail(
            f"{TEST_DB_ENV} is not set. Integration tests need Postgres: run `docker compose up -d db` and set "
            f"{TEST_DB_ENV}=postgresql://rag:rag@localhost:5432/rag (see .env.example). "
            "Tests are not skipped on purpose (constitution §3)."
        )
    schema = f"t_{uuid.uuid4().hex[:12]}"
    try:
        admin = psycopg.connect(base, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as e:
        pytest.fail(f"cannot connect to {TEST_DB_ENV} ({e}). Is `docker compose up -d db` running?")
    admin.execute(f'CREATE SCHEMA "{schema}"')
    url = with_search_path(base, schema)
    conn = psycopg.connect(url, autocommit=True)
    try:
        yield PgSchema(schema=schema, url=url, base_url=base, conn=conn)
    finally:
        conn.close()
        _drop_schema(admin, schema)
        admin.close()


def _drop_schema(admin: psycopg.Connection[Any], schema: str) -> None:
    admin.execute("SET lock_timeout = '5s'")
    try:
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
    except psycopg.errors.LockNotAvailable:
        # A connection leaked by the code under test still holds a lock: end it, then drop.
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid()"
        )
        admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
