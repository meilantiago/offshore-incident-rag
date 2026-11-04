"""Stop (main session and the implementer agent): with uncommitted changes, runs the fast gates and does not let
the turn end while they are red. Honors stop_hook_active: after blocking once it lets the turn end (no loops)."""

from __future__ import annotations

import json
import subprocess
import sys

from _hook_io import project_root, run_hook

from lib.repo import git, is_git_repo, venv_python


def _main(payload: dict) -> None:
    if payload.get("stop_hook_active"):
        return
    root = project_root(payload)
    if not is_git_repo(root) or not git(root, ["status", "--porcelain"]).stdout:
        return
    r = subprocess.run(
        [venv_python(root), str(root / "scripts" / "check.py"), "--fast"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if r.returncode == 0:
        return
    output = "\n".join(f"{r.stdout}{r.stderr}".strip().splitlines()[-30:])
    sys.stdout.write(
        json.dumps(
            {
                "decision": "block",
                "reason": (
                    f"There are uncommitted changes and the fast gates are red:\n{output}\n\n"
                    "Fix it before finishing. If it does not belong to this task, tell the user which gate fails and why."
                ),
            }
        )
    )


if __name__ == "__main__":
    run_hook(_main)
