"""AC-001-06: image-only documents are stored and reported, produce no chunks and do not count as failed."""

from __future__ import annotations

import pytest

from tests.conftest import migrate_schema
from tests.support import pdfs
from tests.support.ingest import EXIT_OK, IngestEnv, assert_exit, outcomes


def test_ac_001_06_parse_pdf_flags_image_only_pages() -> None:
    """AC-001-06: pages with no text layer are flagged image-only by the parser."""
    from offshore_rag.ingestion.pdf import parse_pdf

    parsed = parse_pdf(pdfs.image_only_pdf(3))

    assert [p.number for p in parsed.pages] == [1, 2, 3]
    assert all(p.image_only for p in parsed.pages)


@pytest.mark.integration
def test_ac_001_06_image_only_document_stored_reported_not_failed(db_env: IngestEnv) -> None:
    """AC-001-06: document and pages stored, pages flagged, zero chunks, listed as image-only, not failed."""
    migrate_schema(db_env.db)
    scan = "/sites/bsee.gov/files/reports/safety/scanned-2006.pdf"
    text = "/sites/bsee.gov/files/2024-01/text.pdf"
    scan_url = db_env.serve_pdf(scan, pdfs.image_only_pdf(2))
    text_url = db_env.serve_pdf(text, pdfs.text_pdf(2))
    db_env.write_manifest([db_env.entry(scan, "district_report"), db_env.entry(text, "district_report")])

    run = db_env.ingest()

    assert_exit(run, EXIT_OK)
    doc = db_env.document(scan_url)
    assert doc is not None, "an image-only document is still stored"
    assert doc["page_count"] == 2
    assert doc["image_only"] is True
    pages = db_env.pages(scan_url)
    assert [(n, img) for n, _, img in pages] == [(1, True), (2, True)]
    assert db_env.chunks(scan_url) == [], "no chunk may come from image-only pages"
    assert db_env.chunks(text_url), "the text document is chunked as usual"
    text_doc = db_env.document(text_url)
    assert text_doc is not None and text_doc["image_only"] is False

    report = db_env.latest_report()
    assert scan_url in report["image_only_documents"]
    assert text_url not in report["image_only_documents"]
    assert report["counts"]["image_only"] == 1
    assert report["counts"]["failed"] == 0
    assert outcomes(report)[scan_url]["status"] == "ingested"
