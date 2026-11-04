"""Database connection with errors that never leak the password."""

from __future__ import annotations

from typing import Any

import psycopg

from offshore_rag.config import Settings


class DatabaseUnavailable(RuntimeError):
    """The database cannot be reached. The message names host, port and database, never the password."""


def connect(settings: Settings, *, autocommit: bool = True) -> psycopg.Connection[Any]:
    if settings.database_url is None:
        raise DatabaseUnavailable("DATABASE_URL is not set: cannot connect to the database")
    url = settings.database_url.get_secret_value()
    try:
        return psycopg.connect(url, autocommit=autocommit, connect_timeout=10)
    except psycopg.Error as e:
        reason = " ".join(str(e).split())
        raise DatabaseUnavailable(f"cannot connect to the database ({settings.describe_database()}): {reason}") from e
