"""PreToolUse (Bash|PowerShell): blocks approving specs, skipping git hooks, pushing to main, force pushes
and the commands listed in scripts/harness_config.py."""

from __future__ import annotations

import re
from pathlib import Path

from _hook_io import deny_tool, project_root, run_hook

import harness_config as config
from lib.repo import current_branch, is_git_repo


def evaluate_command(root: Path, command: str) -> str | None:
    if re.search(r"\bapprove\.py\b|scripts[\\/]+approve\b", command):
        return "Approving a spec is a human action (gate 1). Ask the user to run `python scripts/approve.py NNN` in a terminal."
    if re.search(r"--no-verify\b", command):
        return "Git hooks are not skipped. If a hook fails, fix the cause."
    if re.search(r"\bgit\s+push\b", command):
        if re.search(r"\s(-f|--force|--force-with-lease|--force-if-includes)\b|\s\+\S", command):
            return "No force pushes. If the branch diverged, tell the user."
        on_main = is_git_repo(root) and current_branch(root) == "main"
        if re.search(r"(\s|:)main\b", command) or on_main:
            return "main is only reached through a PR the user merges (gate 2). Push your spec/NNN-* branch and open the PR."
    blocked = next((b for b in config.BLOCKED_COMMANDS if b.pattern.search(command)), None)
    return f"{blocked.reason} (constitution §10)" if blocked else None


def _main(payload: dict) -> None:
    reason = evaluate_command(project_root(payload), (payload.get("tool_input") or {}).get("command", ""))
    if reason:
        deny_tool(reason)


if __name__ == "__main__":
    run_hook(_main)
