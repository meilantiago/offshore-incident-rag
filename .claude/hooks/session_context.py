"""SessionStart: gives Claude the project state at startup (branch, active spec, specs and last check)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from _hook_io import project_root, run_hook

from lib.repo import current_branch, is_git_repo
from lib.specs import derive_status, load_specs
from traceability import trace_coverage


def build_context(root: Path) -> str:
    specs = load_specs(root)
    covered = set(trace_coverage(root, specs).refs)
    branch = current_branch(root) if is_git_repo(root) else "(no git)"
    lines = ["offshore-incident-rag: harness context (docs/workflow.md)", f"Branch: {branch}"]
    active = re.match(r"^spec/(\d{3})-", branch)
    spec = next((s for s in specs if active and s.dir_id == active.group(1)), None)
    if spec:
        tasks = spec.tasks or []
        lines.append(
            f'Active spec: {spec.dir_id} "{spec.meta_str("title")}", state {derive_status(spec, covered)}, '
            f"tasks {sum(t.done for t in tasks)}/{len(tasks)}"
        )
    lines.append(
        "Specs: " + " | ".join(f"{s.dir_id} {derive_status(s, covered)}" for s in specs)
        if specs
        else "Specs: none yet (start with /sdd-spec)"
    )
    last = root / ".harness" / "last-check.json"
    if last.exists():
        data = json.loads(last.read_text(encoding="utf-8"))
        failed = [r["id"] for r in data.get("results", []) if not r.get("ok")]
        lines.append(
            f"Last check ({data.get('mode')}, {data.get('at')}): "
            + (f"FAILED in {', '.join(failed)}" if failed else "green")
        )
    lines.append('Rules: docs/constitution.md. "Done" = python scripts/check.py --all green; no agent approves.')
    return "\n".join(lines)


def _main(payload: dict) -> None:
    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": build_context(project_root(payload)),
                }
            }
        )
    )


if __name__ == "__main__":
    run_hook(_main)
