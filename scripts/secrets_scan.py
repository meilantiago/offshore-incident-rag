"""Gate `secrets`: looks for keys and tokens in repo files. Never prints the secret.

A line can be excluded on purpose with the comment `secrets-scan:allow`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import harness_config as config
from lib.repo import list_repo_files, root_from_args

SECRET_PATTERNS = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("OpenAI key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b")),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{32,}\b")),
    ("Groq key", re.compile(r"\bgsk_[A-Za-z0-9]{40,}\b")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    (
        "credential in a URL",
        re.compile(
            r"\b[a-z][a-z0-9+.-]*://[^\s:@/]+:[^\s:@/]{6,}@(?!localhost\b|127\.0\.0\.1\b|db\b|postgres\b)", re.I
        ),
    ),
)

BINARY_EXT = re.compile(r"\.(png|jpe?g|gif|webp|ico|pdf|zip|gz|parquet|ttf|otf|woff2?|mp4|mov)$", re.I)
MAX_BYTES = 1024 * 1024


def scan_secrets(root: Path) -> list[str]:
    findings: list[str] = []
    for file in list_repo_files(root):
        if BINARY_EXT.search(file) or any(file.startswith(p) for p in config.SECRETS_ALLOW_PATHS):
            continue
        full = root / file
        if full.stat().st_size > MAX_BYTES:
            continue
        data = full.read_bytes()
        if b"\0" in data:
            continue
        for i, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            if "secrets-scan:allow" in line:
                continue
            for name, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(f"{file}:{i}: possible {name}")
    return findings


def main(argv: list[str]) -> int:
    findings = scan_secrets(root_from_args(argv))
    for f in findings:
        print(f"[FAIL] {f}")
    if findings:
        print(
            f"secrets: {len(findings)} finding(s). Remove the secret from the repo (and rotate it if it was committed)."
        )
        return 1
    print("secrets: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
