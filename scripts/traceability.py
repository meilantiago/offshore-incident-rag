"""Gate `trace`: every AC of an approved spec appears in at least one test, and no test cites an AC that does not exist.

`--md [NNN]` prints the AC -> tests matrix (used in PR descriptions).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import harness_config as config
from lib.repo import arg_value, list_repo_files, root_from_args
from lib.specs import AC_ID_RE, Spec, is_approved, load_specs


def is_test_file(path: str) -> bool:
    return any(p.search(path) for p in config.TEST_FILE_PATTERNS) and not any(
        p.search(path) for p in config.TRACE_IGNORE
    )


@dataclass
class Coverage:
    errors: list[str]
    refs: dict[str, set[str]]
    specs: list[Spec]
    test_files: list[str]


def trace_coverage(root: Path, specs: list[Spec] | None = None) -> Coverage:
    specs = load_specs(root) if specs is None else specs
    test_files = [f for f in list_repo_files(root) if is_test_file(f)]
    refs: dict[str, set[str]] = {}
    for file in test_files:
        text = (root / file).read_text(encoding="utf-8", errors="replace")
        for m in AC_ID_RE.finditer(text):
            refs.setdefault(m.group(0), set()).add(file)
    known = {a.id for s in specs for a in s.acs}
    errors: list[str] = []
    for spec in filter(is_approved, specs):
        for ac in spec.acs:
            if ac.id not in refs:
                errors.append(f"{ac.id} ({spec.rel_dir}) has no test")
    for ac_id, files in sorted(refs.items()):
        if ac_id not in known:
            errors.append(f"{ac_id} does not exist in any spec, but it is cited by: {', '.join(sorted(files))}")
    return Coverage(errors, refs, specs, test_files)


def render_matrix(cov: Coverage, only: str | None = None) -> str:
    out: list[str] = []
    for spec in cov.specs:
        if only and spec.dir_id != only:
            continue
        out += [f"### {spec.dir_id} — {spec.meta_str('title') or spec.dir_name}", "", "| AC | Tests |", "|---|---|"]
        for ac in spec.acs:
            files = sorted(cov.refs.get(ac.id, set()))
            cell = "<br>".join(f"`{f}`" for f in files) if files else "**no test**"
            out.append(f"| {ac.id} | {cell} |")
        out.append("")
    return "\n".join(out)


def main(argv: list[str]) -> int:
    cov = trace_coverage(root_from_args(argv))
    if "--md" in argv:
        only = arg_value(argv, "--md")
        print(render_matrix(cov, only if only and only.isdigit() and len(only) == 3 else None))
        return 0
    for e in cov.errors:
        print(f"[FAIL] {e}")
    total = sum(len(s.acs) for s in cov.specs)
    covered = sum(1 for s in cov.specs for a in s.acs if a.id in cov.refs)
    if cov.errors:
        print(f"trace: {len(cov.errors)} error(s)")
        return 1
    print(f"trace: ok ({covered}/{total} AC with a test, {len(cov.test_files)} test file(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
