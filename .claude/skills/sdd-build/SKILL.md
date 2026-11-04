---
name: sdd-build
description: Step 5 of the SDD cycle. Implements an approved spec - red commit with the acceptance tests (test-writer), then milestone by milestone with the implementer, verifying gates between milestones.
argument-hint: "<NNN>"
---

# /sdd-build: implement spec $ARGUMENTS

## 0. Preconditions (if one fails, stop and tell the user)
- You are on the `spec/NNN-*` branch.
- The spec is approved and its hash matches: `python scripts/approval_check.py` is green and `docs/specs/STATUS.md` does not show it as `stale`.
- The tree is clean (`git status`) or only has changes of this spec.

## 1. Red commit (only if it does not exist yet in `git log main..HEAD`)
- Delegate to **test-writer**: "write the acceptance tests of spec NNN".
- Check yourself that the tests fail for lack of implementation and that `python scripts/traceability.py` covers every AC.
- Mark T01 as `[x]`, run `python scripts/status.py` and commit: `test(NNN): red acceptance tests for AC-NNN-01..XX`.

## 2. Milestone by milestone, in order
For each milestone with `[ ]` tasks:
1. Delegate to **implementer** (`model` = the milestone's `Model`) with this request and no plan excerpts:
   > Implement milestone HN of spec NNN. Your context comes from `python scripts/context.py NNN HN`: read that output and do not read the whole `plan.md`.

   On a retry, add the output of the gate that failed.
2. Verify yourself (do not trust the agent): run the "Done when" of each task of the milestone and `python scripts/check.py --fast`.
3. Green: mark every task of the milestone `[x]`, run `python scripts/status.py` and commit: `feat(NNN): HN <title> (T02–T07)`.
4. Red: go back to the implementer with the gate output. After two failed attempts, stop and explain to the user what blocks it.
5. If the milestone shows the spec or the plan are wrong: **stop**. Propose the change to the user. Editing `spec.md` or `plan.md` invalidates the hash and the user has to re-approve.

**Loose tasks** (outside milestones, like the T90+ verification fixes): one invocation per task, with `python scripts/context.py NNN T9N`. Commit: `fix(NNN): T9N <title>`.

## 3. Close
When no tasks are open, run `python scripts/check.py --all` and continue with `/sdd-verify NNN`.
