---
name: sdd-spec
description: Step 1 of the SDD cycle. Drafts a new spec (spec.md) from a roadmap item with the spec-writer agent. Use when the user wants to start a new piece of functionality.
argument-hint: "<idea or roadmap item>"
---

# /sdd-spec: draft a spec

Request: $ARGUMENTS

1. If the request is not in `docs/product/roadmap.md` and serves no section of `docs/product/brief.md`, tell the user and ask before going on (constitution §1).
2. Create the branch `spec/NNN-slug` from an up-to-date `main`, unless you are already on it. NNN is the next free number in `docs/specs/`.
3. Delegate to **spec-writer** with the request, the number and the slug. Pass along the decisions the user already took in this conversation.
4. When it returns, run `python scripts/spec_lint.py --spec NNN` and `python scripts/status.py`.
5. Show the user:
   - the ACs, one per line;
   - the **open questions**, which the user answers (use AskUserQuestion when they are multiple choice);
   - the decisions the agent took that deserve a review.
6. With the answers, update the spec (mark questions as `- [x] … → answer`) and commit: `docs(NNN): draft spec`.

Next step: `/sdd-plan NNN`. Nothing is approved in this step.
