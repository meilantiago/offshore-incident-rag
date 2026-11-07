"""Plain-SQL migrations, applied in order, each in its own transaction (plan.md#Migrations).

`schema_migrations` lives in the current schema of the connection (search_path); the SQL files name no schema.
"""

from __future__ import annotations

from importlib import resources
from typing import Any

import psycopg

_TABLE = "schema_migrations"


def _available() -> dict[str, str]:
    files = resources.files("offshore_rag.db").joinpath("migrations")
    return {
        f.name.removesuffix(".sql"): f.read_text(encoding="utf-8")
        for f in sorted(files.iterdir(), key=lambda f: f.name)
        if f.name.endswith(".sql")
    }


def _applied(conn: psycopg.Connection[Any]) -> set[str]:
    row = conn.execute("SELECT to_regclass(current_schema() || '.' || %s) IS NOT NULL", (_TABLE,)).fetchone()
    if row is None or not row[0]:
        return set()
    return {r[0] for r in conn.execute(f"SELECT version FROM {_TABLE}").fetchall()}


def pending_migrations(conn: psycopg.Connection[Any]) -> list[str]:
    applied = _applied(conn)
    return [v for v in _available() if v not in applied]


def migrate(conn: psycopg.Connection[Any]) -> list[str]:
    """Apply every pending migration; returns the versions applied (empty when up to date)."""
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {_TABLE} (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    available = _available()
    applied: list[str] = []
    for version in pending_migrations(conn):
        with conn.transaction():
            conn.execute(available[version].encode())
            conn.execute(f"INSERT INTO {_TABLE} (version) VALUES (%s)", (version,))
        applied.append(version)
    return applied
