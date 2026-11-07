"""AC-001-10: one broken document does not abort the run; failures are reported with stage and reason."""

from __future__ import annotations

import pytest

from tests.conftest import migrate_schema
from tests.support import pdfs
from tests.support.ingest import (
    EXIT_FATAL,
    EXIT_OK,
    EXIT_PARTIAL,
    REAL_ALERT_PDF,
    IngestEnv,
    assert_exit,
    failures,
    outcomes,
)

pytestmark = pytest.mark.integration


def test_ac_001_10_corrupt_pdf_and_404_do_not_stop_valid_documents(db_env: IngestEnv) -> None:
    """AC-001-10: valid documents fully ingested; corrupt (parse) and 404 (download) failures listed; exit 3."""
    migrate_schema(db_env.db)
    valid = {
        "/sites/bsee.gov/files/a.pdf": pdfs.text_pdf(3),
        "/sites/bsee.gov/files/2023-10/469.pdf": REAL_ALERT_PDF.read_bytes(),
        "/sites/bsee.gov/files/z.pdf": pdfs.text_pdf(2, tag="LAST"),
    }
    for path, data in valid.items():
        db_env.serve_pdf(path, data)
    corrupt_url = db_env.serve_pdf("/sites/bsee.gov/files/m-corrupt.pdf", pdfs.corrupt_pdf())
    missing_path = "/sites/bsee.gov/files/n-missing.pdf"
    missing_url = db_env.server.url(missing_path)
    db_env.write_manifest(
        [db_env.entry(p) for p in valid]
        + [db_env.entry("/sites/bsee.gov/files/m-corrupt.pdf"), db_env.entry(missing_path)]
    )

    run = db_env.ingest()

    assert_exit(run, EXIT_PARTIAL)
    assert EXIT_PARTIAL not in (EXIT_OK, EXIT_FATAL)
    expected_pages = {
        "/sites/bsee.gov/files/a.pdf": 3,
        "/sites/bsee.gov/files/2023-10/469.pdf": 3,
        "/sites/bsee.gov/files/z.pdf": 2,
    }
    for path, n in expected_pages.items():
        url = db_env.server.url(path)
        doc = db_env.document(url)
        assert doc is not None, f"valid document {url} not ingested"
        assert doc["page_count"] == n
        assert len(db_env.pages(url)) == n
        assert db_env.chunks(url), f"valid document {url} has no chunks"
    assert db_env.document(corrupt_url) is None
    assert db_env.document(missing_url) is None

    report = db_env.latest_report()
    fails = failures(report)
    assert set(fails) == {corrupt_url, missing_url}
    assert fails[corrupt_url]["stage"] == "parse"
    assert fails[corrupt_url]["reason"], "a failure needs a reason"
    assert fails[missing_url]["stage"] == "download"
    assert "404" in str(fails[missing_url]["reason"])
    statuses = {u: o["status"] for u, o in outcomes(report).items()}
    assert statuses[corrupt_url] == statuses[missing_url] == "failed"
    assert report["counts"]["failed"] == 2
    assert report["counts"]["ingested"] == 3
