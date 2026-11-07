"""Settings defaults, environment overrides and password-free rendering of DATABASE_URL (AC-001-04, AC-001-12)."""

from __future__ import annotations

import pytest

from offshore_rag.config import Settings, get_settings

ENV_NAMES = (
    "DATABASE_URL",
    "DATA_DIR",
    "MANIFEST_PATH",
    "BSEE_BASE_URL",
    "HTTP_USER_AGENT",
    "HTTP_RATE_PER_SECOND",
    "HTTP_MAX_RETRIES",
    "HTTP_TIMEOUT_SECONDS",
    "CHUNKERS",
    "LOG_FORMAT",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(str(tmp_path))  # no stray .env


def test_defaults() -> None:
    s = get_settings()
    assert s.http_rate_per_second == 1.0
    assert s.http_max_retries == 4
    assert s.http_timeout_seconds == 30
    assert str(s.data_dir) == "data"
    assert s.manifest_path.as_posix() == "corpus/manifest.jsonl"
    assert s.bsee_base_url == "https://www.bsee.gov"
    assert s.chunkers == ["fixed_words"]
    assert s.database_url is None


def test_default_user_agent_names_repo_and_has_no_email() -> None:
    ua = get_settings().http_user_agent
    assert "https://github.com/meilantiago/offshore-incident-rag" in ua
    assert "@" not in ua


def test_overrides_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_RATE_PER_SECOND", "5")
    monkeypatch.setenv("HTTP_MAX_RETRIES", "2")
    monkeypatch.setenv("DATA_DIR", "somewhere")
    monkeypatch.setenv("CHUNKERS", "fixed_words, other")
    s = get_settings()
    assert s.http_rate_per_second == 5.0
    assert s.http_max_retries == 2
    assert str(s.data_dir) == "somewhere"
    assert s.chunkers == ["fixed_words", "other"]


def test_database_url_is_rendered_without_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://alice:hunter2@db.example:5544/corpus?sslmode=require")
    s = get_settings()
    assert s.database_url is not None
    assert "hunter2" in s.database_url.get_secret_value()
    shown = s.describe_database()
    assert "hunter2" not in shown
    assert "db.example" in shown
    assert "5544" in shown
    assert "corpus" in shown
    assert "hunter2" not in repr(s)


def test_describe_database_without_url() -> None:
    assert "DATABASE_URL" in Settings(_env_file=None).describe_database()
