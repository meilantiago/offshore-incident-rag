"""Helpers for the corpus-ingestion acceptance tests (spec 001); fixtures live in tests/ingestion/conftest.py.

The CLI is exercised in-process through `typer.testing.CliRunner` on `offshore_rag.cli.app` (plan.md#CLI and
exit codes). Configuration goes through environment variables only (plan.md#Configuration); every test runs in its
own temporary working directory with its own `DATA_DIR` and `MANIFEST_PATH`, against a local HTTP server that stands
in for bsee.gov.

Production modules are imported inside the helpers, never at module level, so that each test fails on its own
(ImportError / AttributeError) while the implementation does not exist yet, instead of breaking collection.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import PgSchema
from tests.support.http_server import FixtureServer

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bsee"
REAL_ALERT_PDF = FIXTURES / "safety-alert-469.pdf"
REPO_URL = "https://github.com/meilantiago/offshore-incident-rag"
TEST_USER_AGENT = f"offshore-incident-rag-tests/0.0.1 (+{REPO_URL})"

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_PARTIAL = 3

COUNT_KEYS = (
    "manifest_entries",
    "ingested",
    "skipped_unchanged",
    "replaced",
    "failed",
    "image_only",
    "pages",
    "chunks",
)
DURATION_KEYS = ("total", "download", "parse", "chunk", "store")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class CliRun:
    exit_code: int
    output: str  # stdout and stderr as a terminal would show them
    stdout: str
    exception: BaseException | None

    def describe(self) -> str:
        return f"exit={self.exit_code} exception={self.exception!r}\n--- output ---\n{self.output}"


def run_cli(*args: str) -> CliRun:
    # The production module first, so a missing implementation reports itself, then typer (a runtime dependency).
    app = importlib.import_module("offshore_rag.cli").app
    from typer.testing import CliRunner

    result = CliRunner().invoke(app, list(args))
    try:
        stdout = result.stdout
    except ValueError:
        stdout = result.output
    return CliRun(result.exit_code, result.output, stdout, result.exception)


def assert_exit(run: CliRun, code: int) -> None:
    """The command ended with `code` on purpose (not through an unhandled exception)."""
    unhandled = run.exception is not None and not isinstance(run.exception, SystemExit)
    assert not unhandled, f"unhandled exception instead of a clean exit:\n{run.describe()}"
    assert run.exit_code == code, f"expected exit code {code}\n{run.describe()}"


@dataclass
class IngestEnv:
    """One isolated operator environment: temp dirs, env vars, the fake bsee.gov and (optionally) a database."""

    tmp: Path
    server: FixtureServer
    monkeypatch: pytest.MonkeyPatch
    pg: PgSchema | None = None
    served: dict[str, bytes] = field(default_factory=dict)

    @property
    def data_dir(self) -> Path:
        return self.tmp / "data"

    @property
    def manifest_path(self) -> Path:
        return self.tmp / "corpus" / "manifest.jsonl"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    def setenv(self, name: str, value: str | float | int) -> None:
        self.monkeypatch.setenv(name, str(value))

    # -- fake bsee.gov ---------------------------------------------------------------------------------------
    def serve_pdf(self, path: str, data: bytes, *, etag: str | None = None) -> str:
        """Serve `data` at `path`; returns the absolute source URL."""
        self.server.add(path, data, etag=etag)
        self.served[path] = data
        return self.server.url(path)

    def entry(
        self,
        path: str,
        doc_type: str = "safety_alert",
        *,
        sha: str | None = None,
        listing: str = "/safety-alerts/listing-page",
        title: str | None = None,
    ) -> dict[str, Any]:
        return {
            "doc_type": doc_type,
            "listing_url": self.server.url(listing),
            "sha256": sha,
            "source_url": self.server.url(path),
            "title": title or path.rsplit("/", 1)[-1],
        }

    # -- manifest --------------------------------------------------------------------------------------------
    def write_manifest(self, entries: list[dict[str, Any]]) -> None:
        self.write_manifest_lines([json.dumps(e, sort_keys=True) for e in sorted(entries, key=_url_key)])

    def write_manifest_lines(self, lines: list[str]) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(line + "\n" for line in lines)
        self.manifest_path.write_bytes(text.encode("utf-8"))

    # -- running ---------------------------------------------------------------------------------------------
    def ingest(self) -> CliRun:
        return run_cli("ingest")

    def reports(self) -> list[Path]:
        if not self.reports_dir.exists():
            return []
        return sorted(self.reports_dir.glob("ingest-*.json"), key=lambda p: (p.stat().st_mtime_ns, p.name))

    def latest_report(self) -> dict[str, Any]:
        reports = self.reports()
        assert reports, f"no ingestion report under {self.reports_dir}"
        data = json.loads(reports[-1].read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        return data

    # -- database --------------------------------------------------------------------------------------------
    @property
    def db(self) -> PgSchema:
        assert self.pg is not None, "this test did not request a database"
        return self.pg

    def scalar(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        return self.db.scalar(sql, params)

    def column_type(self, table: str, column: str) -> str | None:
        return self.db.scalar(
            "SELECT data_type FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
            "AND column_name = %s",
            (self.db.schema, table, column),
        )

    def snapshot(self, source_url: str) -> dict[str, Any]:
        """Everything stored for one document: its row, its pages and its chunks."""
        return {
            "document": self.document(source_url),
            "pages": self.pages(source_url),
            "chunks": self.chunks(source_url),
        }

    def counts(self) -> tuple[int, int, int]:
        return (
            self.db.scalar("SELECT count(*) FROM documents"),
            self.db.scalar("SELECT count(*) FROM pages"),
            self.db.scalar("SELECT count(*) FROM chunks"),
        )

    def document(self, source_url: str) -> dict[str, Any] | None:
        cur = self.db.conn.execute("SELECT * FROM documents WHERE source_url = %s", (source_url,))
        row = cur.fetchone()
        if row is None:
            return None
        assert cur.description is not None
        return dict(zip([c.name for c in cur.description], row, strict=True))

    def pages(self, source_url: str) -> list[tuple[int, str, bool]]:
        return [
            (n, t, bool(img))
            for n, t, img in self.db.rows(
                "SELECT p.page_number, p.text, p.image_only FROM pages p JOIN documents d ON d.id = p.document_id "
                "WHERE d.source_url = %s ORDER BY p.page_number",
                (source_url,),
            )
        ]

    def chunks(self, source_url: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT c.*, d.source_url, d.page_count FROM chunks c JOIN documents d ON d.id = c.document_id"
            + (" WHERE d.source_url = %s" if source_url else "")
            + " ORDER BY c.document_id, c.chunker, c.ordinal"
        )
        cur = self.db.conn.execute(sql, (source_url,) if source_url else ())
        assert cur.description is not None
        names = [c.name for c in cur.description]
        return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def _url_key(e: dict[str, Any]) -> str:
    return str(e.get("source_url", ""))


def outcomes(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per-document outcomes of a report, by source URL (report key `documents`)."""
    docs = report.get("documents")
    assert isinstance(docs, list), f"report has no `documents` list: {sorted(report)}"
    return {d["source_url"]: d for d in docs}


def failures(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Failures listed in a report, by source URL (report key `failures`)."""
    fails = report.get("failures")
    assert isinstance(fails, list), f"report has no `failures` list: {sorted(report)}"
    return {f["source_url"]: f for f in fails}
