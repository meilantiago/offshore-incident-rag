# 002 — Tasks

Small, ordered tasks grouped in milestones. Each milestone is one invocation of its agent in `/sdd-build` and one commit. A task is closed (`[x]`) only when its "Done when" is green. The red commit with the acceptance tests is always first, outside the milestones.

Integration tests need Postgres: `docker compose up -d db` and `TEST_DATABASE_URL` set (see `.env.example`).

- [x] **T01** Red acceptance tests, fixtures and AC-001-07 amendment in tests
  - AC: AC-002-01, AC-002-02, AC-002-03, AC-002-04, AC-002-05, AC-002-06, AC-002-07, AC-002-08, AC-002-09, AC-002-10, AC-002-11, AC-002-12
  - Files: `tests/ingestion/test_chunker_selection.py` (AC-002-01, AC-002-02), `tests/ingestion/test_district_structure.py` (AC-002-03, AC-002-04), `tests/ingestion/test_panel_structure.py` (AC-002-05), `tests/ingestion/test_alert_structure.py` (AC-002-06), `tests/ingestion/test_structure_fallback.py` (AC-002-07), `tests/ingestion/test_structure_aware_invariants.py` (AC-002-08), `tests/ingestion/test_rechunk.py` (AC-002-09, AC-002-12), `tests/ingestion/test_structural_report.py` (AC-002-10, AC-002-11, AC-002-12), `tests/ingestion/test_chunking.py` (AC-001-07 substring and coverage checks on `fixed_words` sets only), `tests/support/pdfs.py` (generators: MMS "Notice No. N" alert, district without fields 17–24, panel without headings, image-only page between two text pages), `tests/support/trim_pdf.py`, `tests/fixtures/bsee/` (trimmed district, panel and Safety Alert PDFs), `tests/fixtures/bsee/SOURCES.md`
  - Test first: the tests themselves, written by `test-writer` from the spec and `plan.md#Contracts`
  - Done when: `python -m pytest tests -q` runs every new acceptance test and each fails for lack of `offshore_rag` modules or behaviour (ImportError / assertion), not for syntax, fixture or infrastructure errors; every spec 001 test still passes; `python scripts/traceability.py` lists all 12 ACs of 002 as covered

## H1 — Chunk section column and strategy selection
- Agent: implementer
- Model: sonnet
- Context: `plan.md#Strategy selection` `plan.md#Migration 0002` `plan.md#Package layout` `plan.md#Chunker interface` `plan.md#CLI and exit codes`

- [x] **T02** Migration 0002 and `section` on chunks
  - AC: AC-002-01
  - Files: `src/offshore_rag/db/migrations/0002_chunk_section.sql`, `src/offshore_rag/ingestion/chunking.py` (`ChunkDraft.section`), `src/offshore_rag/ingestion/store.py` (`section` in the chunk COPY), `tests/unit/test_migrate.py`
  - Test first: `tests/unit/test_migrate.py` — 0002 applies on a clean schema and on one migrated to 0001; an empty `section` is rejected; `fixed_words` rows store `section` NULL
  - Done when: `python -m pytest tests/unit/test_migrate.py tests/ingestion/test_chunking.py -q` green and `python scripts/check.py --fast` green

- [x] **T03** `Chunker.chunk(pages, doc_type)`, `ChunkerPlan` and `CHUNKERS_BY_DOC_TYPE`
  - AC: AC-002-01, AC-002-02
  - Files: `src/offshore_rag/ingestion/chunking.py` (`ChunkerPlan`, `ChunkerConfigError` replacing `UnknownChunkerError`), `src/offshore_rag/config.py`, `src/offshore_rag/ingestion/pipeline.py`, `src/offshore_rag/cli.py`, `tests/unit/test_chunker_plan.py`
  - Test first: `tests/unit/test_chunker_plan.py` — `from_settings` with defaults, with a per-type override, with an unknown strategy and an unknown doc type (message names the setting, the available strategies and the valid types); `for_doc_type` returns the configured chunkers; `FixedWordChunker` output unchanged
  - Done when: `python -m pytest tests/unit/test_chunker_plan.py tests/unit/test_chunking_unit.py -q` green, `python -m pytest tests/ingestion/test_chunker_selection.py -q -k "unknown"` green and `python scripts/check.py --fast` green

## H2 — Structure detection and the `structure_aware` chunker
- Agent: implementer
- Model: opus
- Context: `spec.md#Definitions` `plan.md#Structure detection` `plan.md#Chunking` `plan.md#Chunker interface` `plan.md#Test fixtures`

- [x] **T04** `detect_structure` for district reports (Form 2010)
  - AC: AC-002-03, AC-002-04
  - Files: `src/offshore_rag/ingestion/structure.py`, `tests/unit/test_structure_unit.py`
  - Test first: `tests/unit/test_structure_unit.py` — on the district fixture's stored pages: page 1 and every header line flagged removed, one segment per filled field 17–24 labelled `"<number> <TITLE>"`, text before field 17 on page ≥ 2 is `preamble`; a district without fields 17–24 returns `None`
  - Done when: `python -m pytest tests/unit/test_structure_unit.py -q -k district` green and `python scripts/check.py --fast` green

- [x] **T05** `detect_structure` for panel reports and Safety Alerts
  - AC: AC-002-05, AC-002-06
  - Files: `src/offshore_rag/ingestion/structure.py`, `tests/unit/test_structure_unit.py`
  - Test first: `tests/unit/test_structure_unit.py` — panel fixture: Contents and figure-list pages removed, first-or-last page-number line removed, headings from Contents entries, `acronyms` and `preamble` segments; a panel without headings returns `None`; alert fixture: Contact/Phone removed, segments at heading lines ending in `:`, `preamble` before the first; an alert with no heading line is one `alert` segment
  - Done when: `python -m pytest tests/unit/test_structure_unit.py -q` green and `python scripts/check.py --fast` green

- [x] **T06** `StructureAwareChunker`: splitting rule, image-only cuts and fallback
  - AC: AC-002-03, AC-002-04, AC-002-05, AC-002-06, AC-002-07, AC-002-08
  - Files: `src/offshore_rag/ingestion/structure_aware.py`, `src/offshore_rag/ingestion/chunking.py` (registry), `tests/unit/test_structure_aware_unit.py`
  - Test first: `tests/unit/test_structure_aware_unit.py` — paragraph, sentence and hard-word cuts within the cap, no overlap; a segment cut at an image-only page; unrecognized structure → windows of ≤ `size_cap` labelled `structure_not_recognized` covering every word; `params` = `{"size_cap": 250, "version": 1}`
  - Done when: `python -m pytest tests/unit/test_structure_aware_unit.py tests/ingestion/test_district_structure.py tests/ingestion/test_panel_structure.py tests/ingestion/test_alert_structure.py -q` green and `python scripts/check.py --fast` green

## H3 — Ingestion with both strategies and re-chunking
- Agent: implementer
- Model: sonnet
- Context: `plan.md#Ingestion changes` `plan.md#Re-chunking` `plan.md#Package layout` `plan.md#CLI and exit codes`

- [x] **T07** `ingest` with a `ChunkerPlan`: per-strategy counts, durations and structure not recognized
  - AC: AC-002-01, AC-002-07, AC-002-08
  - Files: `src/offshore_rag/ingestion/pipeline.py`, `src/offshore_rag/ingestion/report.py`, `tests/unit/test_pipeline.py`, `tests/unit/test_report.py`
  - Test first: `tests/unit/test_report.py` — `DocumentOutcome.chunks_by_strategy` and `structure_not_recognized`; the report and summary list those documents with source URL and doc type and the duration per strategy; the exit code ignores them
  - Done when: `python -m pytest tests/unit/test_pipeline.py tests/unit/test_report.py tests/ingestion/test_chunker_selection.py tests/ingestion/test_structure_fallback.py tests/ingestion/test_structure_aware_invariants.py -q` green and `python scripts/check.py --fast` green

- [x] **T08** Store queries and `run_rechunk`
  - AC: AC-002-09
  - Files: `src/offshore_rag/ingestion/store.py` (`iter_stored_documents`, `load_pages`, `replace_chunk_set`), `src/offshore_rag/ingestion/rechunk.py`, `tests/unit/test_rechunk_unit.py`
  - Test first: `tests/unit/test_rechunk_unit.py` (integration) — `replace_chunk_set` returns `unchanged` for identical params and keeps ids, replaces sets with older params in one transaction; `run_rechunk` summary counts per strategy
  - Done when: `python -m pytest tests/unit/test_rechunk_unit.py -q` green and `python scripts/check.py --fast` green

- [x] **T09** `offshore-rag rechunk` and the shared database checks
  - AC: AC-002-02, AC-002-09, AC-002-12
  - Files: `src/offshore_rag/cli.py`, `tests/unit/test_cli_rechunk.py`
  - Test first: `tests/unit/test_cli_rechunk.py` — exit 0 with the summary printed; invalid config exits 1 before DB access; unreachable DB and pending migrations exit 1 without the password
  - Done when: `python -m pytest tests/unit/test_cli_rechunk.py tests/ingestion/test_rechunk.py -q` green and `python scripts/check.py --fast` green

## H4 — Structural report
- Agent: implementer
- Model: opus
- Context: `plan.md#Structural report` `plan.md#Structure detection` `plan.md#CLI and exit codes` `spec.md#Metrics`

- [x] **T10** `build_structural_report`: chunk location and metrics per strategy and document type
  - AC: AC-002-10, AC-002-11
  - Files: `src/offshore_rag/ingestion/structural_report.py`, `src/offshore_rag/ingestion/store.py` (`chunks_for_report`), `tests/unit/test_structural_report_unit.py`
  - Test first: `tests/unit/test_structural_report_unit.py` — on hand-built chunks: percentiles, multi-page share, header and grid shares, boundary crossings, missing segments; a chunk that cannot be located raises
  - Done when: `python -m pytest tests/unit/test_structural_report_unit.py -q` green and `python scripts/check.py --fast` green

- [x] **T11** `offshore-rag chunk-report`: JSON under `data/reports/`, stdout table and errors
  - AC: AC-002-10, AC-002-11, AC-002-12
  - Files: `src/offshore_rag/ingestion/structural_report.py` (`write_structural_report`, `format_structural_summary`), `src/offshore_rag/cli.py`, `tests/unit/test_cli_chunk_report.py`
  - Test first: `tests/unit/test_cli_chunk_report.py` — `--strategy` default and explicit; a strategy with no chunks exits 1, names it and writes no file; unreachable DB exits 1 without the password
  - Done when: `python -m pytest tests/unit/test_cli_chunk_report.py tests/ingestion/test_structural_report.py -q` green and `python scripts/check.py --all` green

## Verification fixes
Confirmed findings from `/sdd-verify`, as loose T90+ tasks. Each may carry its own `Context`.

- [x] **T90** Panel section labels drop Unicode ellipsis leaders from Contents entries
  - AC: AC-002-05
  - Files: `src/offshore_rag/ingestion/structure.py` (`_CONTENTS_ENTRY` and title clean-up), `tests/unit/test_structure_unit.py`
  - Test first: `tests/unit/test_structure_unit.py` — a generated panel whose Contents entries use `…` leaders (`Chronology of Events………… 12`) and `. . .` leaders: the section labels are the bare titles (`Chronology of Events`) and the body headings match them
  - Done when: `python -m pytest tests/unit/test_structure_unit.py tests/ingestion/test_panel_structure.py -q` green and `python scripts/check.py --fast` green
  - Context: `plan.md#Structure detection` `spec.md#Definitions`
  - Found: `rechunk` on the local 690-document sample left 118 `structure_aware` chunks of 2 panel reports labelled like `Chronology of Events……………`, because `_CONTENTS_ENTRY` strips `.`, `_` and spaces before the page number but not `…`.

- [x] **T91** Red acceptance test for AC-002-13 (stale chunk sets in the structural report)
  - AC: AC-002-13
  - Files: `tests/ingestion/test_structural_report.py`
  - Test first: the test itself, written by `test-writer` from AC-002-13 and `plan.md#Structural report`
  - Done when: the new test runs and fails for lack of behaviour (today `chunk-report` exits 1 and writes no file), not for syntax or fixture errors; `python scripts/traceability.py` lists AC-002-13 as covered
  - Context: `plan.md#Structural report` `plan.md#CLI and exit codes`

- [ ] **T92** `chunk-report` lists stale chunk sets instead of aborting
  - AC: AC-002-13
  - Files: `src/offshore_rag/ingestion/structural_report.py`, `src/offshore_rag/cli.py`, `tests/unit/test_structural_report_unit.py`, `tests/unit/test_cli_chunk_report.py`
  - Test first: `tests/unit/test_structural_report_unit.py` — a chunk that cannot be located marks its set stale, the set is out of every metric of its entry, `stale_chunk_sets` carries URL, doc type, strategy and ordinal; `tests/unit/test_cli_chunk_report.py` — exit 3 with the file written and the `rechunk` hint
  - Done when: `python -m pytest tests/unit/test_structural_report_unit.py tests/unit/test_cli_chunk_report.py tests/ingestion/test_structural_report.py -q` green and `python scripts/check.py --all` green
  - Context: `plan.md#Structural report` `plan.md#CLI and exit codes` `plan.md#Risks`
