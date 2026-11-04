"""PreToolUse (Edit|Write|MultiEdit): blocks .env files, generated files, the approval fields of a spec
and edits to the frozen evaluation set."""

from __future__ import annotations

import re
from pathlib import Path

from _hook_io import deny_tool, project_root, run_hook

import harness_config as config
from lib.repo import to_repo_path
from lib.specs import parse_frontmatter

SPEC_FILE_RE = re.compile(r"^docs/specs/\d{3}-[^/]+/spec\.md$")
APPROVAL_KEYS = ("approved_hash", "approved_at", "approved_by")
# The golden evaluation set is written by a person; agents propose changes, never apply them (constitution §6).
EVAL_SET_RE = re.compile(r"^eval/golden/")


def _resulting_content(tool_name: str, tool_input: dict, current: str) -> str:
    if tool_name == "Write":
        return tool_input.get("content", "")
    edits = tool_input.get("edits", []) if tool_name == "MultiEdit" else [tool_input]
    text = current
    for e in edits:
        old, new = e.get("old_string", ""), e.get("new_string", "")
        text = text.replace(old, new) if e.get("replace_all") else text.replace(old, new, 1)
    return text


def evaluate_edit(root: Path, tool_name: str, tool_input: dict) -> str | None:
    path = Path(tool_input.get("file_path", ""))
    abs_path = path if path.is_absolute() else root / path
    name = abs_path.name
    if re.fullmatch(r"\.env(\..+)?", name) and name != ".env.example":
        return ".env files hold real secrets and the user manages them. Add new variables to .env.example."
    rel = to_repo_path(root, abs_path)
    if rel.startswith(".."):
        return None
    if rel in config.GENERATED_FILES:
        return f"{rel} is generated: do not edit it by hand. Regenerate it with `{config.GENERATED_FILES[rel]}`."
    if EVAL_SET_RE.match(rel):
        return (
            "The golden evaluation set is curated by a person (constitution §6). "
            "Propose the change to the user with the reason; do not apply it."
        )
    if SPEC_FILE_RE.match(rel):
        current = abs_path.read_text(encoding="utf-8") if abs_path.exists() else ""
        before = parse_frontmatter(current)[0] or {}
        after = parse_frontmatter(_resulting_content(tool_name, tool_input, current))[0] or {}
        approval_changed = any((after.get(k) or "") != (before.get(k) or "") for k in APPROVAL_KEYS)
        newly_approved = after.get("status") == "approved" and before.get("status") != "approved"
        if newly_approved or (
            approval_changed and (after.get("status") == "approved" or any(after.get(k) for k in APPROVAL_KEYS))
        ):
            return (
                "Approving a spec is a human action (gate 1). Do not write status: approved or the approved_* fields: "
                "ask the user to run `python scripts/approve.py NNN` in a terminal."
            )
    return None


def _main(payload: dict) -> None:
    reason = evaluate_edit(project_root(payload), payload.get("tool_name", ""), payload.get("tool_input") or {})
    if reason:
        deny_tool(reason)


if __name__ == "__main__":
    run_hook(_main)
