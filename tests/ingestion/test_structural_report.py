"""AC-002-10, AC-002-11, AC-002-12, AC-002-13: `offshore-rag chunk-report`, the structural report of chunk sets.

The plan fixes the command and the location (`data/reports/`, JSON) but not the exact JSON layout, so the report is
read leniently: the entry of a (strategy, document type) is the object that names both (as keys on its path or as
`strategy`/`chunker` and `doc_type` values) and holds a chunk count; metrics are found by key name. Shares may be
fractions (0-1) or percentages (0-100).
"""

from __future__ import annotations

import json
import re
import socket
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

from tests.conftest import migrate_schema, with_search_path
from tests.support.ingest import EXIT_FATAL, EXIT_OK, EXIT_PARTIAL, CliRun, IngestEnv, assert_exit, run_cli
from tests.support.structure import (
    COMMITTED,
    DISTRICT,
    DOC_TYPES,
    FIXED,
    SIZE_CAP,
    STRUCTURE,
    UNRECOGNIZED_DISTRICT,
    report_files,
    serve_docs,
    set_strategies,
    words,
)

pytestmark = pytest.mark.integration
STRATEGIES = (FIXED, STRUCTURE)


# -- reading the report ---------------------------------------------------------------------------------------
def _entry(report: Any, strategy: str, doc_type: str) -> dict[str, Any]:
    found: list[dict[str, Any]] = []

    def walk(node: Any, path: tuple[str, ...]) -> None:
        if isinstance(node, dict):
            names = set(path) | {
                v for k, v in node.items() if isinstance(v, str) and k in ("strategy", "chunker", "doc_type")
            }
            if strategy in names and doc_type in names and any(re.search(r"chunk", k, re.I) for k in node):
                found.append(node)
                return
            for k, v in node.items():
                walk(v, (*path, str(k)))
        elif isinstance(node, list):
            for v in node:
                walk(v, path)

    walk(report, ())
    assert len(found) == 1, f"expected one report entry for ({strategy}, {doc_type}), found {len(found)}"
    return found[0]


def _metric(entry: dict[str, Any], pattern: str, kind: type | tuple[type, ...]) -> Any:
    keys = [k for k, v in entry.items() if re.search(pattern, k, re.I) and isinstance(v, kind) and v is not True]
    assert len(keys) == 1, f"no single metric /{pattern}/ of type {kind} in {sorted(entry)}"
    return entry[keys[0]]


def _count(entry: dict[str, Any], pattern: str) -> int:
    value = _metric(entry, pattern, int)
    assert isinstance(value, int)
    return value


def _share(entry: dict[str, Any], pattern: str) -> float:
    value = _metric(entry, pattern, (int, float))
    assert 0 <= value <= 100, f"/{pattern}/ = {value} is not a share"
    return float(value)


def _assert_share(value: float, expected: float, what: str) -> None:
    assert abs(value - expected) < 1e-6 or abs(value - 100 * expected) < 1e-4, f"{what}: {value} != {expected:.6f}"


def _sizes(entry: dict[str, Any]) -> dict[str, float]:
    size = _metric(entry, r"size|words", dict)
    norm = {k.lower(): v for k, v in size.items()}
    out = {}
    for stat, aliases in {
        "min": ("min",),
        "p10": ("p10",),
        "median": ("median", "p50"),
        "p90": ("p90",),
        "max": ("max",),
    }.items():
        value = next((norm[a] for a in aliases if a in norm), None)
        assert isinstance(value, int | float), f"size distribution has no {stat}: {size}"
        out[stat] = float(value)
    return out


# -- running ----------------------------------------------------------------------------------------------------
def _ingest(env: IngestEnv, docs: list[Any]) -> dict[str, Any]:
    migrate_schema(env.db)
    served = serve_docs(env, docs)
    set_strategies(env, list(STRATEGIES))
    assert_exit(env.ingest(), EXIT_OK)
    return served


def _chunk_report(env: IngestEnv, *args: str, exit_code: int = EXIT_OK) -> tuple[CliRun, dict[str, Any], Path]:
    before = report_files(env.reports_dir)
    run = run_cli("chunk-report", *args)
    assert_exit(run, exit_code)
    new = sorted(report_files(env.reports_dir) - before)
    assert len(new) == 1, f"one new report file under {env.reports_dir}, got {new}"
    path = env.reports_dir / new[0]
    assert path.resolve().is_relative_to((env.data_dir / "reports").resolve())
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict | list), "the report is machine-readable JSON"
    return run, data, path


def _db_chunks(env: IngestEnv, strategy: str, doc_type: str) -> list[dict[str, Any]]:
    return [
        c
        for c in env.chunks()
        if c["chunker"] == strategy
        and env.db.scalar("SELECT doc_type FROM documents WHERE id = %s", (c["document_id"],)) == doc_type
    ]


def test_ac_002_10_report_file_and_summary_carry_every_metric(db_env: IngestEnv) -> None:
    """AC-002-10: a JSON file under data/reports/ and a stdout summary, per strategy and document type, with counts,
    size distribution, multi-page, page-header, checkbox-grid and boundary-crossing shares, and missing sections."""
    _ingest(db_env, [*COMMITTED, UNRECOGNIZED_DISTRICT])

    run, report, _ = _chunk_report(db_env)

    for strategy in STRATEGIES:
        for doc_type in DOC_TYPES:
            entry = _entry(report, strategy, doc_type)
            chunks = _db_chunks(db_env, strategy, doc_type)
            docs = {c["document_id"] for c in chunks}
            what = f"({strategy}, {doc_type})"
            assert _count(entry, r"^(documents|docs|n_documents|document_count|documents_count)$") == len(docs), what
            assert _count(entry, r"^(chunks|n_chunks|chunk_count|chunks_count)$") == len(chunks), what
            not_recognized = _count(entry, r"not_?recogni[sz]ed")
            if strategy == STRUCTURE:
                assert not_recognized == (1 if doc_type == "district_report" else 0), f"{what} not recognized"
            sizes = [len(words(c["text"])) for c in chunks]
            dist = _sizes(entry)
            assert (dist["min"], dist["max"]) == (min(sizes), max(sizes)), f"{what} size min/max"
            assert dist["min"] <= dist["p10"] <= dist["median"] <= dist["p90"] <= dist["max"], f"{what} {dist}"
            multi = sum(c["page_end"] > c["page_start"] for c in chunks) / len(chunks)
            _assert_share(_share(entry, r"multi.?page|span"), multi, f"{what} multi-page share")
            _share(entry, r"header")
            _share(entry, r"cross|boundar")
            missing = _metric(entry, r"missing", (list, dict))
            assert isinstance(missing, list | dict), f"{what} missing fields/sections"
            if doc_type == "district_report":
                _share(entry, r"grid|checkbox")
    out = run.stdout
    for name in (*STRATEGIES, *DOC_TYPES):
        assert name in out, f"the summary names {name}:\n{out}"
    for pattern in (r"header", r"grid|checkbox", r"cross|boundar", r"missing", r"median|p50", r"p10", r"p90"):
        assert re.search(pattern, out, re.I), f"the summary shows /{pattern}/:\n{out}"
    assert re.search(r"(?i)not[ _-]?recogni[sz]ed", out), f"the summary shows structure-not-recognized counts:\n{out}"


def test_ac_002_11_structure_aware_has_no_noise_and_fixed_words_shows_it(db_env: IngestEnv) -> None:
    """AC-002-11: on the committed fixtures, structure_aware has zero page-header, grid and crossing shares, nothing
    missing and chunks of at most 250 words; fixed_words on the district fixture has header and crossing shares > 0."""
    _ingest(db_env, list(COMMITTED))

    _, report, _ = _chunk_report(db_env)

    for doc_type in DOC_TYPES:
        entry = _entry(report, STRUCTURE, doc_type)
        what = f"(structure_aware, {doc_type})"
        assert _share(entry, r"header") == 0, f"{what} page-header share"
        assert _share(entry, r"cross|boundar") == 0, f"{what} boundary-crossing share"
        assert not _metric(entry, r"missing", (list, dict)), f"{what} missing fields or sections"
        assert _sizes(entry)["max"] <= SIZE_CAP, f"{what} max chunk size"
        assert _count(entry, r"not_?recogni[sz]ed") == 0, f"{what}: every committed fixture is recognized"
    assert _share(_entry(report, STRUCTURE, "district_report"), r"grid|checkbox") == 0, "structure_aware grid share"
    fixed = _entry(report, FIXED, "district_report")
    assert _share(fixed, r"header") > 0, "fixed_words district chunks carry the page header"
    assert _share(fixed, r"cross|boundar") > 0, "fixed_words district chunks cross field boundaries"


def test_ac_002_10_explicit_strategy_limits_the_report(db_env: IngestEnv) -> None:
    """AC-002-10: `--strategy structure_aware` reports that strategy per document type."""
    _ingest(db_env, list(COMMITTED))

    _, report, _ = _chunk_report(db_env, "--strategy", STRUCTURE)

    for doc_type in DOC_TYPES:
        assert _count(_entry(report, STRUCTURE, doc_type), r"^(chunks|n_chunks|chunk_count|chunks_count)$") > 0


# -- AC-002-13 ----------------------------------------------------------------------------------------------------
def test_ac_002_13_stale_chunk_set_is_listed_left_out_and_exits_3(db_env: IngestEnv) -> None:
    """AC-002-13: a structure_aware chunk set that can no longer be located in the stored pages does not abort the
    report: the file is written and the summary printed, that set is left out of the metrics, the report lists it
    under `stale_chunk_sets` with source URL, doc type, strategy and the ordinal of the first chunk not located, the
    summary points to `offshore-rag rechunk`, and the command exits 3."""
    served = _ingest(db_env, [*COMMITTED, UNRECOGNIZED_DISTRICT])
    stale_url = next(url for url, doc in served.items() if doc is DISTRICT)
    other_url = next(url for url, doc in served.items() if doc is UNRECOGNIZED_DISTRICT)
    stale_set = sorted((c for c in db_env.chunks(stale_url) if c["chunker"] == STRUCTURE), key=lambda c: c["ordinal"])
    assert len(stale_set) >= 3, "the district fixture yields several structure_aware chunks"
    # Alter a chunk in the middle of the set, as older rules would have produced text the current detection does not
    # keep: the chunks before it are still located, so it is the first one that is not.
    target = stale_set[len(stale_set) // 2]
    marker = "stale" + uuid.uuid4().hex
    db_env.db.conn.execute(
        "UPDATE chunks SET text = %s WHERE document_id = %s AND chunker = %s AND ordinal = %s",
        (
            f"{marker} words that were never on any stored page {marker}",
            target["document_id"],
            STRUCTURE,
            target["ordinal"],
        ),
    )
    assert all(marker not in t for _, t, _ in db_env.pages(stale_url)), "the altered text is not in the stored pages"

    run, report, _ = _chunk_report(db_env, exit_code=EXIT_PARTIAL)

    # Listed under stale chunk sets, and only that set.
    assert isinstance(report, dict), "the report is a JSON object with a top-level stale_chunk_sets list"
    stale = report.get("stale_chunk_sets")
    assert isinstance(stale, list), f"top-level stale_chunk_sets list missing: keys {sorted(report)}"
    assert len(stale) == 1, f"exactly the altered (document, strategy) set is stale: {stale}"
    item = stale[0]
    assert item.get("source_url") == stale_url, item
    assert item.get("strategy") == STRUCTURE, item
    assert item.get("doc_type") == "district_report", item
    assert item.get("ordinal") == target["ordinal"], f"first chunk not located is {target['ordinal']}: {item}"

    # The stale set is left out of the metrics of its entry; the other district document still counts.
    entry = _entry(report, STRUCTURE, "district_report")
    kept = [c for c in db_env.chunks(other_url) if c["chunker"] == STRUCTURE]
    assert kept, "the unrecognized district fixture still has structure_aware chunks"
    assert _count(entry, r"^(documents|docs|n_documents|document_count|documents_count)$") == 1, "stale doc left out"
    assert _count(entry, r"^(chunks|n_chunks|chunk_count|chunks_count)$") == len(kept), "stale chunks left out"
    assert _count(entry, r"not_?recogni[sz]ed") == 1, "only the remaining (unrecognized) district document counts"
    sizes = [len(words(c["text"])) for c in kept]
    dist = _sizes(entry)
    assert (dist["min"], dist["max"]) == (min(sizes), max(sizes)), "size distribution of the remaining set only"
    multi = sum(c["page_end"] > c["page_start"] for c in kept) / len(kept)
    _assert_share(_share(entry, r"multi.?page|span"), multi, "multi-page share of the remaining set only")
    # Sets that are not stale are untouched: fixed_words still counts both district documents.
    fixed = _entry(report, FIXED, "district_report")
    assert _count(fixed, r"^(documents|docs|n_documents|document_count|documents_count)$") == 2
    assert _count(fixed, r"^(chunks|n_chunks|chunk_count|chunks_count)$") == len(
        _db_chunks(db_env, FIXED, "district_report")
    )
    for doc_type in ("safety_alert", "panel_report"):
        assert _count(_entry(report, STRUCTURE, doc_type), r"^(chunks|n_chunks|chunk_count|chunks_count)$") == len(
            _db_chunks(db_env, STRUCTURE, doc_type)
        ), f"(structure_aware, {doc_type}) is not stale and keeps all its chunks"

    # The summary is printed, lists the stale set and tells the operator to re-chunk.
    out = run.stdout
    for name in (*STRATEGIES, *DOC_TYPES):
        assert name in out, f"the summary is still printed and names {name}:\n{out}"
    assert re.search(r"(?i)stale", out), f"the summary lists stale chunk sets:\n{out}"
    assert stale_url in out, f"the summary names the stale document:\n{out}"
    assert "offshore-rag rechunk" in out, f"the summary tells the operator to run re-chunking:\n{out}"


# -- AC-002-12 ----------------------------------------------------------------------------------------------------
def _assert_no_chunks_error(env: IngestEnv, before: set[str]) -> None:
    run = run_cli("chunk-report", "--strategy", STRUCTURE)
    unhandled = run.exception is not None and not isinstance(run.exception, SystemExit)
    assert not unhandled, f"unhandled exception instead of a clean exit:\n{run.describe()}"
    assert run.exit_code != EXIT_OK, f"a strategy with no chunks must fail\n{run.describe()}"
    assert STRUCTURE in run.output, f"the error names the strategy with no chunks\n{run.describe()}"
    assert report_files(env.reports_dir) == before, "no report file may be written"


def test_ac_002_12_empty_corpus_report_fails_and_writes_nothing(db_env: IngestEnv) -> None:
    """AC-002-12: an empty corpus → chunk-report exits non-zero, names the strategy, writes no file."""
    migrate_schema(db_env.db)

    _assert_no_chunks_error(db_env, report_files(db_env.reports_dir))


def test_ac_002_12_strategy_never_run_report_fails_and_writes_nothing(db_env: IngestEnv) -> None:
    """AC-002-12: a corpus chunked with fixed_words only → chunk-report for structure_aware fails, no file."""
    migrate_schema(db_env.db)
    serve_docs(db_env, COMMITTED[:1])
    set_strategies(db_env, [FIXED])
    assert_exit(db_env.ingest(), EXIT_OK)

    _assert_no_chunks_error(db_env, report_files(db_env.reports_dir))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_ac_002_12_report_with_unreachable_database_is_fatal_without_password(http_env: IngestEnv) -> None:
    """AC-002-12: Postgres unreachable → chunk-report exits 1 naming host, port and database, never the password."""
    port = _free_port()
    password = "Sup3r-S3cret-pw-" + uuid.uuid4().hex[:8]
    http_env.setenv("DATABASE_URL", f"postgresql://report_user:{password}@127.0.0.1:{port}/corpus_offline")

    run = run_cli("chunk-report")

    assert_exit(run, EXIT_FATAL)
    assert "127.0.0.1" in run.output and str(port) in run.output and "corpus_offline" in run.output, run.describe()
    assert password not in run.output, "the password must never be printed"
    assert report_files(http_env.reports_dir) == set(), "no report file may be written"


def test_ac_002_12_report_with_missing_schema_is_fatal_without_password(
    db_env: IngestEnv, limited_role: tuple[str, str]
) -> None:
    """AC-002-12: reachable Postgres without migrations → chunk-report exits 1, names the connection and the schema."""
    role, password = limited_role
    params = db_env.db.params
    host, port, dbname = params.get("host", "localhost"), params.get("port", "5432"), params["dbname"]
    url = with_search_path(f"postgresql://{role}:{quote(password, safe='')}@{host}:{port}/{dbname}", db_env.db.schema)
    db_env.setenv("DATABASE_URL", url)

    run = run_cli("chunk-report")

    assert_exit(run, EXIT_FATAL)
    assert host in run.output and str(port) in run.output and dbname in run.output, run.describe()
    assert password not in run.output, "the password must never be printed"
    assert re.search(r"schema|migrat", run.output, re.IGNORECASE), "the error says the schema is missing"
    assert report_files(db_env.reports_dir) == set(), "no report file may be written"
