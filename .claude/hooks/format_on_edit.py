"""PostToolUse (Edit|Write|MultiEdit): runs the formatters registered for the edited file."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _hook_io import project_root, run_hook

import harness_config as config
from lib.repo import to_repo_path, venv_python


def _main(payload: dict) -> None:
    root = project_root(payload)
    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not file_path:
        return
    rel = to_repo_path(root, Path(file_path))
    if rel.startswith(".."):
        return
    python = venv_python(root)
    for pattern, template in config.FORMATTERS:
        if not pattern.search(rel):
            continue
        cmd = [python if p == "{python}" else rel if p == "{file}" else p for p in template]
        r = subprocess.run(
            cmd, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
        )
        if r.returncode != 0:
            # exit 2 in PostToolUse: the message reaches Claude so it fixes it.
            sys.stderr.write(f"{' '.join(template)} failed on {rel}:\n{(r.stdout + r.stderr).strip()[-2000:]}\n")
            sys.exit(2)


if __name__ == "__main__":
    run_hook(_main)
