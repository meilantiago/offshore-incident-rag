"""Command line: `offshore-rag db migrate | build-manifest | ingest`.

Exit codes: 0 ok, 3 finished with failed documents, 1 fatal.
"""

from __future__ import annotations

import psycopg
import typer

from offshore_rag.config import Settings, get_settings
from offshore_rag.db.connection import DatabaseUnavailable, connect
from offshore_rag.db.migrate import migrate, pending_migrations
from offshore_rag.ingestion.build import ManifestBuildError, build_manifest
from offshore_rag.ingestion.chunking import UnknownChunkerError, chunkers_from_config
from offshore_rag.ingestion.http import FetchError, PoliteClient
from offshore_rag.ingestion.manifest import ManifestError, load_manifest, write_manifest
from offshore_rag.ingestion.pipeline import run_ingest
from offshore_rag.ingestion.report import format_summary, write_report
from offshore_rag.ingestion.store import CorpusStore
from offshore_rag.logging import configure_logging

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_PARTIAL = 3

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Offshore incident corpus tools.")
db_app = typer.Typer(no_args_is_help=True, help="Database commands.")
app.add_typer(db_app, name="db")


def fatal(message: str) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(EXIT_FATAL)


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply pending database migrations."""
    settings = get_settings()
    configure_logging(settings.log_format)
    try:
        with connect(settings) as conn:
            try:
                applied = migrate(conn)
            except psycopg.Error as e:
                raise fatal(
                    f"migration failed on the database ({settings.describe_database()}): {' '.join(str(e).split())}"
                ) from e
    except DatabaseUnavailable as e:
        raise fatal(str(e)) from e
    if applied:
        typer.echo("Applied migrations: " + ", ".join(applied))
    else:
        typer.echo("Database is up to date.")


@app.command("build-manifest")
def build_manifest_command() -> None:
    """Walk the BSEE listing pages and write the manifest file."""
    settings = get_settings()
    configure_logging(settings.log_format)
    with _client(settings) as client:
        try:
            entries = build_manifest(client, settings.bsee_base_url, settings.data_dir / "listings")
        except (ManifestBuildError, FetchError) as e:
            raise fatal(str(e)) from e
    write_manifest(entries, settings.manifest_path)
    typer.echo(f"Wrote {len(entries)} entries to {settings.manifest_path}")


def _client(settings: Settings) -> PoliteClient:
    return PoliteClient(
        user_agent=settings.http_user_agent,
        rate_per_second=settings.http_rate_per_second,
        max_retries=settings.http_max_retries,
        timeout=settings.http_timeout_seconds,
    )


@app.command("ingest")
def ingest_command() -> None:
    """Download, parse, chunk and store every manifest entry, then write the ingestion report."""
    settings = get_settings()
    configure_logging(settings.log_format)
    # 1. The whole manifest and the configuration are validated before any network or database access.
    try:
        entries = load_manifest(settings.manifest_path)
    except ManifestError as e:
        details = "\n".join(f"  - {p}" for p in e.problems)
        raise fatal(f"invalid manifest {settings.manifest_path}; nothing was downloaded or stored:\n{details}") from e
    try:
        chunkers = chunkers_from_config(settings.chunkers)
    except UnknownChunkerError as e:
        raise fatal(f"invalid CHUNKERS setting: {e}") from e
    # 2. The database must be reachable and fully migrated. `ingest` never migrates by itself.
    try:
        conn = connect(settings)
    except DatabaseUnavailable as e:
        raise fatal(str(e)) from e
    target = settings.describe_database()
    with conn:
        try:
            pending = pending_migrations(conn)
        except psycopg.Error as e:
            raise fatal(f"cannot read the schema of the database ({target}): {' '.join(str(e).split())}") from e
        if pending:
            raise fatal(
                f"the database schema is missing or not migrated ({target}): pending migrations "
                f"{', '.join(pending)}. Run `offshore-rag db migrate` first."
            )
        # 3. Documents, one at a time. Per-document failures are in the report; anything else is fatal.
        with _client(settings) as client:
            try:
                report = run_ingest(entries, client, CorpusStore(conn), chunkers, settings.data_dir)
            except psycopg.Error as e:
                raise fatal(f"database error during ingest ({target}): {' '.join(str(e).split())}") from e
            except OSError as e:
                raise fatal(f"file system error during ingest: {e}") from e
    path = write_report(report, settings.data_dir)
    typer.echo(format_summary(report))
    typer.echo(f"Report: {path}")
    raise typer.Exit(EXIT_PARTIAL if report.has_failures else EXIT_OK)
