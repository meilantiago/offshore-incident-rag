"""Fixtures for the corpus-ingestion acceptance tests (spec 001). Helpers are in tests/support/ingest.py."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from tests.conftest import PgSchema
from tests.support.http_server import FixtureServer
from tests.support.ingest import TEST_USER_AGENT, IngestEnv


@pytest.fixture
def server() -> Iterator[FixtureServer]:
    with FixtureServer(timeout_stall_seconds=3.0) as s:
        yield s


def _base_env(env: IngestEnv) -> None:
    mp = env.monkeypatch
    mp.chdir(env.tmp)  # no stray .env file, relative defaults land in the temp dir
    for name in ("LOG_FORMAT", "CHUNKERS_BY_DOC_TYPE"):
        mp.delenv(name, raising=False)
    env.setenv("DATA_DIR", env.data_dir)
    env.setenv("MANIFEST_PATH", env.manifest_path)
    env.setenv("BSEE_BASE_URL", env.server.base_url)
    env.setenv("HTTP_USER_AGENT", TEST_USER_AGENT)
    env.setenv("HTTP_RATE_PER_SECOND", 50)
    env.setenv("HTTP_MAX_RETRIES", 2)
    env.setenv("HTTP_TIMEOUT_SECONDS", 2)
    env.setenv("CHUNKERS", "fixed_words")


@pytest.fixture
def http_env(tmp_path: Path, server: FixtureServer, monkeypatch: pytest.MonkeyPatch) -> IngestEnv:
    """Operator environment without a database (DATABASE_URL points nowhere useful)."""
    env = IngestEnv(tmp_path, server, monkeypatch)
    _base_env(env)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return env


@pytest.fixture
def db_env(tmp_path: Path, server: FixtureServer, monkeypatch: pytest.MonkeyPatch, postgres: PgSchema) -> IngestEnv:
    """Operator environment with DATABASE_URL pointing at a fresh, NOT yet migrated test schema."""
    env = IngestEnv(tmp_path, server, monkeypatch, pg=postgres)
    _base_env(env)
    env.setenv("DATABASE_URL", postgres.url)
    return env


@pytest.fixture
def limited_role(postgres: PgSchema) -> Iterator[tuple[str, str]]:
    """A login role with a distinctive password, allowed to use the (unmigrated) test schema."""
    role = f"r_{uuid.uuid4().hex[:10]}"
    password = "Pw-" + uuid.uuid4().hex
    admin = psycopg.connect(postgres.base_url, autocommit=True)
    admin.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'")
    admin.execute(f'GRANT USAGE ON SCHEMA "{postgres.schema}" TO {role}')
    try:
        yield role, password
    finally:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = %s", (role,))
        admin.execute(f"DROP OWNED BY {role}")
        admin.execute(f"DROP ROLE {role}")
        admin.close()
