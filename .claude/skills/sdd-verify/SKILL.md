---
name: sdd-verify
description: Step 6 of the SDD cycle. Verifies an implemented spec with every gate, AC -> test traceability and the reviewers (reviewer always; eval-auditor when the branch touches retrieval, prompts, models or eval/). Confirmed findings become fix tasks.
argument-hint: "<NNN>"
---

# /sdd-verify: verify spec $ARGUMENTS

1. Run `python scripts/check.py --all`. Anything red is already a fix task; no reviewer needs to find it.
2. Decide the reviewers from `git diff --name-only main...HEAD`:
   - **reviewer** always;
   - **eval-auditor** if the diff touches `src/offshore_rag/retrieval/`, `src/offshore_rag/generation/`, `src/offshore_rag/prompts/`, `src/offshore_rag/evaluation/` or `eval/`.

   Launch them **in parallel** (one message), each with: "review branch `spec/NNN-*` against `main` for spec NNN". Do not give them your opinion about the code, only the scope.
3. With the findings:
   - Discard those that do not hold, by reading the code. Write down why.
   - Confirm the doubtful ones (run the test or the scenario).
   - Every **confirmed** medium or high finding goes to `tasks.md` under `## Verification fixes` as `- [ ] **T9N**`, with AC, Files, Test first (the test that would have caught it), Done when and, if needed, `Context`.
   - Low-severity findings do not become tasks: they go to the debt list in step 5.
4. If you added tasks, go back to `/sdd-build NNN` and then repeat this step reviewing only the diff of the fixes.
5. When `check --all` is green and no confirmed findings are open, show the user:
   - the matrix `python scripts/traceability.py --md NNN`;
   - which reviewers ran and why;
   - the discarded findings with their reason;
   - the low-severity debt.

   Continue with `/sdd-ship NNN`.

Neither you nor the reviewers declare the spec "approved" or "production ready": the evidence is the gate output, and the merge belongs to the user.
