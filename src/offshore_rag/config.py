"""Runtime configuration, read from the environment (or `.env`) when `get_settings()` is called."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from psycopg.conninfo import conninfo_to_dict
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from offshore_rag import __version__

REPO_URL = "https://github.com/meilantiago/offshore-incident-rag"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: SecretStr | None = None
    data_dir: Path = Path("data")
    manifest_path: Path = Path("corpus/manifest.jsonl")
    bsee_base_url: str = "https://www.bsee.gov"
    http_user_agent: str = f"offshore-incident-rag/{__version__} (+{REPO_URL})"
    http_rate_per_second: float = 1.0
    http_max_retries: int = 4
    http_timeout_seconds: float = 30
    chunkers: Annotated[list[str], NoDecode] = ["fixed_words"]
    log_format: str = "console"

    @field_validator("chunkers", mode="before")
    @classmethod
    def _split_chunkers(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    def describe_database(self) -> str:
        """Host, port and database of `DATABASE_URL` for messages. Never includes the password."""
        if self.database_url is None:
            return "DATABASE_URL is not set"
        try:
            params = conninfo_to_dict(self.database_url.get_secret_value())
        except ValueError:
            return "DATABASE_URL is not a valid connection string"
        host = params.get("host") or params.get("hostaddr") or "localhost"
        port = params.get("port") or "5432"
        dbname = params.get("dbname") or params.get("user") or "(default)"
        return f"host={host} port={port} database={dbname}"


def get_settings() -> Settings:
    return Settings()
