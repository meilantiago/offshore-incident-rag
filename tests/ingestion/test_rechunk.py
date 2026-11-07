"""AC-002-09, AC-002-12: `offshore-rag rechunk` builds chunk sets from stored pages, without downloading.

A corpus is ingested with `fixed_words` only; then `structure_aware` is enabled and `rechunk` runs, twice.
"""

from __future__ import annotations

import re
import socket
import uuid
from urllib.parse import quote

import pytest

from tests.conftest import migrate_schema, with_search_path
from tests.support.ingest import EXIT_FATAL, EXIT_OK, IngestEnv, assert_exit, run_cli
from tests.support.structure import (
    COMMITTED,
    FIXED,
    STRUCTURE,
    UNRECOGNIZED_DISTRICT,
    chunk_counts,
    chunk_rows,
    serve_docs,
    set_strategies,
)

pytestmark = pytest.mark.integration


def _numbers_on_lines(stdout: str, *needles: str) -> list[int]:
    """Integers on the stdout lines that contain every needle (case-insensitive)."""
    out: list[int] = []
    for line in stdout.splitlines():
        low = line.lower()
        if all(n.lower() in low for n in needles):
            out += [int(x) for x in re.findall(r"(?<![\w.])\d+(?![\w.])", line.replace(",", ""))]
    return out


def test_ac_002_09_rechunk_adds_structure_aware_without_downloading(db_env: IngestEnv) -> None:
    """AC-002-09: structure_aware sets for every stored document, no HTTP request, fixed_words ids and text kept,
    a second run creates no duplicate set, and a summary is printed."""
    migrate_schema(db_env.db)
    docs = serve_docs(db_env, [*COMMITTED, UNRECOGNIZED_DISTRICT])
    set_strategies(db_env, [FIXED])
    assert_exit(db_env.ingest(), EXIT_OK)
    fixed_before = db_env.db.rows("SELECT id, document_id, text FROM chunks WHERE chunker = %s ORDER BY id", (FIXED,))
    assert fixed_before and not db_env.db.scalar("SELECT count(*) FROM chunks WHERE chunker = %s", (STRUCTURE,))
    db_env.server.clear_requests()
    set_strategies(db_env, [FIXED, STRUCTURE])

    run = run_cli("rechunk")

    assert_exit(run, EXIT_OK)
    assert db_env.server.requests == [], "re-chunking must not send any HTTP request"
    for url, doc in docs.items():
        assert chunk_rows(db_env, url, STRUCTURE), f"{doc.name}: no structure_aware chunks after rechunk"
    fixed_after = db_env.db.rows("SELECT id, document_id, text FROM chunks WHERE chunker = %s ORDER BY id", (FIXED,))
    assert fixed_after == fixed_before, "existing fixed_words chunks keep their ids and text"

    created = db_env.db.scalar("SELECT count(*) FROM chunks WHERE chunker = %s", (STRUCTURE,))
    assert len(docs) in _numbers_on_lines(run.stdout, "document"), f"documents processed not printed:\n{run.stdout}"
    assert created in _numbers_on_lines(run.stdout, STRUCTURE), (
        f"structure_aware chunks created not printed:\n{run.stdout}"
    )
    assert re.search(r"(?i)not[ _-]?recogni[sz]ed", run.stdout), f"no structure-not-recognized line:\n{run.stdout}"
    unrecognized_url = next(u for u, d in docs.items() if d is UNRECOGNIZED_DISTRICT)
    assert unrecognized_url in run.stdout, "the structure-not-recognized documents are listed"
    for strategy in (FIXED, STRUCTURE):
        assert _numbers_on_lines(run.stdout, strategy) or re.search(
            rf"(?i){strategy}.*\d+(\.\d+)?\s*(ms|s)\b", run.stdout
        ), f"no per-strategy figures for {strategy}"
    assert re.search(r"(?i)duration|elapsed|\btime\b", run.stdout), f"no duration in the summary:\n{run.stdout}"

    counts_first = chunk_counts(db_env)
    db_env.server.clear_requests()

    second = run_cli("rechunk")

    assert_exit(second, EXIT_OK)
    assert chunk_counts(db_env) == counts_first, "a second rechunk must not duplicate any chunk set"
    assert db_env.server.requests == []
    assert (
        db_env.db.rows("SELECT id, document_id, text FROM chunks WHERE chunker = %s ORDER BY id", (FIXED,))
        == fixed_before
    )


def test_ac_002_09_rechunk_only_touches_configured_types(db_env: IngestEnv) -> None:
    """AC-002-09: with structure_aware configured for district reports only, only they get structure_aware sets."""
    migrate_schema(db_env.db)
    docs = serve_docs(db_env, COMMITTED)
    assert_exit(db_env.ingest(), EXIT_OK)
    set_strategies(db_env, [FIXED], {"district_report": [FIXED, STRUCTURE]})

    run = run_cli("rechunk")

    assert_exit(run, EXIT_OK)
    for url, doc in docs.items():
        has = bool(chunk_rows(db_env, url, STRUCTURE))
        assert has == (doc.doc_type == "district_report"), f"{doc.name}: structure_aware chunks present={has}"


# -- AC-002-12: database unreachable or schema missing ------------------------------------------------------------
def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_ac_002_12_rechunk_with_unreachable_database_is_fatal_without_password(http_env: IngestEnv) -> None:
    """AC-002-12: Postgres unreachable → rechunk exits 1 naming host, port and database, never the password."""
    port = _free_port()
    password = "Sup3r-S3cret-pw-" + uuid.uuid4().hex[:8]
    http_env.setenv("DATABASE_URL", f"postgresql://rechunk_user:{password}@127.0.0.1:{port}/corpus_offline")
    set_strategies(http_env, [FIXED, STRUCTURE])

    run = run_cli("rechunk")

    assert_exit(run, EXIT_FATAL)
    assert "127.0.0.1" in run.output and str(port) in run.output and "corpus_offline" in run.output, run.describe()
    assert password not in run.output, "the password must never be printed"
    assert http_env.server.requests == []


def test_ac_002_12_rechunk_with_missing_schema_is_fatal_without_password(
    db_env: IngestEnv, limited_role: tuple[str, str]
) -> None:
    """AC-002-12: reachable Postgres without migrations → rechunk exits 1, names the connection and the schema."""
    role, password = limited_role
    params = db_env.db.params
    host, port, dbname = params.get("host", "localhost"), params.get("port", "5432"), params["dbname"]
    url = with_search_path(f"postgresql://{role}:{quote(password, safe='')}@{host}:{port}/{dbname}", db_env.db.schema)
    db_env.setenv("DATABASE_URL", url)
    set_strategies(db_env, [FIXED, STRUCTURE])

    run = run_cli("rechunk")

    assert_exit(run, EXIT_FATAL)
    assert host in run.output and str(port) in run.output and dbname in run.output, run.describe()
    assert password not in run.output, "the password must never be printed"
    assert re.search(r"schema|migrat", run.output, re.IGNORECASE), "the error says the schema is missing"
    assert not db_env.db.table_exists("chunks"), "rechunk must not migrate by itself"
