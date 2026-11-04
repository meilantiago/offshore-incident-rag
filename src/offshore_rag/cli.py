"""Command line: `offshore-rag db migrate | build-manifest` (ingest arrives with a later milestone).

Exit codes: 0 ok, 3 finished with failed documents, 1 fatal.
"""

from __future__ import annotations

import psycopg
import typer

from offshore_rag.config import get_settings
from offshore_rag.db.connection import DatabaseUnavailable, connect
from offshore_rag.db.migrate import migrate
from offshore_rag.ingestion.build import ManifestBuildError, build_manifest
from offshore_rag.ingestion.http import FetchError, PoliteClient
from offshore_rag.ingestion.manifest import write_manifest
from offshore_rag.logging import configure_logging

EXIT_FATAL = 1

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
    with PoliteClient(
        user_agent=settings.http_user_agent,
        rate_per_second=settings.http_rate_per_second,
        max_retries=settings.http_max_retries,
        timeout=settings.http_timeout_seconds,
    ) as client:
        try:
            entries = build_manifest(client, settings.bsee_base_url, settings.data_dir / "listings")
        except (ManifestBuildError, FetchError) as e:
            raise fatal(str(e)) from e
    write_manifest(entries, settings.manifest_path)
    typer.echo(f"Wrote {len(entries)} entries to {settings.manifest_path}")
