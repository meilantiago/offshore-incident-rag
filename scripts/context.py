"""Just-enough context to implement a milestone or a loose task.

Prints its tasks, the ACs they cite and the sections named in its `Context`, so the agent does not read the whole plan.

    python scripts/context.py NNN H1
    python scripts/context.py NNN T90
"""

from __future__ import annotations

import sys
from pathlib import Path

from lib.repo import root_from_args
from lib.specs import ac_ids_in, context_refs, load_specs, resolve_context_ref


def build_context(root: Path, spec_id: str, unit: str) -> tuple[str | None, str | None]:
    """Returns (text, error)."""
    spec = next((s for s in load_specs(root) if s.dir_id == spec_id), None)
    if spec is None:
        return None, f"spec {spec_id} does not exist"
    if spec.tasks is None:
        return None, f"{spec.rel_dir} has no tasks.md"

    milestone = next((m for m in spec.milestones if m.id == unit), None)
    tasks = [t for t in spec.tasks if (t.id in milestone.task_ids if milestone else t.id == unit)]
    if not tasks:
        return None, f"{unit} is neither a milestone nor a task of {spec.rel_dir}/tasks.md"

    context_field = milestone.fields.get("Context") if milestone else tasks[0].fields.get("Context")
    ac_ids = {i for t in tasks for i in ac_ids_in(t.fields.get("AC"))}
    out: list[str] = []
    if milestone:
        out.append(f"# {milestone.id} — {milestone.title} (spec {spec_id})")
        out.append(f"Agent: {milestone.fields.get('Agent')} · Model: {milestone.fields.get('Model')}")
    else:
        out.append(f"# {tasks[0].id} — {tasks[0].title} (spec {spec_id})")
    out += ["", f"## Tasks ({spec.rel_dir}/tasks.md)", "", *(t.raw for t in tasks)]
    out += ["", f"## Acceptance criteria ({spec.rel_dir}/spec.md)", ""]
    out += [f"- **{ac.id}** — {ac.text}" for ac in spec.acs if ac.id in ac_ids]

    errors: list[str] = []
    refs = context_refs(context_field)
    if refs:
        out += ["", "## Context"]
    for ref in refs:
        text, error = resolve_context_ref(root, spec, ref)
        if error:
            errors.append(error)
        else:
            out += ["", f"<!-- {ref.ref} -->", text or ""]
    if not refs:
        out += ["", f"(no `Context`: read only the sections of {spec.rel_dir}/plan.md you need)"]
    if errors:
        return None, "\n".join(errors)
    return "\n".join(out) + "\n", None


def main(argv: list[str]) -> int:
    positional = [a for i, a in enumerate(argv[1:], 1) if not a.startswith("--") and argv[i - 1] != "--root"]
    if len(positional) < 2:
        print("usage: python scripts/context.py NNN H1|T90", file=sys.stderr)
        return 2
    text, error = build_context(root_from_args(argv), positional[0], positional[1])
    if error:
        print(f"context: {error}", file=sys.stderr)
        return 1
    sys.stdout.write(text or "")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
