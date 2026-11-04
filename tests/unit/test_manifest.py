"""Manifest load, validation and deterministic write (AC-001-01, AC-001-02)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from offshore_rag.ingestion.manifest import ManifestEntry, ManifestError, load_manifest, write_manifest


def _entry(url: str, doc_type: str = "safety_alert") -> dict[str, object]:
    return {"doc_type": doc_type, "listing_url": "http://x/l", "sha256": None, "source_url": url, "title": "t"}


def _write(path: Path, entries: list[dict[str, object]]) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


def test_valid_manifest_loads(tmp_path: Path) -> None:
    entries = load_manifest(_write(tmp_path / "m.jsonl", [_entry("http://x/a.pdf"), _entry("http://x/b.pdf")]))
    assert [e.source_url for e in entries] == ["http://x/a.pdf", "http://x/b.pdf"]


def test_missing_url_names_the_line(tmp_path: Path) -> None:
    bad = {k: v for k, v in _entry("u").items() if k != "source_url"}
    with pytest.raises(ManifestError) as e:
        load_manifest(_write(tmp_path / "m.jsonl", [_entry("http://x/a.pdf"), bad]))
    assert any("line 2" in p and "source_url" in p for p in e.value.problems)


def test_unknown_type_names_url_and_value(tmp_path: Path) -> None:
    with pytest.raises(ManifestError) as e:
        load_manifest(_write(tmp_path / "m.jsonl", [_entry("http://x/a.pdf", "press_release")]))
    assert any("http://x/a.pdf" in p and "press_release" in p for p in e.value.problems)


def test_duplicate_url_is_named(tmp_path: Path) -> None:
    with pytest.raises(ManifestError) as e:
        load_manifest(_write(tmp_path / "m.jsonl", [_entry("http://x/a.pdf"), _entry("http://x/a.pdf")]))
    assert any("http://x/a.pdf" in p and "duplicate" in p and "line 2" in p for p in e.value.problems)


def test_empty_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "m.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ManifestError) as e:
        load_manifest(path)
    assert "empty" in str(e.value)


def test_invalid_json_and_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "m.jsonl"
    path.write_text("{nope\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="line 1"):
        load_manifest(path)
    with pytest.raises(ManifestError, match="not found"):
        load_manifest(tmp_path / "absent.jsonl")


def test_write_is_sorted_deterministic_and_round_trips(tmp_path: Path) -> None:
    entries = [
        ManifestEntry("panel_report", "http://x/b.pdf", "http://x/l", "Título ñ"),
        ManifestEntry("safety_alert", "http://x/a.pdf", "http://x/l", "A"),
    ]
    first, second = tmp_path / "1.jsonl", tmp_path / "sub" / "2.jsonl"
    write_manifest(entries, first)
    write_manifest(list(reversed(entries)), second)
    assert first.read_bytes() == second.read_bytes()
    raw = first.read_bytes()
    assert b"\r" not in raw and "Título ñ".encode() in raw
    lines = raw.decode("utf-8").splitlines()
    assert [json.loads(line)["source_url"] for line in lines] == ["http://x/a.pdf", "http://x/b.pdf"]
    assert list(json.loads(lines[0])) == sorted(json.loads(lines[0]))
    assert load_manifest(first) == sorted(entries, key=lambda e: e.source_url)
