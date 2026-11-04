---
name: sdd-plan
description: Step 2 of the SDD cycle. Writes plan.md for a spec (design, data model, contracts, test strategy, evaluation impact) and the ADRs it needs.
argument-hint: "<NNN>"
---

# /sdd-plan: technical plan for spec $ARGUMENTS

1. Check that you are on `spec/NNN-*` and that `spec.md` has no open questions that block the design. If it does, resolve them with the user first.
2. Read the spec, `docs/constitution.md`, the ADRs in `docs/adr/` and the code you are going to touch. Reuse what exists and name it with its path.
3. Write `plan.md` from `docs/specs/_templates/plan.md`:
   - **Design**: the end-to-end path (CLI/API → pipeline stage → storage). The minimum that satisfies the ACs, without over-generalizing.
   - **Data model**: tables, columns, indexes and migrations. Each change is a small migration that applies on a clean database.
   - **Contracts**: function and HTTP interfaces, inputs, outputs and errors. External dependencies (model provider, database) sit behind interfaces.
   - **Test strategy**: one row per AC with the layer (unit, integration against real Postgres, `llm`-marked, evaluation) and the test. Every AC must appear: `spec_lint` checks it.
   - **Evaluation impact**: whether the change can move retrieval or answer metrics, and which evaluation runs before merging (or "none").
   - **Risks**, and **ADRs**: a decision with real alternatives (library, model, store) gets `docs/adr/NNNN-title.md` from the template, with status `proposed`. The user accepts it when approving the plan.
   - Short, stable `###` headings: tasks cite plan sections by their exact heading. The plan has a 40 KB budget; do not repeat the spec.
4. Run `python scripts/spec_lint.py --spec NNN`.
5. Show the user: the design in 5 lines, the proposed ADRs, the evaluation impact and the decisions that are theirs.
6. Commit: `docs(NNN): technical plan`.

Next step: `/sdd-tasks NNN`.
