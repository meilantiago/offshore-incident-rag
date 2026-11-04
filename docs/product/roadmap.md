# Roadmap

Each item becomes one spec (`/sdd-spec`). Order matters: each one builds on the previous.

| # | Item | Serves | What it delivers |
|---|---|---|---|
| R1 | Corpus ingestion | brief §3.1, §6 | Manifest of BSEE documents, download with provenance, PDF parsing with page numbers and tables, chunking, storage in Postgres, incremental re-ingestion by content hash. CLI `ingest`. |
| R2 | Hybrid retrieval | brief §3.2 | Embeddings with a local model, pgvector + Postgres full-text search, reciprocal rank fusion, cross-encoder reranking. CLI `search`. First golden set for retrieval (recall@k, MRR) with bootstrap intervals. |
| R3 | Grounded answering | brief §3.3 | LangGraph pipeline: retrieve → grade evidence → rewrite query if needed → generate → verify citations → refuse when unsupported. Provider interface with Ollama by default. CLI `ask`. |
| R4 | Evaluation gate | brief §3.4 | Answer-level metrics (faithfulness, citation precision, correct refusals), baseline storage, paired comparison between configurations, `eval-regression` gate in CI, versioned reports in `eval/reports/`. |
| R5 | Service and operations | brief §3.5 | FastAPI with streaming answers, Docker Compose (API + Postgres + Ollama), structured logs with per-stage latency and token counts, health checks, configuration by environment. |

Later, only if R1–R5 are merged: hosted provider adapters beyond the first one, query analytics, a minimal web page over the API.
