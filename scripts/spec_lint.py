"""Gate `spec-lint`: structure of spec.md, plan.md and tasks.md.

Completeness checks are errors when the spec is approved (or with --strict) and warnings while it is a draft.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path

import harness_config as config
from lib.repo import arg_value, root_from_args
from lib.specs import (
    AC_SECTION,
    MILESTONE_FIELDS,
    PLAN_SECTIONS,
    QUESTIONS_SECTION,
    SPEC_SECTIONS,
    STATUSES,
    TASK_FIELDS,
    TEST_STRATEGY_SECTION,
    Spec,
    ac_ids_in,
    context_refs,
    load_specs,
    resolve_context_ref,
)

Report = Callable[[str, str], None]


def lint_specs(root: Path, strict: bool = False, only: str | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    specs = load_specs(root)
    by_id: dict[str, list[str]] = {}
    for spec in specs:
        if spec.dir_id:
            by_id.setdefault(spec.dir_id, []).append(spec.rel_dir)
        if only and spec.dir_id != only:
            continue
        _lint_spec(root, spec, strict or spec.meta_str("status") == "approved", errors, warnings)
    for spec_id, dirs in by_id.items():
        if len(dirs) > 1:
            errors.append(f"id {spec_id} repeated in: {', '.join(dirs)}")
    if only and not any(s.dir_id == only for s in specs):
        errors.append(f"spec {only} does not exist")
    return errors, warnings


def _lint_spec(root: Path, spec: Spec, strict: bool, errors: list[str], warnings: list[str]) -> None:
    def err(file: str, msg: str) -> None:
        errors.append(f"{spec.rel_dir}/{file}: {msg}")

    def warn(file: str, msg: str) -> None:
        warnings.append(f"{spec.rel_dir}/{file}: {msg}")

    need = err if strict else warn

    if not spec.dir_id:
        errors.append(f"{spec.rel_dir}: invalid folder name (use NNN-lowercase-slug)")
        return
    if not spec.spec_text:
        err("spec.md", "spec.md is missing")
        return
    if spec.meta is None:
        err("spec.md", "frontmatter is missing")
        return

    if spec.meta_str("id") != spec.dir_id:
        err("spec.md", f'id "{spec.meta_str("id")}" does not match the folder ({spec.dir_id})')
    if not spec.meta_str("title"):
        err("spec.md", "title is missing")
    if spec.meta_str("status") not in STATUSES:
        err("spec.md", f'invalid status "{spec.meta_str("status")}" ({"|".join(STATUSES)})')
    refs = spec.meta.get("roadmap_refs")
    if not isinstance(refs, list) or not refs:
        err("spec.md", "roadmap_refs is empty: every spec cites the brief or the roadmap")
    for s in SPEC_SECTIONS:
        if s not in spec.sections:
            err("spec.md", f'section "## {s}" is missing')

    for bad in spec.malformed_acs:
        err(
            "spec.md",
            f'criterion without an id or malformed: "{bad}" (format: **AC-{spec.dir_id}-01** — Given …, when …, then …)',
        )
    if AC_SECTION in spec.sections and not spec.acs:
        err("spec.md", "there are no acceptance criteria")
    seen: set[str] = set()
    for ac in spec.acs:
        if not ac.id.startswith(f"AC-{spec.dir_id}-"):
            err("spec.md", f"{ac.id} does not belong to spec {spec.dir_id}")
        if ac.id in seen:
            err("spec.md", f"{ac.id} repeated")
        seen.add(ac.id)
        if not re.search(r"\bwhen\b", ac.text, re.I) or not re.search(r"\bthen\b", ac.text, re.I):
            err("spec.md", f"{ac.id} does not follow the Given / when / then format")
    ac_ids = {a.id for a in spec.acs}

    def unknown_refs(text: str) -> list[str]:
        return [i for i in ac_ids_in(text) if i.startswith(f"AC-{spec.dir_id}-") and i not in ac_ids]

    clarifications = (spec.spec_text + (spec.plan_text or "")).count("[NEEDS CLARIFICATION")
    if clarifications:
        need("spec.md", f"there are {clarifications} [NEEDS CLARIFICATION] marker(s)")
    open_q = [ln for ln in spec.sections.get(QUESTIONS_SECTION, "").split("\n") if re.match(r"^\s*- \[ \]", ln)]
    if open_q:
        need("spec.md", f"there are {len(open_q)} open question(s)")

    if not spec.plan_text or spec.plan_sections is None:
        need("plan.md", "plan.md is missing (/sdd-plan)")
    else:
        for s in PLAN_SECTIONS:
            if s not in spec.plan_sections:
                err("plan.md", f'section "## {s}" is missing')
        strategy = ac_ids_in(spec.plan_sections.get(TEST_STRATEGY_SECTION, ""))
        missing = sorted(i for i in ac_ids if i not in strategy)
        if missing:
            need("plan.md", f"the test strategy does not cover: {', '.join(missing)}")
        for i in unknown_refs(spec.plan_text):
            err("plan.md", f"cites {i}, which does not exist in the spec")
        kb = round(len(spec.plan_text.encode("utf-8")) / 1024)
        if kb > config.PLAN_BUDGET_KB:
            warn("plan.md", f"is {kb} KB (budget {config.PLAN_BUDGET_KB} KB): tasks must cite sections in `Context`")

    if not spec.tasks_text or spec.tasks is None:
        need("tasks.md", "tasks.md is missing (/sdd-tasks)")
    else:
        for line in spec.malformed_tasks:
            err("tasks.md", f'task without an id: "{line}" (format: - [ ] **T01** title)')
        if not spec.tasks:
            need("tasks.md", "there are no tasks")
        task_ids: set[str] = set()
        for t in spec.tasks:
            if t.id in task_ids:
                err("tasks.md", f"{t.id} repeated")
            task_ids.add(t.id)
            for f in TASK_FIELDS:
                if not t.fields.get(f):
                    err("tasks.md", f'{t.id} has no "{f}"')
        covered = {i for t in spec.tasks for i in ac_ids_in(t.fields.get("AC"))}
        missing = sorted(i for i in ac_ids if i not in covered)
        if missing:
            need("tasks.md", f"no task covers: {', '.join(missing)}")
        for i in unknown_refs(spec.tasks_text):
            err("tasks.md", f"cites {i}, which does not exist in the spec")
        _lint_milestones(root, spec, err)

    if spec.meta_str("status") == "approved" and not all(
        spec.meta_str(k) for k in ("approved_hash", "approved_at", "approved_by")
    ):
        err("spec.md", "approved without approved_hash/approved_at/approved_by: approve with python scripts/approve.py")


def _lint_milestones(root: Path, spec: Spec, err: Report) -> None:
    """Milestones and the `Context` of loose tasks are always validated: /sdd-build uses them as they are."""

    def check_context(owner: str, value: str) -> None:
        refs = context_refs(value)
        if not refs:
            err("tasks.md", f'{owner}: "Context" names no sections (format: `plan.md#Title`)')
        for ref in refs:
            _, error = resolve_context_ref(root, spec, ref)
            if error:
                err("tasks.md", f"{owner}: {error}")

    seen: set[str] = set()
    for m in spec.milestones:
        if m.id in seen:
            err("tasks.md", f"{m.id} repeated")
        seen.add(m.id)
        for f in MILESTONE_FIELDS:
            if not m.fields.get(f):
                err("tasks.md", f'{m.id} has no "{f}"')
        if not m.task_ids:
            err("tasks.md", f"{m.id} has no tasks")
        agent = m.fields.get("Agent", "").replace("`", "")
        if agent and agent not in config.BUILD_AGENTS:
            err("tasks.md", f'{m.id}: invalid agent "{agent}" ({"|".join(config.BUILD_AGENTS)})')
        model = m.fields.get("Model", "").replace("`", "")
        if model and model not in config.BUILD_MODELS:
            err("tasks.md", f'{m.id}: invalid model "{model}" ({"|".join(config.BUILD_MODELS)})')
        if m.fields.get("Context"):
            check_context(m.id, m.fields["Context"])
    for t in spec.tasks or []:
        if t.fields.get("Context"):
            check_context(t.id, t.fields["Context"])


def main(argv: list[str]) -> int:
    errors, warnings = lint_specs(root_from_args(argv), strict="--strict" in argv, only=arg_value(argv, "--spec"))
    for w in warnings:
        print(f"[warn] {w}")
    for e in errors:
        print(f"[FAIL] {e}")
    if errors:
        print(f"spec-lint: {len(errors)} error(s)")
        return 1
    print(f"spec-lint: ok ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
