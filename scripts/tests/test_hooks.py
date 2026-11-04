"""Guards of the Claude Code hooks: approvals, git, generated files, the golden set and secrets."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import REPO, write
from guard_bash import evaluate_command
from guard_edit import evaluate_edit
from secrets_scan import scan_secrets

SPEC_MD = "docs/specs/001-corpus-ingestion/spec.md"


@pytest.mark.parametrize(
    "command",
    [
        "python scripts/approve.py 001",
        "git commit --no-verify -m x",
        "git push --force origin spec/001-x",
        "git push origin main",
        "gh pr merge 3 --squash",
        "docker push ghcr.io/x/y",
        "git reset --hard HEAD~1",
    ],
)
def test_guard_bash_blocks(spec_root: Path, command: str) -> None:
    assert evaluate_command(spec_root, command) is not None


@pytest.mark.parametrize(
    "command",
    ["python scripts/check.py --all", "git push -u origin spec/001-corpus-ingestion", "git status"],
)
def test_guard_bash_allows(spec_root: Path, command: str) -> None:
    assert evaluate_command(spec_root, command) is None


def test_guard_edit_blocks_env_and_generated_files(spec_root: Path) -> None:
    assert evaluate_edit(spec_root, "Write", {"file_path": str(spec_root / ".env"), "content": "X=1"})
    assert evaluate_edit(spec_root, "Write", {"file_path": str(spec_root / ".env.example"), "content": "X="}) is None
    assert evaluate_edit(spec_root, "Write", {"file_path": str(spec_root / "docs/specs/STATUS.md"), "content": ""})


def test_guard_edit_blocks_the_golden_set_but_not_candidates(spec_root: Path) -> None:
    golden = {"file_path": str(spec_root / "eval/golden/questions.jsonl"), "content": "{}"}
    candidate = {"file_path": str(spec_root / "eval/candidates/questions.jsonl"), "content": "{}"}
    assert evaluate_edit(spec_root, "Write", golden)
    assert evaluate_edit(spec_root, "Write", candidate) is None


def test_guard_edit_blocks_self_approval(spec_root: Path) -> None:
    edit = {"file_path": str(spec_root / SPEC_MD), "old_string": "status: draft", "new_string": "status: approved"}
    assert evaluate_edit(spec_root, "Edit", edit)
    benign = {"file_path": str(spec_root / SPEC_MD), "old_string": "Reports are scattered.", "new_string": "Spread."}
    assert evaluate_edit(spec_root, "Edit", benign) is None


def test_guard_bash_hook_emits_a_deny_decision(spec_root: Path) -> None:
    payload = json.dumps({"cwd": str(spec_root), "tool_input": {"command": "python scripts/approve.py 001"}})
    r = subprocess.run(
        [sys.executable, str(REPO / ".claude/hooks/guard_bash.py")],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_secrets_scan_finds_keys_and_honors_allow(spec_root: Path) -> None:
    fake = "gh" + "p_" + "a" * 36
    write(spec_root, "src/leak.py", f'TOKEN = "{fake}"\n')
    write(spec_root, "src/ok.py", f'TOKEN = "{fake}"  # secrets-scan:allow\n')
    findings = scan_secrets(spec_root)
    assert findings == ["src/leak.py:1: possible GitHub token"]
