---
name: sdd-tasks
description: Step 3 of the SDD cycle. Splits the plan of a spec into small ordered tasks (tasks.md), test first, and leaves the spec ready for human approval.
argument-hint: "<NNN>"
---

# /sdd-tasks: tasks for spec $ARGUMENTS

1. Read `spec.md` and `plan.md`.
2. Write `tasks.md` from `docs/specs/_templates/tasks.md`:
   - **T01 is always "Red acceptance tests"**, with every AC.
   - Then small tasks (ideally under ~200 lines of diff each), in dependency order: storage and schemas first, then pipeline stages, then interfaces (CLI/API).
   - Every task has `AC`, `Files`, `Test first` and `Done when`. "Done when" is a command that can be run, not an opinion.
   - **Group tasks into milestones** (`## H1 — Title`): each milestone is one agent invocation in `/sdd-build` and one commit. 2 to 5 milestones per spec, no more than ~6 tasks per milestone.
   - Each milestone has:
     - `Agent`: `implementer`.
     - `Model`: `opus` for retrieval, ranking, grounding and evaluation logic; `sonnet` for plumbing, CLI, API, configuration and CI; `haiku` only for mechanical work (docs, renames).
     - `Context`: the exact sections the agent needs, in backticks, by heading text: `plan.md#Data model`. What is not cited is not read: pick the minimum that is enough. `python scripts/context.py NNN HN` shows what the agent will receive.
   - Every AC must be covered by some task.
   - If there are more than ~15 tasks, propose splitting the spec.
3. Run `python scripts/spec_lint.py --spec NNN --strict`. It must give **zero errors**: it is the same validation approval runs.
4. Run `python scripts/status.py` and commit: `docs(NNN): tasks`.
5. Tell the user, verbatim:
   > Spec NNN is ready for your review: `docs/specs/NNN-slug/spec.md` and `plan.md`. If you agree, approve it in a terminal with `python scripts/approve.py NNN` and then ask me for `/sdd-build NNN`.

**Never** approve yourself: the `guard_bash` hook blocks it, and it is the rule anyway.
