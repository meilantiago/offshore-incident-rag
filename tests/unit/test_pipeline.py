"""`run_ingest`: outcome per document, change detection and raw files (T11)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest

from offshore_rag.ingestion.chunking import FixedWordChunker
from offshore_rag.ingestion.http import PoliteClient
from offshore_rag.ingestion.manifest import ManifestEntry
from offshore_rag.ingestion.pipeline import run_ingest
from offshore_rag.ingestion.report import IngestionReport
from offshore_rag.ingestion.store import CorpusStore
from tests.conftest import PgSchema, migrate_schema
from tests.support import pdfs
from tests.support.http_server import FixtureServer

pytestmark = pytest.mark.integration


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Rig:
    server: FixtureServer
    pg: PgSchema
    data_dir: Path
    conn: psycopg.Connection[object]

    def entry(self, path: str, sha: str | None = None) -> ManifestEntry:
        return ManifestEntry("safety_alert", self.server.url(path), self.server.url("/listing"), "", sha)

    def run(self, *entries: ManifestEntry) -> IngestionReport:
        with PoliteClient(user_agent="t/1", rate_per_second=100, max_retries=0, timeout=5) as client:
            return run_ingest(
                entries=list(entries),
                client=client,
                store=CorpusStore(self.conn),
                chunkers=[FixedWordChunker(size=50, overlap=10)],
                data_dir=self.data_dir,
            )

    def statuses(self, report: IngestionReport) -> list[tuple[str, str | None, str | None]]:
        return [(d.status, d.stage, d.reason) for d in report.documents]


@pytest.fixture
def rig(postgres: PgSchema, tmp_path: Path) -> Iterator[Rig]:
    migrate_schema(postgres)
    with FixtureServer() as server, psycopg.connect(postgres.url, autocommit=True) as conn:
        yield Rig(server, postgres, tmp_path / "data", conn)


def test_new_document_is_ingested_with_content_addressed_raw_file(rig: Rig) -> None:
    data = pdfs.text_pdf(2)
    rig.server.add("/a.pdf", data)
    report = rig.run(rig.entry("/a.pdf"))
    assert rig.statuses(report) == [("ingested", None, None)]
    raw_path = rig.pg.scalar("SELECT raw_path FROM documents")
    assert raw_path == f"raw/{_sha(data)}.pdf"
    assert (rig.data_dir / raw_path).read_bytes() == data
    assert not [p for p in (rig.data_dir / "raw").iterdir() if p.suffix != ".pdf"], "no temp file left behind"
    assert report.documents[0].pages == 2 and report.documents[0].chunks > 0


def test_304_is_skipped_unchanged(rig: Rig) -> None:
    rig.server.add("/a.pdf", pdfs.text_pdf(2), etag='"v1"')
    rig.run(rig.entry("/a.pdf"))
    rig.server.clear_requests()
    report = rig.run(rig.entry("/a.pdf"))
    assert rig.statuses(report) == [("skipped_unchanged", None, None)]
    [req] = rig.server.requests_for("/a.pdf")
    assert req.header("if-none-match") == '"v1"' and req.status == 304


def test_same_hash_200_is_skipped_unchanged(rig: Rig) -> None:
    rig.server.add("/a.pdf", pdfs.text_pdf(2))
    rig.run(rig.entry("/a.pdf"))
    report = rig.run(rig.entry("/a.pdf"))
    assert rig.statuses(report) == [("skipped_unchanged", None, None)]


def test_changed_bytes_are_replaced(rig: Rig) -> None:
    rig.server.add("/a.pdf", pdfs.text_pdf(2, tag="A"))
    rig.run(rig.entry("/a.pdf"))
    new = pdfs.text_pdf(3, tag="B")
    rig.server.set_body("/a.pdf", new)
    report = rig.run(rig.entry("/a.pdf"))
    assert rig.statuses(report) == [("replaced", None, None)]
    assert rig.pg.scalar("SELECT sha256 FROM documents") == _sha(new)
    assert rig.pg.scalar("SELECT count(*) FROM pages") == 3


def test_declared_hash_mismatch_fails_and_keeps_no_raw_file(rig: Rig) -> None:
    rig.server.add("/a.pdf", pdfs.text_pdf(2))
    report = rig.run(rig.entry("/a.pdf", sha="0" * 64))
    assert rig.statuses(report) == [("failed", "download", "hash_mismatch")]
    assert rig.pg.scalar("SELECT count(*) FROM documents") == 0
    raw = rig.data_dir / "raw"
    assert not raw.exists() or not any(raw.iterdir())


def test_404_on_stored_document_keeps_it(rig: Rig) -> None:
    rig.server.add("/a.pdf", pdfs.text_pdf(2))
    rig.run(rig.entry("/a.pdf"))
    rig.server.add("/a.pdf", b"", status=404)
    report = rig.run(rig.entry("/a.pdf"))
    [outcome] = report.documents
    assert (outcome.status, outcome.stage) == ("failed", "download")
    assert outcome.reason is not None and "404" in outcome.reason
    assert rig.pg.scalar("SELECT count(*) FROM documents") == 1
    assert rig.pg.scalar("SELECT count(*) FROM pages") == 2


def test_corrupt_pdf_fails_at_parse_and_others_continue(rig: Rig) -> None:
    rig.server.add("/bad.pdf", pdfs.corrupt_pdf())
    rig.server.add("/ok.pdf", pdfs.text_pdf(1))
    report = rig.run(rig.entry("/bad.pdf"), rig.entry("/ok.pdf"))
    assert [(d.status, d.stage) for d in report.documents] == [("failed", "parse"), ("ingested", None)]
    assert report.has_failures


def test_robots_disallowed_url_fails_without_download(rig: Rig) -> None:
    rig.server.add("/admin/a.pdf", pdfs.text_pdf(1))
    report = rig.run(rig.entry("/admin/a.pdf"))
    assert rig.statuses(report) == [("failed", "download", "robots_disallowed")]
    assert rig.server.requests_for("/admin/a.pdf") == []


def test_report_carries_network_counters_and_durations(rig: Rig) -> None:
    data = pdfs.text_pdf(2)
    rig.server.add("/a.pdf", data)
    report = rig.run(rig.entry("/a.pdf"))
    assert report.requests == 2  # robots.txt + the PDF
    assert report.bytes_downloaded >= len(data)
    assert set(report.durations_ms) == {"total", "download", "parse", "chunk", "store"}
    assert report.durations_ms["total"] >= report.durations_ms["store"]


def test_ac_001_10_unparseable_url_fails_only_its_document(rig: Rig) -> None:
    """AC-001-10: a URL that makes urlsplit raise is a download failure; the others are still ingested."""
    rig.server.add("/ok.pdf", pdfs.text_pdf(1))
    bad = ManifestEntry("safety_alert", "http://[bad/a.pdf", rig.server.url("/listing"), "", None)
    report = rig.run(bad, rig.entry("/ok.pdf"))
    assert [(d.status, d.stage, d.reason) for d in report.documents] == [
        ("failed", "download", "invalid_url"),
        ("ingested", None, None),
    ]
    assert report.has_failures


@pytest.mark.parametrize("bad_url", ["http://host:abc/a.pdf", "http://host:99999/a.pdf"])
def test_ac_001_10_invalid_port_fails_only_its_document(rig: Rig, bad_url: str) -> None:
    """AC-001-10: an invalid port is a download failure `invalid_url`; the others are still ingested."""
    rig.server.add("/ok.pdf", pdfs.text_pdf(1))
    bad = ManifestEntry("safety_alert", bad_url, rig.server.url("/listing"), "", None)
    report = rig.run(bad, rig.entry("/ok.pdf"))
    assert rig.statuses(report) == [("failed", "download", "invalid_url"), ("ingested", None, None)]
    assert report.has_failures


def test_ac_001_10_malformed_redirect_fails_only_its_document(rig: Rig) -> None:
    """AC-001-10: a redirect with a malformed Location is a download failure `invalid_redirect`."""
    rig.server.add("/ok.pdf", pdfs.text_pdf(1))
    rig.server.redirect("/moved.pdf", "http://[bad/x.pdf", 302)
    report = rig.run(rig.entry("/moved.pdf"), rig.entry("/ok.pdf"))
    assert rig.statuses(report) == [("failed", "download", "invalid_redirect"), ("ingested", None, None)]
    assert report.has_failures
