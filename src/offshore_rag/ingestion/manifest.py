"""The corpus manifest: one JSON object per line, sorted by `source_url`, keys sorted."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

DOC_TYPES = ("safety_alert", "panel_report", "district_report")
# Entries are separated by "\n" only: str.splitlines() would also split on U+2028, U+2029, U+0085.
_LINE_SEPARATOR = "\n"


class ManifestError(Exception):
    """The manifest is malformed. `problems` has one message per offending entry."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class ManifestEntry:
    doc_type: str
    source_url: str
    listing_url: str
    title: str = ""
    sha256: str | None = None


def _url_problem(url: str) -> str | None:
    """Why `url` is not an absolute http(s) URL, or None when it is."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError as e:
        return f"source_url is not a valid URL ({e})"
    if parts.scheme not in ("http", "https") or not host:
        return "source_url must be an absolute http(s) URL"
    return None


def load_manifest(path: Path) -> list[ManifestEntry]:
    """Read and validate a manifest. Raises `ManifestError` listing every problem found."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ManifestError([f"manifest file not found: {path}"]) from e
    except UnicodeDecodeError as e:
        raise ManifestError([f"manifest is not valid UTF-8: {e}"]) from e

    entries: list[ManifestEntry] = []
    problems: list[str] = []
    first_line_of: dict[str, int] = {}
    for number, line in enumerate(text.split(_LINE_SEPARATOR), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as e:
            problems.append(f"line {number}: not valid JSON ({e.msg})")
            continue
        if not isinstance(raw, dict):
            problems.append(f"line {number}: entry is not a JSON object")
            continue
        url = raw.get("source_url")
        if not isinstance(url, str) or not url.strip():
            problems.append(f"line {number}: missing source_url")
            continue
        url_problem = _url_problem(url)
        if url_problem:
            problems.append(f"line {number}: {url}: {url_problem}")
            continue
        doc_type = raw.get("doc_type")
        if doc_type not in DOC_TYPES:
            problems.append(
                f"line {number}: {url}: unknown doc_type {doc_type!r} (expected one of {', '.join(DOC_TYPES)})"
            )
            continue
        listing_url = raw.get("listing_url")
        if not isinstance(listing_url, str) or not listing_url.strip():
            problems.append(f"line {number}: {url}: missing listing_url")
            continue
        title = raw.get("title", "")
        sha = raw.get("sha256")
        if not isinstance(title, str) or not (sha is None or isinstance(sha, str)):
            problems.append(f"line {number}: {url}: title and sha256 must be strings")
            continue
        if url in first_line_of:
            problems.append(f"line {number}: {url}: duplicate source_url (first on line {first_line_of[url]})")
            continue
        first_line_of[url] = number
        entries.append(ManifestEntry(doc_type, url, listing_url, title, sha))

    if not problems and not entries:
        problems.append("manifest is empty: it has no entries")
    if problems:
        raise ManifestError(problems)
    return entries


def write_manifest(entries: Iterable[ManifestEntry], path: Path) -> None:
    """Write the manifest deterministically: sorted by source_url, sorted keys, UTF-8, LF line endings."""
    ordered = sorted(entries, key=lambda e: e.source_url)
    lines = [json.dumps(asdict(e), sort_keys=True, ensure_ascii=False) + "\n" for e in ordered]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(lines).encode("utf-8"))
