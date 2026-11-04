"""HUMAN GATE 1. Approves spec + plan and stores the hash in the spec frontmatter.

Usage (in a terminal, never from an agent): python scripts/approve.py NNN
"""

from __future__ import annotations

import datetime as dt
import getpass
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from lib.repo import git, root_from_args
from lib.specs import approval_hash, load_specs, set_frontmatter_fields
from spec_lint import lint_specs
from status import STATUS_FILE, render_status


@dataclass
class ApprovalResult:
    ok: bool
    errors: list[str]
    hash: str = ""


def approve_spec(root: Path, spec_id: str, approver: str, today: dt.date | None = None) -> ApprovalResult:
    spec = next((s for s in load_specs(root) if s.dir_id == spec_id), None)
    if spec is None or spec.spec_text is None:
        return ApprovalResult(False, [f"spec {spec_id} does not exist"])
    errors, _ = lint_specs(root, strict=True, only=spec_id)
    if errors:
        return ApprovalResult(False, errors)
    digest = approval_hash(spec)
    updated = set_frontmatter_fields(
        spec.spec_text,
        {
            "status": "approved",
            "approved_hash": digest,
            "approved_at": (today or dt.date.today()).isoformat(),
            "approved_by": approver,
        },
    )
    (root / spec.rel_dir / "spec.md").write_text(updated, encoding="utf-8", newline="\n")
    (root / STATUS_FILE).write_text(render_status(root), encoding="utf-8", newline="\n")
    return ApprovalResult(True, [], digest)


def main(argv: list[str]) -> int:
    root = root_from_args(argv)
    spec_id = next((a for a in argv[1:] if re.fullmatch(r"\d{3}", a)), None)
    if not spec_id:
        print("Usage: python scripts/approve.py NNN")
        return 1
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("Approval is a human action: run this command yourself, in an interactive terminal.")
        return 1
    spec = next((s for s in load_specs(root) if s.dir_id == spec_id), None)
    if spec is None:
        print(f"Spec {spec_id} does not exist.")
        return 1
    print(f"\nSpec {spec_id}: {spec.meta_str('title')}")
    print(f"  {len(spec.acs)} acceptance criteria, {len(spec.tasks or [])} tasks")
    print(f"  Review {spec.rel_dir}/spec.md and plan.md before continuing.\n")
    if input(f'Type "{spec_id}" to approve spec + plan: ').strip() != spec_id:
        print("Not approved.")
        return 1
    approver = git(root, ["config", "user.name"]).stdout or getpass.getuser()
    result = approve_spec(root, spec_id, approver)
    if not result.ok:
        print("\nCannot approve yet:")
        for e in result.errors:
            print(f"  - {e}")
        return 1
    print(f"\nApproved by {approver}. Hash {result.hash[:19]}…")
    print(f"Next: commit spec.md and STATUS.md, then ask Claude for /sdd-build {spec_id}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
