"""Shared helpers for the Claude Code hooks (JSON on stdin, JSON on stdout).

Hooks only use the standard library, so they run with any Python 3.11+ on PATH.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from collections.abc import Callable
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def read_input() -> dict:
    data = sys.stdin.read()
    return json.loads(data) if data.strip() else {}


def project_root(payload: dict) -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()).resolve()


def deny_tool(reason: str) -> None:
    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def run_hook(main: Callable[[dict], None]) -> None:
    """A broken hook must not block the work: it warns on stderr and lets it continue."""
    try:
        main(read_input())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 - reported, never swallowed silently
        sys.stderr.write(f"[hook {sys.argv[0]}] internal error: {e}\n{traceback.format_exc(limit=3)}")
    sys.exit(0)
