"""Fixtures for the harness tests: throwaway repositories with specs, built in tmp_path."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for p in (REPO / "scripts", REPO / ".claude" / "hooks"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SPEC = """\
---
id: "001"
title: Corpus ingestion
status: draft
roadmap_refs: ["R1"]
approved_hash:
approved_at:
approved_by:
---

# 001 — Corpus ingestion

## Problem
Reports are scattered.

## Users
Operator.

## Stories
- As an operator, I want to ingest, so that I can search.

## Acceptance criteria
- **AC-001-01** — Given a manifest, when ingest runs, then every document is stored with its hash.
- **AC-001-02** — Given an unchanged document, when ingest runs again, then it is skipped.

## Non-goals
Retrieval.

## Data and provenance
Public BSEE PDFs.

## Metrics
Documents per minute.

## Open questions
- [x] Which source? → BSEE.
"""

PLAN = """\
# 001 — Technical plan

## Design
Manifest → download → parse → store.

## Data model
### Documents table
documents(id, url, sha256).

## Contracts
`ingest(manifest) -> Report`.

## Test strategy
| AC | Layer | Test |
|---|---|---|
| AC-001-01 | integration | test_ingest |
| AC-001-02 | integration | test_reingest |

## Evaluation impact
none

## Risks
Scanned PDFs.

## ADRs
none
"""

TASKS = """\
# 001 — Tasks

- [ ] **T01** Red acceptance tests
  - AC: AC-001-01, AC-001-02
  - Files: tests/test_ingest.py
  - Test first: the tests themselves
  - Done when: they fail for lack of implementation

## H1 — Storage
- Agent: implementer
- Model: sonnet
- Context: `plan.md#Documents table`

- [ ] **T02** Documents table
  - AC: AC-001-01, AC-001-02
  - Files: src/offshore_rag/store.py
  - Test first: test_store
  - Done when: `python scripts/check.py --fast` green
"""


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8", newline="\n")
    return path


def git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return r.stdout.strip()


@pytest.fixture
def spec_root(tmp_path: Path) -> Path:
    """A tree with one complete draft spec, not a git repo."""
    write(tmp_path, "docs/specs/001-corpus-ingestion/spec.md", SPEC)
    write(tmp_path, "docs/specs/001-corpus-ingestion/plan.md", PLAN)
    write(tmp_path, "docs/specs/001-corpus-ingestion/tasks.md", TASKS)
    return tmp_path


@pytest.fixture
def git_root(spec_root: Path) -> Path:
    """The same tree as a git repo with one commit on main."""
    git(spec_root, "init", "-q", "-b", "main")
    git(spec_root, "config", "user.email", "harness@test.local")
    git(spec_root, "config", "user.name", "Harness Test")
    git(spec_root, "add", "-A")
    git(spec_root, "commit", "-q", "-m", "init")
    return spec_root
