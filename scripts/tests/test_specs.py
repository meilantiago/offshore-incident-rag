"""spec-lint, approval hash, approval gate, traceability, status and context."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from approval_check import check_approvals
from approve import approve_spec
from conftest import git, write
from context import build_context
from lib.specs import approval_hash, derive_status, load_specs, parse_tasks
from spec_lint import lint_specs
from status import render_status
from traceability import render_matrix, trace_coverage

SPEC_MD = "docs/specs/001-corpus-ingestion/spec.md"
PLAN_MD = "docs/specs/001-corpus-ingestion/plan.md"


def _approve(root: Path) -> None:
    result = approve_spec(root, "001", "Harness Test", today=dt.date(2026, 11, 4))
    assert result.ok, result.errors


def test_complete_draft_lints_clean_in_strict_mode(spec_root: Path) -> None:
    errors, _ = lint_specs(spec_root, strict=True)
    assert errors == []


def test_malformed_ac_and_missing_sections_are_errors(spec_root: Path) -> None:
    spec = spec_root / SPEC_MD
    text = spec.read_text(encoding="utf-8")
    text = text.replace("- **AC-001-02** — Given an unchanged document", "- AC-001-02 — Given an unchanged document")
    text = text.replace("## Metrics\nDocuments per minute.\n", "")
    spec.write_text(text, encoding="utf-8")
    errors, _ = lint_specs(spec_root)
    assert any("malformed" in e for e in errors)
    assert any('"## Metrics" is missing' in e for e in errors)


def test_ac_without_when_then_is_an_error(spec_root: Path) -> None:
    spec = spec_root / SPEC_MD
    spec.write_text(
        spec.read_text(encoding="utf-8").replace(
            "Given a manifest, when ingest runs, then every document is stored with its hash.",
            "Documents are stored.",
        ),
        encoding="utf-8",
    )
    errors, _ = lint_specs(spec_root)
    assert any("AC-001-01 does not follow" in e for e in errors)


def test_open_question_warns_in_draft_and_fails_in_strict(spec_root: Path) -> None:
    spec = spec_root / SPEC_MD
    spec.write_text(spec.read_text(encoding="utf-8") + "- [ ] Which chunk size?\n", encoding="utf-8")
    errors, warnings = lint_specs(spec_root)
    assert not errors and any("open question" in w for w in warnings)
    strict_errors, _ = lint_specs(spec_root, strict=True)
    assert any("open question" in e for e in strict_errors)


def test_test_strategy_must_cover_every_ac_in_strict_mode(spec_root: Path) -> None:
    plan = spec_root / PLAN_MD
    text = plan.read_text(encoding="utf-8").replace("| AC-001-02 | integration | test_reingest |\n", "")
    plan.write_text(text, encoding="utf-8")
    errors, _ = lint_specs(spec_root, strict=True)
    assert any("test strategy does not cover: AC-001-02" in e for e in errors)


def test_milestone_context_must_point_to_an_existing_section(spec_root: Path) -> None:
    tasks = spec_root / "docs/specs/001-corpus-ingestion/tasks.md"
    tasks.write_text(tasks.read_text(encoding="utf-8").replace("#Documents table", "#Nope"), encoding="utf-8")
    errors, _ = lint_specs(spec_root)
    assert any('has no section "Nope"' in e for e in errors)


def test_approval_writes_hash_and_any_later_edit_makes_it_stale(spec_root: Path) -> None:
    _approve(spec_root)
    spec = load_specs(spec_root)[0]
    assert spec.meta_str("status") == "approved"
    assert spec.meta_str("approved_hash") == approval_hash(spec)
    assert derive_status(spec, set()) == "approved"

    plan = spec_root / PLAN_MD
    plan.write_text(plan.read_text(encoding="utf-8") + "\nScope creep.\n", encoding="utf-8")
    spec = load_specs(spec_root)[0]
    assert derive_status(spec, set()) == "stale"
    errors, _ = check_approvals(spec_root)
    assert any("changed after approval" in e for e in errors)


def test_editing_tasks_does_not_invalidate_approval(spec_root: Path) -> None:
    _approve(spec_root)
    tasks = spec_root / "docs/specs/001-corpus-ingestion/tasks.md"
    tasks.write_text(tasks.read_text(encoding="utf-8").replace("- [ ] **T01**", "- [x] **T01**"), encoding="utf-8")
    spec = load_specs(spec_root)[0]
    assert derive_status(spec, set()) == "in-progress"


def test_approval_is_refused_while_lint_fails(spec_root: Path) -> None:
    (spec_root / PLAN_MD).unlink()
    result = approve_spec(spec_root, "001", "Harness Test")
    assert not result.ok
    assert any("plan.md is missing" in e for e in result.errors)


def test_trace_requires_a_test_per_ac_of_approved_specs(spec_root: Path) -> None:
    _approve(spec_root)
    write(spec_root, "tests/test_ingest.py", 'def test_ac_001_01():\n    """AC-001-01"""\n')
    cov = trace_coverage(spec_root)
    assert cov.errors == ["AC-001-02 (docs/specs/001-corpus-ingestion) has no test"]
    assert "**no test**" in render_matrix(cov, "001")


def test_trace_rejects_tests_citing_unknown_acs(spec_root: Path) -> None:
    write(spec_root, "tests/test_x.py", 'def test_x():\n    """AC-001-09"""\n')
    cov = trace_coverage(spec_root)
    assert any("AC-001-09 does not exist" in e for e in cov.errors)


def test_done_needs_every_task_closed_and_every_ac_tested(spec_root: Path) -> None:
    _approve(spec_root)
    tasks = spec_root / "docs/specs/001-corpus-ingestion/tasks.md"
    tasks.write_text(tasks.read_text(encoding="utf-8").replace("- [ ]", "- [x]"), encoding="utf-8")
    write(spec_root, "tests/test_ingest.py", '"""AC-001-01 AC-001-02"""\n')
    assert "| done |" in render_status(spec_root)


def test_product_code_on_a_non_spec_branch_fails_the_approval_gate(git_root: Path) -> None:
    git(git_root, "checkout", "-q", "-b", "feature/x")
    write(git_root, "src/offshore_rag/x.py", "X = 1\n")
    errors, _ = check_approvals(git_root, branch="feature/x")
    assert any("not a spec/NNN-* branch" in e for e in errors)


def test_product_code_on_a_draft_spec_branch_fails_until_approved(git_root: Path) -> None:
    git(git_root, "checkout", "-q", "-b", "spec/001-corpus-ingestion")
    write(git_root, "src/offshore_rag/x.py", "X = 1\n")
    errors, _ = check_approvals(git_root, branch="spec/001-corpus-ingestion")
    assert any("is not approved" in e for e in errors)
    _approve(git_root)
    errors, _ = check_approvals(git_root, branch="spec/001-corpus-ingestion")
    assert errors == []


def test_context_prints_only_the_cited_section(spec_root: Path) -> None:
    text, error = build_context(spec_root, "001", "H1")
    assert error is None and text is not None
    assert "### Documents table" in text
    assert "## Risks" not in text
    assert "AC-001-01" in text


def test_task_parser_reads_fields() -> None:
    tasks, malformed = parse_tasks("- [x] **T01** Red\n  - AC: AC-001-01\n  - Done when: green\n- [ ] no id\n")
    assert malformed == ["- [ ] no id"]
    assert tasks[0].done and tasks[0].fields == {"AC": "AC-001-01", "Done when": "green"}
