"""Gate `approval`.

1. Every approved spec keeps the hash it was approved with (otherwise it must be re-approved).
2. Product code only changes on a spec/NNN-* branch whose spec is approved.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import harness_config as config
from lib.repo import current_branch, git, is_git_repo, root_from_args
from lib.specs import Spec, hash_matches, is_approved, load_specs


def check_approvals(
    root: Path,
    branch: str | None = None,
    base_ref: str | None = None,
    specs: list[Spec] | None = None,
) -> tuple[list[str], list[str]]:
    base_ref = base_ref or os.environ.get("HARNESS_BASE_REF") or "main"
    specs = load_specs(root) if specs is None else specs
    errors: list[str] = []
    notes: list[str] = []
    for spec in filter(is_approved, specs):
        if not hash_matches(spec):
            errors.append(
                f"spec {spec.dir_id} changed after approval (spec.md or plan.md): the user has to review and re-approve it"
            )

    if not is_git_repo(root):
        notes.append("not a git repo: the branch rule is not checked")
        return errors, notes
    br = branch if branch is not None else current_branch(root)
    if not br or br == base_ref:
        notes.append(f"on {br or 'detached HEAD'}: the branch rule is not checked")
        return errors, notes
    base = next(
        (ref for ref in (f"origin/{base_ref}", base_ref) if git(root, ["rev-parse", "--verify", "--quiet", ref]).ok),
        None,
    )
    merge_base = git(root, ["merge-base", "HEAD", base]) if base else None
    if merge_base is None or not merge_base.ok:
        notes.append(f"base {base_ref} not found: the branch rule is not checked")
        return errors, notes
    changed = set(git(root, ["diff", "--name-only", merge_base.stdout]).stdout.split("\n"))
    changed |= set(git(root, ["ls-files", "-o", "--exclude-standard"]).stdout.split("\n"))
    product = sorted(f for f in changed if f and any(f.startswith(p) for p in config.PRODUCT_PATHS))
    if not product:
        return errors, notes

    sample = ", ".join(product[:5]) + (", …" if len(product) > 5 else "")
    m = re.match(r"^spec/(\d{3})-", br)
    if not m:
        errors.append(f'branch "{br}" touches product code ({sample}) but it is not a spec/NNN-* branch')
    else:
        spec = next((s for s in specs if s.dir_id == m.group(1)), None)
        if spec is None:
            errors.append(f'branch "{br}" points to spec {m.group(1)}, which does not exist')
        elif not is_approved(spec):
            errors.append(f"spec {m.group(1)} is not approved and the branch already touches product code ({sample})")
    return errors, notes


def main(argv: list[str]) -> int:
    errors, notes = check_approvals(root_from_args(argv))
    for n in notes:
        print(f"[info] {n}")
    for e in errors:
        print(f"[FAIL] {e}")
    print(f"approval: {len(errors)} error(s)" if errors else "approval: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
