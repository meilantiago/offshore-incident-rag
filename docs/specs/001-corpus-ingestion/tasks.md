# 001 — Tasks

Small, ordered tasks grouped in milestones. Each milestone is one invocation of its agent in `/sdd-build` and one commit. A task is closed (`[x]`) only when its "Done when" is green. The red commit with the acceptance tests is always first, outside the milestones.

Integration tests need Postgres: `docker compose up -d db` and `TEST_DATABASE_URL` set (see `.env.example`).

- [x] **T01** Red acceptance tests and test infrastructure
  - AC: AC-001-01, AC-001-02, AC-001-03, AC-001-04, AC-001-05, AC-001-06, AC-001-07, AC-001-08, AC-001-09, AC-001-10, AC-001-11, AC-001-12
  - Files: `tests/ingestion/test_*.py` (one file per row of `plan.md#Test strategy`), `tests/support/http_server.py`, `tests/support/pdfs.py`, `tests/conftest.py` (postgres fixture with a fresh schema per test), `tests/fixtures/bsee/` (trimmed listing and detail HTML, one small Safety Alert PDF without third-party images, `SOURCES.md`), `docker-compose.yml` (service `db`, image `pgvector/pgvector:pg16`), `pyproject.toml` (dev extras `fpdf2`, `pytest-timeout`), `.env.example` (`TEST_DATABASE_URL`)
  - Test first: the tests themselves, written by `test-writer` from the spec and `plan.md#Contracts`
  - Done when: `python -m pytest tests -q` runs every acceptance test and each fails for lack of `offshore_rag` modules or behaviour (ImportError / assertion), not for syntax, fixture or infrastructure errors; `python scripts/traceability.py` lists all 12 ACs as covered

## H1 — Foundations: configuration, database and CI
- Agent: implementer
- Model: sonnet
- Context: `plan.md#Configuration` `plan.md#Logging` `plan.md#New dependencies` `plan.md#Migrations` `plan.md#Tables` `plan.md#Package layout`

- [x] **T02** Runtime dependencies, settings and logging
  - AC: AC-001-04, AC-001-12
  - Files: `pyproject.toml`, `src/offshore_rag/config.py`, `src/offshore_rag/logging.py`, `tests/unit/test_config.py`
  - Test first: `tests/unit/test_config.py` — defaults (rate 1.0, retries 4, User-Agent with the repo URL and no `@`), overrides from environment, `DATABASE_URL` rendered without password
  - Done when: `python -m pytest tests/unit/test_config.py -q` green and `python scripts/check.py --fast` green

- [x] **T03** Database connection and migrations
  - AC: AC-001-12
  - Files: `src/offshore_rag/db/connection.py`, `src/offshore_rag/db/migrate.py`, `src/offshore_rag/db/migrations/0001_corpus.sql`, `tests/unit/test_migrate.py`
  - Test first: `tests/unit/test_migrate.py` (integration) — migrate on an empty schema creates the three tables with their checks; running it twice is a no-op; `pending_migrations` is empty afterwards and non-empty on a fresh schema; unreachable host raises `DatabaseUnavailable` whose message has no password
  - Done when: `python -m pytest tests/unit/test_migrate.py -q` green and `python scripts/check.py --fast` green

- [x] **T04** CLI skeleton with `db migrate`, and Postgres in CI
  - AC: AC-001-12
  - Files: `src/offshore_rag/cli.py`, `pyproject.toml` (`[project.scripts] offshore-rag`), `.github/workflows/ci.yml` (service `pgvector/pgvector:pg16`, `TEST_DATABASE_URL`), `README.md` (development section: `docker compose up -d db`)
  - Test first: `tests/unit/test_cli_migrate.py` — `offshore-rag db migrate` via `typer.testing.CliRunner` applies migrations and exits 0; with an unreachable database exits 1 and names host/port/db without the password
  - Done when: `python -m pytest tests/unit/test_cli_migrate.py -q` green and `python scripts/check.py --fast` green

## H2 — Manifest and polite download
- Agent: implementer
- Model: sonnet
- Context: `plan.md#Manifest building` `plan.md#Manifest format` `plan.md#HTTP` `plan.md#Package layout` `plan.md#Test infrastructure`

- [x] **T05** Manifest load, validation and deterministic write
  - AC: AC-001-01, AC-001-02
  - Files: `src/offshore_rag/ingestion/manifest.py`, `tests/unit/test_manifest.py`
  - Test first: `tests/unit/test_manifest.py` — each malformed variant (missing URL, unknown type, duplicate URL, empty file) raises `ManifestError` naming the line and URL; `write_manifest` output is sorted, UTF-8, `\n`, byte-identical across calls
  - Done when: `python -m pytest tests/unit/test_manifest.py -q` green and `python scripts/check.py --fast` green

- [x] **T06** PoliteClient: User-Agent, rate limit, retries, conditional requests, robots.txt
  - AC: AC-001-04
  - Files: `src/offshore_rag/ingestion/http.py`, `tests/unit/test_http_client.py`
  - Test first: `tests/unit/test_http_client.py` — with an injected clock and sleep: spacing ≥ 1/rate, backoff on 429/503 with `Retry-After`, no retry on 404, `If-None-Match` sent and 304 surfaced, robots.txt disallow honoured
  - Done when: `python -m pytest tests/unit/test_http_client.py tests/ingestion/test_polite_client.py -q` green and `python scripts/check.py --fast` green

- [x] **T07** Listing parsers, `build_manifest` and `offshore-rag build-manifest`
  - AC: AC-001-01
  - Files: `src/offshore_rag/ingestion/listings.py`, `src/offshore_rag/ingestion/build.py`, `src/offshore_rag/cli.py`, `tests/unit/test_listings.py`
  - Test first: `tests/unit/test_listings.py` — each parser on the recorded fixture HTML returns the expected links, resolves relative district links, and a page with no rows returns an empty list
  - Done when: `python -m pytest tests/unit/test_listings.py tests/ingestion/test_manifest_build.py -q` green and `python scripts/check.py --fast` green

## H3 — Page-accurate parsing and chunking
- Agent: implementer
- Model: opus
- Context: `plan.md#Parsing` `plan.md#Chunking` `plan.md#PDF` `plan.md#Chunker interface`

- [x] **T08** `parse_pdf` with pypdfium2 and image-only detection
  - AC: AC-001-05, AC-001-06, AC-001-10
  - Files: `src/offshore_rag/ingestion/pdf.py`, `tests/unit/test_pdf.py`
  - Test first: `tests/unit/test_pdf.py` — synthetic N-page PDF gives N pages, page k holds marker k only; image-only PDF gives pages flagged `image_only`; corrupt bytes raise `PdfParseError`; text is NFC with `\n` line endings
  - Done when: `python -m pytest tests/unit/test_pdf.py -q` green and `python scripts/check.py --fast` green

- [x] **T09** `Chunker` interface and `FixedWordChunker(size=250, overlap=40)`
  - AC: AC-001-06, AC-001-07
  - Files: `src/offshore_rag/ingestion/chunking.py`, `tests/unit/test_chunking_unit.py`
  - Test first: `tests/unit/test_chunking_unit.py` — page ranges from the offset map are correct when a window spans pages; no empty chunks; every text page covered; image-only pages produce no chunks; overlap is exactly `overlap` words; `chunkers_from_config` builds the configured list
  - Done when: `python -m pytest tests/unit/test_chunking_unit.py -q` green and `python scripts/check.py --fast` green

## H4 — Store, ingestion run, report and `ingest` command
- Agent: implementer
- Model: opus
- Context: `plan.md#Ingestion run` `plan.md#Change detection` `plan.md#Raw files` `plan.md#Replacement` `plan.md#Store` `plan.md#Run and outcomes` `plan.md#CLI and exit codes`

- [x] **T10** `CorpusStore` with atomic insert and replacement
  - AC: AC-001-03, AC-001-08, AC-001-09
  - Files: `src/offshore_rag/ingestion/store.py`, `tests/unit/test_store.py`
  - Test first: `tests/unit/test_store.py` (integration) — insert then replace keeps one row per URL and removes old pages and chunks; an exception raised mid-transaction leaves the previous version byte-identical; `counts()` matches the rows
  - Done when: `python -m pytest tests/unit/test_store.py -q` green and `python scripts/check.py --fast` green

- [x] **T11** `run_ingest`: download, change detection, raw files, failure isolation
  - AC: AC-001-03, AC-001-06, AC-001-08, AC-001-09, AC-001-10
  - Files: `src/offshore_rag/ingestion/pipeline.py`, `tests/unit/test_pipeline.py`
  - Test first: `tests/unit/test_pipeline.py` — outcome per document for 304, same-hash 200, changed bytes, `hash_mismatch`, 404 on an already stored document (kept), corrupt PDF (stage `parse`); raw file saved as `data/raw/<sha256>.pdf`
  - Done when: `python -m pytest tests/unit/test_pipeline.py tests/ingestion/test_ingest_provenance.py tests/ingestion/test_reingest.py tests/ingestion/test_image_only.py tests/ingestion/test_chunking.py tests/ingestion/test_pdf_pages.py -q` green and `python scripts/check.py --fast` green

- [x] **T12** Ingestion report and stdout summary
  - AC: AC-001-11
  - Files: `src/offshore_rag/ingestion/report.py`, `tests/unit/test_report.py`
  - Test first: `tests/unit/test_report.py` — JSON has every count, failures with URL/stage/reason, per-stage durations, bytes, requests and retries, image-only share and chunk size min/median/max; `format_summary` shows the same numbers
  - Done when: `python -m pytest tests/unit/test_report.py -q` green and `python scripts/check.py --fast` green

- [x] **T13** `offshore-rag ingest`: validation, fatal checks and exit codes
  - AC: AC-001-02, AC-001-10, AC-001-11, AC-001-12
  - Files: `src/offshore_rag/cli.py`, `tests/unit/test_cli_ingest.py`
  - Test first: `tests/unit/test_cli_ingest.py` — invalid manifest exits 1 before any request; unmigrated or unreachable database exits 1 before any request; partial failure exits 3; full success exits 0; report path printed
  - Done when: `python -m pytest tests -q` green (all acceptance tests) and `python scripts/check.py --all` green

## Verification fixes
Confirmed findings from `/sdd-verify`, as loose T90+ tasks. Each may carry its own `Context`.

- [x] **T90** A malformed `DATABASE_URL` is a clean fatal error that never prints the password
  - AC: AC-001-12
  - Files: `src/offshore_rag/config.py`, `src/offshore_rag/db/connection.py`, `tests/ingestion/test_fatal_db.py`
  - Test first: `tests/ingestion/test_fatal_db.py` — with `DATABASE_URL=rag:SECRETPW@localhost/rag` (no scheme, unparseable), `ingest` and `db migrate` exit with the fatal code, print an error naming the database connection, and neither stdout nor stderr contains `SECRETPW` or a traceback
  - Done when: `python -m pytest tests/ingestion/test_fatal_db.py -q` green and `python scripts/check.py --fast` green
  - Context: `plan.md#CLI and exit codes` `plan.md#Configuration`
  - Why: `conninfo_to_dict` raises `psycopg.ProgrammingError`, not `ValueError`, so `describe_database()` lets it escape from inside `connect()`'s `except` handler and its message echoes the conninfo string with the password.

- [x] **T91** A malformed `source_url` fails only its own document; the manifest rejects non-absolute http(s) URLs
  - AC: AC-001-02, AC-001-10
  - Files: `src/offshore_rag/ingestion/manifest.py`, `src/offshore_rag/ingestion/http.py`, `src/offshore_rag/ingestion/pipeline.py`, `tests/ingestion/test_manifest_validation.py`, `tests/unit/test_pipeline.py`
  - Test first: `tests/ingestion/test_manifest_validation.py` — an entry with a relative or non-http(s) `source_url` is named and the command exits 1 before any request; `tests/unit/test_pipeline.py` — an entry whose URL makes `urlsplit` raise (`http://[bad/a.pdf`) is a `download` failure in the report while the other documents are ingested and the run exits 3
  - Done when: `python -m pytest tests/ingestion/test_manifest_validation.py tests/unit/test_pipeline.py -q` green and `python scripts/check.py --fast` green
  - Context: `plan.md#Manifest format` `plan.md#HTTP` `plan.md#Run and outcomes`
  - Why: `PoliteClient.allowed` raises `ValueError` from `urlsplit`; `_process` only catches `FetchError` and the CLI only `psycopg.Error`/`OSError`, so today the whole run dies without a report. Consider mapping `httpx.DecodingError` to a `FetchError` in the same change.

- [x] **T92** Manifests whose titles contain Unicode line separators round-trip
  - AC: AC-001-01, AC-001-02
  - Files: `src/offshore_rag/ingestion/manifest.py`, `tests/unit/test_manifest.py`
  - Test first: `tests/unit/test_manifest.py` — `write_manifest` then `load_manifest` with a title containing U+2028, U+2029 and U+0085 returns the same entries
  - Done when: `python -m pytest tests/unit/test_manifest.py -q` green and `python scripts/check.py --fast` green
  - Context: `plan.md#Manifest format`
  - Why: `write_manifest` uses `ensure_ascii=False`; `load_manifest` uses `str.splitlines()`, which also splits on those characters. Split on `"\n"` only.

- [x] **T93** A `source_url` with an invalid port is rejected by the manifest and, if it reaches the client, fails only its own document
  - AC: AC-001-02, AC-001-10
  - Files: `src/offshore_rag/ingestion/manifest.py`, `src/offshore_rag/ingestion/http.py`, `tests/ingestion/test_manifest_validation.py`, `tests/unit/test_pipeline.py`
  - Test first: `tests/ingestion/test_manifest_validation.py` — entries with `http://host:abc/a.pdf` and `http://host:99999/a.pdf` are named and the command exits 1 before any request; `tests/unit/test_pipeline.py` — the same URL given straight to `run_ingest` is a `download` failure with reason `invalid_url` while the other documents are ingested
  - Done when: `python -m pytest tests/ingestion/test_manifest_validation.py tests/unit/test_pipeline.py -q` green and `python scripts/check.py --fast` green
  - Context: `plan.md#Manifest format` `plan.md#HTTP` `plan.md#Run and outcomes`
  - Why: `urlsplit` and `.hostname` accept a non-numeric port, so `_url_problem` passes it; `PoliteClient.allowed` then raises `httpx.InvalidURL` (not a `TransportError`, not a `ValueError`), which escapes `_process` and the CLI and kills the run without a report. Check `parts.port` in `_url_problem` and map `httpx.InvalidURL` to `FetchError(url, "invalid_url", ...)` in `allowed` and `get`.

- [x] **T94** A redirect with a malformed `Location` fails only its own document
  - AC: AC-001-10
  - Files: `src/offshore_rag/ingestion/http.py`, `tests/unit/test_http_client.py`, `tests/unit/test_pipeline.py`
  - Test first: `tests/unit/test_http_client.py` — a 302 whose `Location` is `http://[bad/x.pdf` makes `PoliteClient.get` raise `FetchError` with reason `invalid_redirect`; `tests/unit/test_pipeline.py` — the same redirect for one document is a `download` failure with reason `invalid_redirect` while the other documents are ingested
  - Done when: `python -m pytest tests/unit/test_http_client.py tests/unit/test_pipeline.py -q` green and `python scripts/check.py --fast` green
  - Context: `plan.md#HTTP` `plan.md#Run and outcomes`
  - Why: `PoliteClient.get` follows redirects with `urljoin(current, location)`, which raises `ValueError` on a malformed `Location` (verified: `Invalid IPv6 URL`); it escapes `_process` and the CLI and kills the run without a report, the same class as T91/T93.

- [ ] **T95** A detail page without a PDF link is skipped and reported; it no longer aborts `build-manifest`
  - AC: AC-001-01
  - Files: `src/offshore_rag/ingestion/build.py`, `src/offshore_rag/cli.py`, `tests/ingestion/test_manifest_build.py`, `tests/fixtures/bsee/` (one recorded detail page with no PDF link)
  - Test first: `tests/ingestion/test_manifest_build.py` — the recorded listing plus one detail page with no PDF link, served locally: `build-manifest` exits 0, the manifest has every other entry and none for that page, and the output names the skipped detail URL and the count; a listing where every detail page lacks a PDF still fails
  - Done when: `python -m pytest tests/ingestion/test_manifest_build.py tests/unit/test_listings.py -q` green and `python scripts/check.py --fast` green
  - Context: `plan.md#Manifest building`
  - Why: against the real site, `build-manifest` raised `ManifestBuildError` on `https://www.bsee.gov/safety-alerts/bsee-safety-alert-395-electrical-equipment-in-hazardous-locations-increase-risk-of`, whose HTML has no PDF link, so no manifest could be built at all.
