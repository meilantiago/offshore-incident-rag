# ADR-0001: Base stack

- **Status:** accepted (2026-11-04, with spec 001)
- **Date:** 2026-11-04
- **Originating spec:** — (repository bootstrap)
- **Decided by:** Tiago Meilan

## Context
The system has to run end to end on a modest workstation (NVIDIA GTX 1650 with 4 GB of VRAM, 16 GB of RAM), with no paid API keys, and still be deployable as a service. It must be testable in CI without a GPU. The pipeline needs lexical and semantic search, provenance per document and an orchestration layer for the multi-step answering flow.

## Options considered

### Language and tooling
- **Python 3.11+** with `ruff` (format + lint), `mypy --strict` on `src/` and `pytest`. The RAG and evaluation ecosystem is Python-first.

### Storage and retrieval
- **A: Postgres 16 + pgvector + built-in full-text search.** One database for documents, chunks, embeddings and lexical index; hybrid search in SQL; transactional re-ingestion; runs in Docker and in CI as a service container.
- B: Qdrant + a separate BM25 index. Good native hybrid search, but two stores to keep consistent and a second service to operate.
- C: FAISS / Chroma in-process. Simple, but no transactional metadata store and weak story for a multi-process service.

### Orchestration
- **A: LangGraph** for the answering flow (retrieve → grade → rewrite → generate → verify citations → refuse). Explicit state machine, testable nodes, conditional edges and retries.
- B: Plain Python functions. Full control, but conditional loops and tracing have to be rebuilt by hand.

### Models
- **Embeddings and reranker:** local open models through `sentence-transformers` (a small English embedding model and a cross-encoder), which fit in 4 GB of VRAM and also run on CPU in CI.
- **Generator:** an `LLMProvider` interface. Default implementation: **Ollama** with a small open instruction model (3B-class) that fits in 4 GB of VRAM. A hosted provider (for example Gemini on its free tier) can be added behind the same interface and selected by environment variable. *Open: confirm whether the hosted adapter is in scope for R3 or later.*

### Service
- **FastAPI** + `uvicorn`, configuration with `pydantic-settings`, structured JSON logs with `structlog`, Docker Compose for API + Postgres + Ollama.

## Decision
Python 3.11, Postgres + pgvector for storage and hybrid retrieval, LangGraph for orchestration, local open models by default behind provider interfaces, FastAPI for the service. Each roadmap spec pins the exact libraries and model names it introduces, with a follow-up ADR when there are real alternatives.

## Consequences
- One database to run and back up; integration tests need a real Postgres (Docker locally, a service container in CI).
- CI never needs a GPU or an API key: tests use the deterministic test provider in `tests/`; tests marked `llm` run only locally.
- Quality depends on small local models; the evaluation gate makes the trade-off visible, and a hosted provider can be compared on the same golden set.
- Revisit if the corpus grows past what a single Postgres instance serves within the latency budget, or if a 3B-class model cannot reach the faithfulness threshold.
