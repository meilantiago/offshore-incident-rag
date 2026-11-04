# offshore-incident-rag

Question answering over public offshore safety reports (BSEE incident investigations and Safety Alerts), with citations to document and page, refusal when the corpus does not support an answer, and quality measured on a frozen evaluation set. Built spec-first with an agent harness.

## Sources of truth
| What | Where |
|---|---|
| Scope | [docs/product/brief.md](docs/product/brief.md) and [docs/product/roadmap.md](docs/product/roadmap.md): if it is not there, it is not built |
| Non-negotiable rules | [docs/constitution.md](docs/constitution.md) |
| How work is done | [docs/workflow.md](docs/workflow.md) |
| Domain terms | [docs/glossary.md](docs/glossary.md): use these names in code |
| Spec status | [docs/specs/STATUS.md](docs/specs/STATUS.md) (generated) |
| Technical decisions | [docs/adr/](docs/adr/) |
| Gates and paths | [scripts/harness_config.py](scripts/harness_config.py) |

## The cycle (spec-driven)
`/sdd-spec` → `/sdd-plan` → `/sdd-tasks` → **the user approves** (`python scripts/approve.py NNN`) → `/sdd-build` → `/sdd-verify` → `/sdd-ship` → **the user merges**. `/sdd-status` shows where every spec stands.

No product change happens outside this cycle. Harness changes (scripts, hooks, agents, process docs) go on `harness/<topic>` branches, also through a PR.

## Golden rules
1. **"Done" = `python scripts/check.py --all` green.** Do not say "done", "approved" or "works" without the gate output that shows it. If you could not verify something, say so.
2. **You never approve specs or merge.** Do not write `status: approved` or the `approved_*` fields, do not run `approve.py`, do not push to `main`. The hooks block it; the rule holds even when they do not.
3. **Every AC has a test** carrying its id (`AC-NNN-XX`). Acceptance tests are written first, from the spec, and are never weakened.
4. **Cited or silent.** No answer reaches the user without citations to retrieved chunks; no support means a refusal.
5. **The golden set is human-curated.** Never edit `eval/golden/`; propose items in `eval/candidates/`. Golden questions never go into prompts.
6. **Nothing fake in `src/`**: no mocks, placeholder providers or swallowed exceptions. Test doubles live in `tests/`.
7. **Secrets out of the repo.** Only `.env.example`.
8. If the spec or the plan is wrong, **stop and ask**. Do not improvise scope.

## Commands
```
python -m venv .venv && .venv/Scripts/activate      # Windows (bin/activate on Linux/macOS)
pip install -e ".[dev]"
python scripts/check.py --all                       # every gate (same as CI)
python scripts/check.py --fast                      # fast gates
python scripts/spec_lint.py --spec NNN [--strict]
python scripts/traceability.py [--md NNN]           # AC → test coverage
python scripts/status.py                            # regenerates docs/specs/STATUS.md
python scripts/context.py NNN H1                    # just-enough context for a milestone
```

## Stack
Proposed in [ADR-0001](docs/adr/0001-stack.md): Python 3.11, Postgres + pgvector (hybrid retrieval), LangGraph (answering flow), local open models through Ollama and sentence-transformers behind provider interfaces, FastAPI for the service.

| Where | What |
|---|---|
| `src/offshore_rag/` | The package. Prompts in `prompts/`, never inline. |
| `tests/` | pytest. Markers: `integration` (needs Postgres), `llm` (needs a real model, local only). |
| `eval/` | `golden/` (human-curated, frozen), `candidates/`, `thresholds.toml`, `reports/`. |
| `data/` | Downloaded corpus. Ignored by git; rebuilt from the manifest. |
| `scripts/` | The harness: gates, approval, status, traceability. |
| `.claude/` | Agents, skills and hooks of the harness. |
