"""AC-001-12: an unreachable database or a missing schema is fatal before any download, password never shown."""

from __future__ import annotations

import re
import socket
import uuid
from collections.abc import Iterator
from urllib.parse import quote

import psycopg
import pytest

from tests.conftest import PgSchema, with_search_path
from tests.support import pdfs
from tests.support.ingest import EXIT_FATAL, IngestEnv, assert_exit

pytestmark = pytest.mark.integration


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _valid_manifest(env: IngestEnv) -> None:
    env.serve_pdf("/sites/bsee.gov/files/a.pdf", pdfs.text_pdf(2))
    env.write_manifest([env.entry("/sites/bsee.gov/files/a.pdf")])


def test_ac_001_12_unreachable_database_is_fatal_before_download(http_env: IngestEnv) -> None:
    """AC-001-12: Postgres unreachable → exit 1, no request sent, error names host/port/db without the password."""
    port = _free_port()
    password = "Sup3r-S3cret-pw-" + uuid.uuid4().hex[:8]
    http_env.setenv("DATABASE_URL", f"postgresql://ingest_user:{password}@127.0.0.1:{port}/corpus_offline")
    _valid_manifest(http_env)

    run = http_env.ingest()

    assert_exit(run, EXIT_FATAL)
    assert http_env.server.requests == [], "nothing may be downloaded when the database is unreachable"
    assert "127.0.0.1" in run.output, run.describe()
    assert str(port) in run.output
    assert "corpus_offline" in run.output
    assert password not in run.output, "the password must never be printed"
    assert not (http_env.data_dir / "raw").exists() or not any((http_env.data_dir / "raw").iterdir())


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


def test_ac_001_12_missing_schema_is_fatal_before_download(db_env: IngestEnv, limited_role: tuple[str, str]) -> None:
    """AC-001-12: reachable Postgres without migrations → exit 1, nothing downloaded, ingest does not migrate."""
    role, password = limited_role
    params = db_env.db.params
    host, port, dbname = params.get("host", "localhost"), params.get("port", "5432"), params["dbname"]
    url = with_search_path(f"postgresql://{role}:{quote(password, safe='')}@{host}:{port}/{dbname}", db_env.db.schema)
    db_env.setenv("DATABASE_URL", url)
    _valid_manifest(db_env)

    run = db_env.ingest()

    assert_exit(run, EXIT_FATAL)
    assert db_env.server.requests == [], "nothing may be downloaded when the schema is missing"
    assert host in run.output, run.describe()
    assert str(port) in run.output
    assert dbname in run.output
    assert password not in run.output, "the password must never be printed"
    assert re.search(r"schema|migrat", run.output, re.IGNORECASE), "the error should say the schema is missing"
    assert not db_env.db.table_exists("documents"), "ingest must not migrate by itself"


MALFORMED_URL = "rag:SECRETPW@localhost/rag"


@pytest.mark.parametrize("args", [("ingest",), ("db", "migrate")])
def test_ac_001_12_malformed_database_url_is_clean_fatal_without_password(
    http_env: IngestEnv, args: tuple[str, ...]
) -> None:
    """AC-001-12: an unparseable DATABASE_URL → exit 1, names the database connection, no password, no traceback."""
    from tests.support.ingest import run_cli

    http_env.setenv("DATABASE_URL", MALFORMED_URL)
    _valid_manifest(http_env)

    run = run_cli(*args)

    assert_exit(run, EXIT_FATAL)
    assert "SECRETPW" not in run.output, run.describe()
    assert "Traceback" not in run.output
    assert re.search(r"database", run.output, re.IGNORECASE), run.describe()
    assert http_env.server.requests == []
