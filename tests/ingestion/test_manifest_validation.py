"""AC-001-02: a malformed manifest stops `ingest` before any download or database write."""

from __future__ import annotations

import json
import re

import pytest

from tests.conftest import migrate_schema
from tests.support import pdfs
from tests.support.ingest import EXIT_FATAL, IngestEnv, assert_exit

pytestmark = pytest.mark.integration


def _valid(env: IngestEnv, name: str) -> dict[str, object]:
    path = f"/sites/bsee.gov/files/{name}.pdf"
    env.serve_pdf(path, pdfs.text_pdf(1))
    return env.entry(path)


def _assert_nothing_happened(env: IngestEnv) -> None:
    assert env.server.requests == [], "no HTTP request may be sent when the manifest is invalid"
    assert env.counts() == (0, 0, 0), "nothing may be written to the database when the manifest is invalid"
    raw = env.data_dir / "raw"
    assert not raw.exists() or not any(raw.iterdir()), "no raw file may be saved when the manifest is invalid"


def test_ac_001_02_entry_without_source_url_is_named(db_env: IngestEnv) -> None:
    """AC-001-02: an entry without a source URL → exit 1, the entry is named by its line, nothing done."""
    migrate_schema(db_env.db)
    first, second = _valid(db_env, "a"), _valid(db_env, "b")
    broken = {k: v for k, v in _valid(db_env, "c").items() if k != "source_url"}
    lines = [json.dumps(first, sort_keys=True), json.dumps(broken, sort_keys=True), json.dumps(second, sort_keys=True)]
    db_env.write_manifest_lines(lines)

    run = db_env.ingest()

    assert_exit(run, EXIT_FATAL)
    assert re.search(r"line\W*2\b", run.output, re.IGNORECASE), run.describe()
    assert "source_url" in run.output
    _assert_nothing_happened(db_env)


def test_ac_001_02_unknown_document_type_is_named(db_env: IngestEnv) -> None:
    """AC-001-02: an unknown document type → exit 1, the offending entry named by its source URL, nothing done."""
    migrate_schema(db_env.db)
    bad = {**_valid(db_env, "press"), "doc_type": "press_release"}
    db_env.write_manifest([_valid(db_env, "ok"), bad])

    run = db_env.ingest()

    assert_exit(run, EXIT_FATAL)
    assert str(bad["source_url"]) in run.output, run.describe()
    assert "press_release" in run.output
    _assert_nothing_happened(db_env)


def test_ac_001_02_duplicate_source_url_is_named(db_env: IngestEnv) -> None:
    """AC-001-02: a duplicate source URL → exit 1, the duplicated URL named, nothing done."""
    migrate_schema(db_env.db)
    dup = _valid(db_env, "dup")
    db_env.write_manifest([_valid(db_env, "ok"), dup, {**dup, "title": "same file, other title"}])

    run = db_env.ingest()

    assert_exit(run, EXIT_FATAL)
    assert str(dup["source_url"]) in run.output, run.describe()
    assert "duplicate" in run.output.lower()
    _assert_nothing_happened(db_env)


def test_ac_001_02_empty_manifest_is_reported(db_env: IngestEnv) -> None:
    """AC-001-02: a manifest with no entries → exit 1 stating that the manifest is empty, nothing done."""
    migrate_schema(db_env.db)
    db_env.write_manifest_lines([])

    run = db_env.ingest()

    assert_exit(run, EXIT_FATAL)
    assert "empty" in run.output.lower(), run.describe()
    _assert_nothing_happened(db_env)


def test_ac_001_02_every_offending_entry_is_named(db_env: IngestEnv) -> None:
    """AC-001-02: with several problems at once, each offending entry is named, not only the first."""
    migrate_schema(db_env.db)
    ok = _valid(db_env, "ok")
    unknown = {**_valid(db_env, "unknown"), "doc_type": "research_report"}
    dup = _valid(db_env, "dup")
    missing = {k: v for k, v in _valid(db_env, "missing").items() if k != "source_url"}
    lines = [json.dumps(e, sort_keys=True) for e in (ok, unknown, dup, dup, missing)]
    db_env.write_manifest_lines(lines)

    run = db_env.ingest()

    assert_exit(run, EXIT_FATAL)
    assert str(unknown["source_url"]) in run.output, run.describe()
    assert str(dup["source_url"]) in run.output, run.describe()
    assert re.search(r"line\W*5\b", run.output, re.IGNORECASE), run.describe()
    _assert_nothing_happened(db_env)
