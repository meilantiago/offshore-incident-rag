# offshore-incident-rag

Grounded question answering over public offshore safety reports from the US Bureau of Safety and Environmental Enforcement (BSEE): incident investigations and Safety Alerts.

Ask *"What root causes did BSEE panels find in crane boom failures?"* and get an answer that cites the document and page of every claim, or an explicit statement that the corpus does not support an answer.

> **Status:** under construction. The engineering process and harness are in place; the pipeline is being built spec by spec. See [docs/specs/STATUS.md](docs/specs/STATUS.md) for what is done, with the gates that prove it.

## What it will do

| Stage | Approach |
|---|---|
| Ingestion | Manifest-driven download with provenance (source URL, date, content hash), PDF parsing with page numbers and tables, incremental re-ingestion |
| Retrieval | Hybrid search in Postgres (pgvector + full-text), reciprocal rank fusion, cross-encoder reranking |
| Answering | LangGraph flow: retrieve → grade evidence → rewrite query → generate → verify citations → refuse when unsupported |
| Models | Local open models (Ollama, sentence-transformers) by default, hosted providers behind the same interface |
| Evaluation | Frozen human-curated golden set; recall@k, MRR, faithfulness, correct-refusal rate; bootstrap confidence intervals and paired tests between configurations; regression gate in CI |
| Service | FastAPI with streaming, Docker Compose, structured logs with per-stage latency and token counts |

The roadmap is in [docs/product/roadmap.md](docs/product/roadmap.md) and the stack decision in [ADR-0001](docs/adr/0001-stack.md).

## How it is built

The repository is developed with spec-driven development and a Claude Code harness:

1. Every change starts as a spec with numbered acceptance criteria (`AC-NNN-XX`), a technical plan and small tasks.
2. A person approves spec + plan; the approval stores a hash, so any later change to the contract invalidates it.
3. Acceptance tests are written first, from the spec, and committed red. Implementation happens milestone by milestone.
4. "Done" is decided by deterministic gates (`python scripts/check.py --all`): spec structure, approval hashes, AC → test traceability, secrets scan, ruff, mypy strict, pytest, and the evaluation regression gate.
5. Reviewer agents return findings, never approvals; a person merges.

Hooks enforce the rules the process depends on: agents cannot approve specs, edit the golden evaluation set, push to `main` or finish a turn with red gates. Details in [docs/workflow.md](docs/workflow.md) and [docs/constitution.md](docs/constitution.md).

## Development

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python scripts/check.py --all
```

Integration tests need Postgres with pgvector. Start it with `docker compose up -d db` and point the tests at it:

```bash
export TEST_DATABASE_URL=postgresql://rag:rag@localhost:5432/rag   # PowerShell: $env:TEST_DATABASE_URL = "..."
offshore-rag db migrate                                            # needs DATABASE_URL (see .env.example)
```

Each test gets its own schema, so they never touch your data. CI runs the same image as a service container.

## Data

BSEE reports are works of the US federal government. The raw corpus is downloaded by the pipeline and never committed; the repository holds the manifest that rebuilds it.

## License

MIT
