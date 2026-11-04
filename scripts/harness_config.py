"""Single harness configuration: gates, product paths, generated files and guards.

Stack: ADR-0001. Python package in src/offshore_rag, tests in tests/, evaluation assets in eval/.
`{python}` in a gate command is replaced by the project's interpreter (.venv if present).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Gate:
    id: str
    cmd: list[str]
    fast: bool
    # Exit codes that count as green besides 0 (pytest exits 5 when it collects no tests).
    ok_codes: tuple[int, ...] = field(default=(0,))


@dataclass(frozen=True)
class BlockedCommand:
    pattern: re.Pattern[str]
    reason: str


# Product code: only changed from a spec/NNN-* branch whose spec is approved (gate `approval`).
PRODUCT_PATHS = ("src/", "tests/", "eval/", "docker/", "docker-compose.yml")

# Files produced by a command. Agents never edit them by hand (hook guard_edit).
GENERATED_FILES = {"docs/specs/STATUS.md": "python scripts/status.py"}

# Which files count as tests for AC -> test traceability.
TEST_FILE_PATTERNS = (re.compile(r"(^|/)tests/(.+/)?test_[^/]+\.py$"),)
# The harness's own tests use made-up AC ids in fixtures.
TRACE_IGNORE = (re.compile(r"^scripts/"), re.compile(r"^docs/"))

SECRETS_ALLOW_PATHS: tuple[str, ...] = ()

# /sdd-build works per milestone (`## H1 — …` in tasks.md). Each milestone names its agent and model.
BUILD_AGENTS = ("implementer",)
BUILD_MODELS = ("haiku", "sonnet", "opus")

# A long plan is read whole by every step that does not use `Context`. Going over is a warning.
PLAN_BUDGET_KB = 40

# Commands no agent runs (hook guard_bash). Constitution §10.
BLOCKED_COMMANDS = (
    BlockedCommand(re.compile(r"\bgh\s+pr\s+merge\b"), "Merging is human gate 2."),
    BlockedCommand(re.compile(r"\bgh\s+repo\s+(delete|edit|rename)\b"), "Repository settings are managed by a person."),
    BlockedCommand(re.compile(r"\bgh\s+release\s+create\b"), "Releases are published by a person."),
    BlockedCommand(re.compile(r"\bdocker\s+push\b"), "Publishing images is a human action."),
    BlockedCommand(
        re.compile(r"\bgit\s+(reset\s+--hard|clean\s+-[a-z]*f)"),
        "Destructive git commands discard work. Ask the user.",
    ),
)

# Formatters run by the format_on_edit hook: (path regex, command). `{file}` is the edited file.
FORMATTERS = (
    (re.compile(r"\.py$"), ["{python}", "-m", "ruff", "format", "{file}"]),
    (re.compile(r"\.py$"), ["{python}", "-m", "ruff", "check", "--fix", "--quiet", "{file}"]),
)

# `fast` gates run when an agent stops with uncommitted changes (hook gate_on_stop). All of them run in CI.
# Acceptance tests are never fast: during a build they are red on purpose.
GATES = (
    Gate("spec-lint", ["{python}", "scripts/spec_lint.py"], fast=True),
    Gate("approval", ["{python}", "scripts/approval_check.py"], fast=True),
    Gate("status-fresh", ["{python}", "scripts/status.py", "--check"], fast=True),
    Gate("secrets", ["{python}", "scripts/secrets_scan.py"], fast=True),
    Gate("format", ["{python}", "-m", "ruff", "format", "--check", "."], fast=True),
    Gate("lint", ["{python}", "-m", "ruff", "check", "."], fast=True),
    Gate("typecheck", ["{python}", "-m", "mypy", "src"], fast=True),
    Gate("trace", ["{python}", "scripts/traceability.py"], fast=False),
    Gate("harness-tests", ["{python}", "-m", "pytest", "scripts/tests", "-q", "-p", "no:cacheprovider"], fast=False),
    Gate("tests", ["{python}", "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"], fast=False, ok_codes=(0, 5)),
)
