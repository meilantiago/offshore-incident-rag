"""AC-002-01, AC-002-02: which chunking strategies run for each document type, and invalid configuration.

Configuration goes through the environment (plan.md#Strategy selection): `CHUNKERS` (comma-separated, every type)
and `CHUNKERS_BY_DOC_TYPE` (JSON object `{doc_type: [strategy, ...]}` replacing the list for the types it names).
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from tests.conftest import migrate_schema
from tests.support.ingest import EXIT_FATAL, EXIT_OK, CliRun, IngestEnv, assert_exit, run_cli
from tests.support.structure import (
    COMMITTED,
    DOC_TYPES,
    FIXED,
    SIZE_CAP,
    STRUCTURE,
    chunk_rows,
    serve_docs,
    set_strategies,
)


def _params_key(params: Any) -> str:
    return json.dumps(params, sort_keys=True)


def _fixed_rows(env: IngestEnv, url: str) -> list[tuple[Any, ...]]:
    return [
        (c["ordinal"], c["page_start"], c["page_end"], c["text"], _params_key(c["chunker_params"]))
        for c in chunk_rows(env, url, FIXED)
    ]


def _reset_corpus(env: IngestEnv) -> None:
    env.db.conn.execute("TRUNCATE chunks, pages, documents")


@pytest.mark.integration
def test_ac_002_01_one_chunk_set_per_strategy_with_ids_params_and_labels(db_env: IngestEnv) -> None:
    """AC-002-01: both strategies for all types → one fixed_words and one structure_aware set per document, each
    chunk with strategy id and params, every structure_aware chunk with a non-empty section label, and fixed_words
    rows identical to a fixed_words-only run."""
    migrate_schema(db_env.db)
    docs = serve_docs(db_env, COMMITTED)
    set_strategies(db_env, [FIXED])
    assert_exit(db_env.ingest(), EXIT_OK)
    control = {url: _fixed_rows(db_env, url) for url in docs}
    assert all(control.values()), "control run: fixed_words chunks for every fixture"
    _reset_corpus(db_env)
    set_strategies(db_env, [FIXED, STRUCTURE])

    run = db_env.ingest()

    assert_exit(run, EXIT_OK)
    for url, doc in docs.items():
        chunks = db_env.chunks(url)
        sets = {(c["chunker"], _params_key(c["chunker_params"])) for c in chunks}
        assert sorted(s for s, _ in sets) == [FIXED, STRUCTURE], f"{doc.name}: chunk sets {sorted(sets)}"
        for c in chunks:
            assert c["chunker"] in (FIXED, STRUCTURE)
            assert isinstance(c["chunker_params"], dict) and c["chunker_params"], f"{doc.name}: chunk without params"
        structure = chunk_rows(db_env, url, STRUCTURE)
        assert structure[0]["chunker_params"].get("size_cap") == SIZE_CAP, "the size cap is a recorded parameter"
        unlabelled = [
            c["ordinal"] for c in structure if not (isinstance(c.get("section"), str) and c["section"].strip())
        ]
        assert not unlabelled, f"{doc.name}: structure_aware chunks without a section label: {unlabelled}"
        assert _fixed_rows(db_env, url) == control[url], f"{doc.name}: fixed_words chunks differ from the control run"


@pytest.mark.integration
def test_ac_002_01_structure_aware_for_one_type_only(db_env: IngestEnv) -> None:
    """AC-002-01: with structure_aware configured only for district reports, other types get no such chunks."""
    migrate_schema(db_env.db)
    docs = serve_docs(db_env, COMMITTED)
    set_strategies(db_env, [FIXED], {"district_report": [FIXED, STRUCTURE]})

    run = db_env.ingest()

    assert_exit(run, EXIT_OK)
    for url, doc in docs.items():
        strategies = {c["chunker"] for c in db_env.chunks(url)}
        expected = {FIXED, STRUCTURE} if doc.doc_type == "district_report" else {FIXED}
        assert strategies == expected, f"{doc.name} ({doc.doc_type}): strategies {sorted(strategies)}"


# -- AC-002-02 ----------------------------------------------------------------------------------------------------
BAD_CONFIGS = [
    pytest.param("CHUNKERS", "fixed_words,semantic_v9", None, "semantic_v9", id="unknown-strategy"),
    pytest.param(
        "CHUNKERS_BY_DOC_TYPE", "fixed_words", {"incident_memo": ["fixed_words"]}, "incident_memo", id="unknown-type"
    ),
    pytest.param(
        "CHUNKERS_BY_DOC_TYPE",
        "fixed_words",
        {"panel_report": ["fixed_words", "semantic_v9"]},
        "semantic_v9",
        id="unknown-strategy-by-type",
    ),
]


def _assert_config_error(run: CliRun, setting: str, offending: str) -> None:
    assert_exit(run, EXIT_FATAL)
    assert re.search(rf"\b{setting}\b", run.output), f"the error names the setting {setting}\n{run.describe()}"
    assert offending in run.output, f"the error names the offending value {offending!r}\n{run.describe()}"
    for strategy in (FIXED, STRUCTURE):
        assert strategy in run.output, f"the error lists the available strategy {strategy}\n{run.describe()}"
    for doc_type in DOC_TYPES:
        assert doc_type in run.output, f"the error lists the valid document type {doc_type}\n{run.describe()}"


@pytest.mark.parametrize(("setting", "chunkers", "by_type", "offending"), BAD_CONFIGS)
def test_ac_002_02_invalid_config_is_fatal_before_any_download(
    http_env: IngestEnv, setting: str, chunkers: str, by_type: dict[str, list[str]] | None, offending: str
) -> None:
    """AC-002-02: `ingest` with an unknown strategy or doc type exits fatal, no request sent, error explains it.

    No database is configured: the configuration error must come first."""
    http_env.serve_pdf("/sites/bsee.gov/files/a.pdf", b"%PDF-1.4 never downloaded")
    http_env.write_manifest([http_env.entry("/sites/bsee.gov/files/a.pdf")])
    set_strategies(http_env, chunkers.split(","), by_type)

    run = http_env.ingest()

    _assert_config_error(run, setting, offending)
    assert http_env.server.requests == [], "nothing may be requested when the configuration is invalid"


@pytest.mark.integration
@pytest.mark.parametrize(("setting", "chunkers", "by_type", "offending"), BAD_CONFIGS)
def test_ac_002_02_invalid_config_is_fatal_before_any_database_write(
    db_env: IngestEnv, setting: str, chunkers: str, by_type: dict[str, list[str]] | None, offending: str
) -> None:
    """AC-002-02: with a reachable, migrated database, `ingest` and `rechunk` write nothing and download nothing."""
    migrate_schema(db_env.db)
    docs = serve_docs(db_env, COMMITTED[:1])
    assert_exit(db_env.ingest(), EXIT_OK)  # a stored corpus that re-chunking could touch
    before = db_env.counts()
    chunks_before = db_env.db.rows("SELECT id, chunker, text FROM chunks ORDER BY id")
    db_env.server.clear_requests()
    (url,) = docs
    db_env.server.set_body(next(iter(db_env.served)), b"%PDF-1.4 a new version that must not be fetched")
    set_strategies(db_env, chunkers.split(","), by_type)

    for command in ("ingest", "rechunk"):
        run = run_cli(command)

        _assert_config_error(run, setting, offending)
        assert db_env.server.requests == [], f"{command}: nothing may be requested"
        assert db_env.counts() == before, f"{command}: rows were written"
        assert db_env.db.rows("SELECT id, chunker, text FROM chunks ORDER BY id") == chunks_before
        assert db_env.document(url) is not None
