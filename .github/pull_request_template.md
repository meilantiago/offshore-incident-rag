## Spec

<!-- Link to docs/specs/NNN-slug/spec.md. Harness changes say "harness" and explain why. -->

## Summary

<!-- Three lines: what changes for the user or the operator. -->

## AC → test matrix

<!-- Paste the output of: python scripts/traceability.py --md NNN (never write it by hand). -->

## Gates

<!-- Paste the [ok]/[FAIL] lines and the summary of: python scripts/check.py --all -->

## Evaluation

<!-- If retrieval, prompts or models changed: summary of the latest report in eval/reports/ (metric, CI, paired test against the baseline). Otherwise "not affected". -->

## Review

- Discarded findings and why:
- Low-severity debt left:
- New or changed ADRs:

## For the reviewer

- [ ] I read the spec and the ACs cover what I want.
- [ ] Every answer path cites evidence or refuses.
- [ ] CI is green.
