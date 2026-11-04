"""AC-001-08 and AC-001-09: re-running ingest skips unchanged documents and replaces changed ones atomically."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.conftest import migrate_schema
from tests.support import pdfs
from tests.support.ingest import (
    EXIT_OK,
    EXIT_PARTIAL,
    REAL_ALERT_PDF,
    IngestEnv,
    assert_exit,
    failures,
    outcomes,
    sha256,
)

pytestmark = pytest.mark.integration

PATHS = (
    "/sites/bsee.gov/files/a.pdf",
    "/sites/bsee.gov/files/b.pdf",
    "/sites/bsee.gov/files/2023-10/469.pdf",
)


def _corpus(env: IngestEnv, *, etags: bool) -> list[str]:
    datas = [pdfs.text_pdf(3, tag="A"), pdfs.text_pdf(2, tag="B"), REAL_ALERT_PDF.read_bytes()]
    urls = []
    for path, data in zip(PATHS, datas, strict=True):
        urls.append(env.serve_pdf(path, data, etag=f'"{sha256(data)[:16]}"' if etags else None))
    env.write_manifest([env.entry(p) for p in PATHS])
    return urls


def _assert_unchanged_rerun(env: IngestEnv, urls: list[str]) -> None:
    assert_exit(env.ingest(), EXIT_OK)
    before = env.counts()
    snapshots = {u: env.snapshot(u) for u in urls}
    env.server.clear_requests()

    assert_exit(env.ingest(), EXIT_OK)

    report = env.latest_report()
    assert {u: o["status"] for u, o in outcomes(report).items()} == dict.fromkeys(urls, "skipped_unchanged")
    assert report["counts"]["skipped_unchanged"] == len(urls)
    assert env.counts() == before, "document, page and chunk row counts must not change"
    for u in urls:
        assert env.scalar("SELECT count(*) FROM documents WHERE source_url = %s", (u,)) == 1
        after = env.snapshot(u)
        assert after["pages"] == snapshots[u]["pages"]
        assert after["chunks"] == snapshots[u]["chunks"]


def test_ac_001_08_unchanged_same_hash_is_skipped(db_env: IngestEnv) -> None:
    """AC-001-08: second run, server sends the same bytes (200, no validators) → all skipped_unchanged."""
    migrate_schema(db_env.db)
    urls = _corpus(db_env, etags=False)

    _assert_unchanged_rerun(db_env, urls)


def test_ac_001_08_unchanged_not_modified_is_skipped(db_env: IngestEnv) -> None:
    """AC-001-08: second run, server answers 304 to the conditional request → all skipped_unchanged."""
    migrate_schema(db_env.db)
    urls = _corpus(db_env, etags=True)

    _assert_unchanged_rerun(db_env, urls)

    for path in PATHS:
        [req] = db_env.server.requests_for(path)
        assert req.header("if-none-match"), f"{path}: the stored ETag must be sent on re-download"
        assert req.status == 304


def test_ac_001_09_changed_document_is_replaced(db_env: IngestEnv) -> None:
    """AC-001-09: new bytes at the same URL → one row, new sha256 and timestamp, old pages/chunks replaced."""
    migrate_schema(db_env.db)
    path = "/sites/bsee.gov/files/changing.pdf"
    other = "/sites/bsee.gov/files/stable.pdf"
    old, new = pdfs.text_pdf(3, tag="VERSION-A"), pdfs.text_pdf(5, tag="VERSION-B")
    url = db_env.serve_pdf(path, old)
    stable_url = db_env.serve_pdf(other, pdfs.text_pdf(2))
    db_env.write_manifest([db_env.entry(path), db_env.entry(other)])
    assert_exit(db_env.ingest(), EXIT_OK)
    first = db_env.snapshot(url)
    assert first["document"] is not None
    old_chunk_ids = {c["id"] for c in first["chunks"]}

    db_env.server.set_body(path, new)
    started = datetime.now(UTC)
    assert_exit(db_env.ingest(), EXIT_OK)

    report = db_env.latest_report()
    assert outcomes(report)[url]["status"] == "replaced"
    assert outcomes(report)[stable_url]["status"] == "skipped_unchanged"
    assert report["counts"]["replaced"] == 1
    assert db_env.scalar("SELECT count(*) FROM documents WHERE source_url = %s", (url,)) == 1
    doc = db_env.document(url)
    assert doc is not None
    assert doc["sha256"] == sha256(new)
    assert doc["retrieved_at"].astimezone(UTC) >= started
    assert doc["page_count"] == 5
    pages = db_env.pages(url)
    assert [n for n, _, _ in pages] == [1, 2, 3, 4, 5]
    assert all("VERSION-B" in t and "VERSION-A" not in t for _, t, _ in pages)
    chunks = db_env.chunks(url)
    assert chunks and all("VERSION-A" not in c["text"] for c in chunks)
    assert not old_chunk_ids & {c["id"] for c in chunks}, "old chunks must be gone"
    assert db_env.scalar("SELECT count(*) FROM pages WHERE document_id <> ALL(SELECT id FROM documents)") == 0


def test_ac_001_09_failed_new_version_keeps_previous_version(db_env: IngestEnv) -> None:
    """AC-001-09: if the new version fails (corrupt PDF), the stored version stays unchanged and it is failed."""
    migrate_schema(db_env.db)
    path = "/sites/bsee.gov/files/will-break.pdf"
    url = db_env.serve_pdf(path, pdfs.text_pdf(4, tag="VERSION-A"))
    db_env.write_manifest([db_env.entry(path)])
    assert_exit(db_env.ingest(), EXIT_OK)
    before = db_env.snapshot(url)
    assert before["document"] is not None and before["chunks"]

    db_env.server.set_body(path, pdfs.corrupt_pdf())
    run = db_env.ingest()

    assert_exit(run, EXIT_PARTIAL)
    report = db_env.latest_report()
    assert outcomes(report)[url]["status"] == "failed"
    assert failures(report)[url]["stage"] == "parse"
    assert db_env.snapshot(url) == before, "the previous version must stay in the database unchanged"
