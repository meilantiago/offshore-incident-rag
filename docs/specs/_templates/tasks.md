# NNN — Tasks

Small, ordered tasks grouped in milestones. Each milestone is one invocation of its agent in `/sdd-build` and one commit. A task is closed (`[x]`) only when its "Done when" is green. The red commit with the acceptance tests is always first, outside the milestones.

- [ ] **T01** Red acceptance tests
  - AC: AC-NNN-01, AC-NNN-02
  - Files: <test paths>
  - Test first: the tests themselves (written by `test-writer` from the spec)
  - Done when: the tests run and fail for lack of implementation, not because of syntax errors

## H1 — <milestone title>
- Agent: implementer
- Model: sonnet
- Context: `plan.md#Data model` `plan.md#Contracts`

- [ ] **T02** <title>
  - AC: AC-NNN-01
  - Files: <paths>
  - Test first: <which unit or integration test is written before>
  - Done when: `python scripts/check.py --fast` green and <test> green

## Verification fixes
Confirmed findings from `/sdd-verify`, as loose T90+ tasks. Each may carry its own `Context`.
