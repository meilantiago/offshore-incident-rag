"""AC-001-03: every ingested document keeps its provenance, and its raw file matches the stored hash."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

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
    sha256,
)

pytestmark = pytest.mark.integration


def _raw_file(env: IngestEnv, raw_path: str) -> Path:
    p = Path(raw_path)
    return p if p.is_absolute() else env.data_dir / p


def test_ac_001_03_documents_stored_with_provenance_and_raw_file(db_env: IngestEnv) -> None:
    """AC-001-03: source URL, type, UTC retrieval time and sha256 stored; raw file under data/ has that hash."""
    migrate_schema(db_env.db)
    files = {
        "/sites/bsee.gov/files/2023-10/BSEE%20Safety%20Alert%20469.pdf": ("safety_alert", REAL_ALERT_PDF.read_bytes()),
        "/sites/bsee.gov/files/2024-08/panel.pdf": ("panel_report", pdfs.text_pdf(3)),
        "/sites/bsee.gov/files/reports/safety/district.pdf": ("district_report", pdfs.text_pdf(2, tag="DISTRICT")),
    }
    entries = []
    for path, (doc_type, data) in files.items():
        db_env.serve_pdf(path, data)
        listing = f"/listing/{doc_type}"
        # the panel entry declares its correct hash: a matching declared hash is accepted
        declared = sha256(data) if doc_type == "panel_report" else None
        entries.append(db_env.entry(path, doc_type, sha=declared, listing=listing))
    db_env.write_manifest(entries)

    before = datetime.now(UTC)
    run = db_env.ingest()
    after = datetime.now(UTC)

    assert_exit(run, EXIT_OK)
    assert db_env.column_type("documents", "retrieved_at") == "timestamp with time zone"
    for path, (doc_type, data) in files.items():
        url = db_env.server.url(path)
        doc = db_env.document(url)
        assert doc is not None, f"{url} not stored"
        assert doc["doc_type"] == doc_type
        assert doc["listing_url"] == db_env.server.url(f"/listing/{doc_type}")
        assert doc["sha256"] == sha256(data)
        retrieved = doc["retrieved_at"]
        assert retrieved.tzinfo is not None, "retrieved_at must be an aware (UTC) timestamp"
        assert before <= retrieved.astimezone(UTC) <= after
        raw = _raw_file(db_env, doc["raw_path"])
        assert raw.is_file(), f"raw file {raw} missing"
        assert raw.resolve().is_relative_to(db_env.data_dir.resolve()), "raw files live under DATA_DIR"
        assert sha256(raw.read_bytes()) == doc["sha256"]


def test_ac_001_03_declared_hash_mismatch_fails_and_stores_nothing(db_env: IngestEnv) -> None:
    """AC-001-03: a declared sha256 that does not match → failed with reason hash_mismatch, nothing stored."""
    migrate_schema(db_env.db)
    bad_data = pdfs.text_pdf(2, tag="MISMATCH")
    good_data = pdfs.text_pdf(2)
    bad_url = db_env.serve_pdf("/sites/bsee.gov/files/bad.pdf", bad_data)
    good_url = db_env.serve_pdf("/sites/bsee.gov/files/good.pdf", good_data)
    db_env.write_manifest(
        [
            db_env.entry("/sites/bsee.gov/files/bad.pdf", sha="0" * 64),
            db_env.entry("/sites/bsee.gov/files/good.pdf"),
        ]
    )

    run = db_env.ingest()

    assert_exit(run, EXIT_PARTIAL)
    report = db_env.latest_report()
    assert failures(report)[bad_url]["reason"] == "hash_mismatch"
    assert db_env.document(bad_url) is None
    assert db_env.scalar("SELECT count(*) FROM documents WHERE source_url = %s", (bad_url,)) == 0
    assert db_env.document(good_url) is not None, "the other document is still ingested"
    bad_hash = sha256(bad_data)
    stored_raw = [p for p in db_env.data_dir.rglob("*") if p.is_file() and sha256(p.read_bytes()) == bad_hash]
    assert stored_raw == [], f"the mismatching file must not be stored: {stored_raw}"
