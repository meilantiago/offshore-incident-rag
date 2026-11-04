"""AC-001-04: ingestion downloads politely (User-Agent, rate limit, bounded retries, no retry on 404)."""

from __future__ import annotations

import itertools
import re

import pytest

from tests.conftest import migrate_schema
from tests.support import pdfs
from tests.support.ingest import (
    EXIT_OK,
    EXIT_PARTIAL,
    REPO_URL,
    IngestEnv,
    assert_exit,
    failures,
    outcomes,
)

pytestmark = pytest.mark.integration

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+|@")


def _serve(env: IngestEnv, names: list[str]) -> list[str]:
    paths = [f"/sites/bsee.gov/files/{n}.pdf" for n in names]
    for i, p in enumerate(paths, start=1):
        env.serve_pdf(p, pdfs.text_pdf(1 + i % 2, tag=f"DOC{i}"))
    env.write_manifest([env.entry(p) for p in paths])
    return paths


def test_ac_001_04_default_user_agent_names_project_and_repo_without_email(db_env: IngestEnv) -> None:
    """AC-001-04: with no override, every request carries the project User-Agent with the repo URL, no e-mail."""
    migrate_schema(db_env.db)
    db_env.monkeypatch.delenv("HTTP_USER_AGENT", raising=False)
    _serve(db_env, ["a", "b"])

    assert_exit(db_env.ingest(), EXIT_OK)

    agents = list(db_env.server.iter_user_agents())
    assert agents, "ingest made no request"
    assert len(set(agents)) == 1, f"every request must carry the same User-Agent: {set(agents)}"
    ua = agents[0]
    assert ua is not None
    assert "offshore-incident-rag" in ua
    assert REPO_URL in ua
    assert not EMAIL_RE.search(ua), f"User-Agent must not contain an e-mail address: {ua!r}"


def test_ac_001_04_configured_user_agent_on_every_request(db_env: IngestEnv) -> None:
    """AC-001-04: every request (robots.txt and PDFs) carries the configured User-Agent."""
    migrate_schema(db_env.db)
    configured = f"offshore-incident-rag-ci/9.9 (+{REPO_URL})"
    db_env.setenv("HTTP_USER_AGENT", configured)
    paths = _serve(db_env, ["a", "b", "c"])

    assert_exit(db_env.ingest(), EXIT_OK)

    requests = db_env.server.requests
    for p in paths:
        assert db_env.server.requests_for(p), f"{p} was never requested"
    assert [r.header("user-agent") for r in requests] == [configured] * len(requests)


def test_ac_001_04_requests_never_exceed_the_configured_rate(db_env: IngestEnv) -> None:
    """AC-001-04: the interval between consecutive requests is never shorter than 1 / HTTP_RATE_PER_SECOND."""
    migrate_schema(db_env.db)
    rate = 4.0
    db_env.setenv("HTTP_RATE_PER_SECOND", rate)
    _serve(db_env, ["a", "b", "c", "d", "e"])

    assert_exit(db_env.ingest(), EXIT_OK)

    times = [r.time for r in db_env.server.requests]
    assert len(times) >= 5
    gaps = [b - a for a, b in itertools.pairwise(times)]
    # 5% tolerance for timer resolution between the client's clock and the server's
    assert min(gaps) >= 0.95 / rate, f"requests closer than 1/rate: {[round(g, 3) for g in gaps]}"


def test_ac_001_04_transient_errors_are_retried_up_to_the_limit(db_env: IngestEnv) -> None:
    """AC-001-04: 429, 5xx and timeouts are retried up to HTTP_MAX_RETRIES, then succeed or are recorded failed."""
    migrate_schema(db_env.db)
    db_env.setenv("HTTP_MAX_RETRIES", 2)
    db_env.setenv("HTTP_TIMEOUT_SECONDS", 1)
    server = db_env.server
    p503, p429, ptimeout, pgiveup = (
        "/sites/bsee.gov/files/flaky-503.pdf",
        "/sites/bsee.gov/files/flaky-429.pdf",
        "/sites/bsee.gov/files/slow.pdf",
        "/sites/bsee.gov/files/always-503.pdf",
    )
    for i, p in enumerate((p503, p429, ptimeout, pgiveup), start=1):
        db_env.serve_pdf(p, pdfs.text_pdf(1, tag=f"DOC{i}"))
    server.fail(p503, 2, 503)  # two failures, the third attempt (second retry) succeeds
    server.fail(p429, 1, 429)
    server.fail(ptimeout, 1, None)  # the server stalls past HTTP_TIMEOUT_SECONDS once
    server.fail(pgiveup, 10, 503)  # more failures than the retry limit
    db_env.write_manifest([db_env.entry(p) for p in (p503, p429, ptimeout, pgiveup)])

    run = db_env.ingest()

    assert_exit(run, EXIT_PARTIAL)
    assert len(server.requests_for(p503)) == 3
    assert len(server.requests_for(p429)) == 2
    assert len(server.requests_for(ptimeout)) == 2
    assert len(server.requests_for(pgiveup)) == 3, "1 attempt + HTTP_MAX_RETRIES retries, then give up"
    for p in (p503, p429, ptimeout):
        assert db_env.document(server.url(p)) is not None, f"{p} should succeed after retrying"
    assert db_env.document(server.url(pgiveup)) is None
    report = db_env.latest_report()
    assert outcomes(report)[server.url(pgiveup)]["status"] == "failed"
    assert failures(report)[server.url(pgiveup)]["stage"] == "download"


def test_ac_001_04_http_404_is_failed_without_retry(db_env: IngestEnv) -> None:
    """AC-001-04: an HTTP 404 is recorded as failed and requested exactly once."""
    migrate_schema(db_env.db)
    missing = "/sites/bsee.gov/files/removed.pdf"
    ok = "/sites/bsee.gov/files/ok.pdf"
    db_env.serve_pdf(ok, pdfs.text_pdf(1))
    db_env.write_manifest([db_env.entry(missing), db_env.entry(ok)])

    run = db_env.ingest()

    assert_exit(run, EXIT_PARTIAL)
    assert len(db_env.server.requests_for(missing)) == 1
    failure = failures(db_env.latest_report())[db_env.server.url(missing)]
    assert failure["stage"] == "download"
    assert "404" in str(failure["reason"])
