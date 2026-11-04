"""Command line: `offshore-rag db migrate` (build-manifest and ingest arrive with later milestones).

Exit codes: 0 ok, 3 finished with failed documents, 1 fatal.
"""

from __future__ import annotations

import psycopg
import typer

from offshore_rag.config import get_settings
from offshore_rag.db.connection import DatabaseUnavailable, connect
from offshore_rag.db.migrate import migrate
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
