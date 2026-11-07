# 002 — Technical plan

## Design
One new chunking strategy, `structure_aware`, next to the unchanged `fixed_words`; a `rechunk` command that builds chunk sets from stored pages; a `chunk-report` command that measures chunk sets. No new dependency, no network in the new paths.

```
ingest  : manifest → download → parse → [chunkers for doc_type] → store (pages + chunk sets)    (spec 001 path)
rechunk : stored pages (Postgres) → [chunkers for doc_type] → replace chunk set per (document, strategy)
chunk-report : stored pages + chunks → structure detection → metrics per (strategy, doc_type) → data/reports/ + stdout
```

### Strategy selection
`CHUNKERS` keeps its meaning: the strategies run for every document type (default `fixed_words`). A new optional setting, `CHUNKERS_BY_DOC_TYPE`, is a JSON object `{doc_type: [strategy, …]}` that replaces the list for the types it names. `ChunkerPlan.from_settings(settings)` validates both before any download or database write (AC-002-02): every strategy must be in the registry and every key a valid `doc_type`. The error names the setting (`CHUNKERS` or `CHUNKERS_BY_DOC_TYPE`), the available strategies and the valid document types. `ChunkerPlan.for_doc_type(doc_type) -> list[Chunker]` is what `run_ingest` and `run_rechunk` call per document (AC-002-01).

### Structure detection
`ingestion/structure.py` turns the pages of one document into a `DocumentStructure`: a list of **lines** (page number, text, `removed` flag) and a list of **segments** (section label, first and last line index, `kind`: `narrative` | `acronyms` | `preamble`). It is pure, has one function per document type and is shared by the chunker and the structural report, so both use the same boundaries. It returns `None` when the structure is not recognized (AC-002-07). The rules are line-based on the text that `parse_pdf` already stores (see ADR-0003).

- **District reports (Form 2010).** Recognized when at least one of fields 17–24 is found.
  - Page 1 is entirely removed content (AC-002-04).
  - A page-header line is removed when it matches one of the header patterns measured in the sample: `PAGE: N OF`, `MMS - FORM 2010`, `EV2010R`, `For Public Release`, the bare page count and the header date line at the top of a page (AC-002-04).
  - A field starts at a line matching `^(\d{1,2})\.?\s+<FIELD TITLE>` for the known titles of fields 17–25 (and any later numbered field found after 24, labelled with its own number and title). The label is `"<number> <TITLE>"`, for example `17 INVESTIGATION FINDINGS` (AC-002-03).
  - Text on pages ≥ 2 before field 17 (rare) goes to a `preamble` segment.
- **Panel reports.** Recognized when a Contents page is found and at least one of its entries matches a heading line in the body.
  - The Contents page(s) and the figure/table-list page(s) (a page whose first line is `List of Figures`, `Figures`, `List of Tables`…) are removed content (AC-002-05).
  - The page-number line is removed: the first or last line of a page when it holds only a page number, arabic or roman (spec open question 16).
  - The section headings are the Contents entries with their page number stripped, matched as whole lines in the body (case-insensitive, whitespace-normalized). Each heading starts a segment labelled with that title (AC-002-05).
  - The `Abbreviations and Acronyms` / `Acronyms` section is labelled `acronyms` (AC-002-05).
  - Text before the first heading (title page, cover) goes to a `preamble` segment (spec open question 17).
- **Safety Alerts.**
  - The `Contact:` and `Phone:` lines of the header block (first page, before the title) are removed content (AC-002-06).
  - A line that ends in `:` and has at most 8 words starts a segment labelled with that line without the colon (`Background`, `Recommendations`…). Text before the first such line (alert number, date, title, opening paragraphs) is a `preamble` segment. An alert with no such line is one segment labelled `alert` (AC-002-06).
  - Photo captions are not detected and stay in the text.

### Chunking
`StructureAwareChunker(size_cap=250)` (`ingestion/structure_aware.py`):
1. Detect the structure. `None` → fallback: fixed windows of `size_cap` words, no overlap, over the text runs of `fixed_words` (reusing `_text_runs`), each labelled `structure_not_recognized` (AC-002-07).
2. For each segment, take its kept words (lines with `removed=False`), each tagged with its page and with the breaks after it (paragraph, sentence).
3. A segment that fits the cap is one chunk. A longer one is cut by the splitting rule of the spec: last paragraph break within the cap, else last sentence break, else the cap word. No overlap (AC-002-03, AC-002-05, AC-002-06).
4. A segment piece never crosses an image-only page; the segment is cut there, as `fixed_words` does with its runs (AC-002-08).
5. `page_start`/`page_end` are the pages of the first and last word; text is the words joined by single spaces (the joining rule of `fixed_words`). The section label goes in `ChunkDraft.section`, never in the text.

Breaks: a **paragraph break** follows a blank line, a bullet line start (`•`, `-`, `1)`, `a.`), or a line ending in `.`, `:`, `?` or `!` that is shorter than 75% of the median line length of its page. A **sentence break** follows a word ending in `.`, `?` or `!` when the next word starts with a capital letter or a digit. Both are heuristics; the splitting rule only needs them to be inside the cap, and AC-002-08 checks that no word is lost or reordered whatever they decide.

`params` = `{"size_cap": 250, "version": 1}`. `version` is bumped whenever the detection or splitting rules change, so that `rechunk` regenerates the sets (see *Re-chunking*).

### Re-chunking
`run_rechunk(store, plan)` iterates the stored documents of the configured types, loads their pages, runs the chunkers of their type and writes each chunk set with `CorpusStore.replace_chunk_set`. For each (document, strategy):
- a stored set with the same `chunker` and identical `chunker_params` is left untouched: ids and text are kept, and a second run creates nothing (AC-002-09);
- otherwise the sets of that strategy for that document (older params) are deleted and the new one inserted, in one transaction per document.

It never builds a `PoliteClient`, so no HTTP request is possible (AC-002-09). It prints documents processed, chunks created per strategy, structure-not-recognized documents and duration per strategy. A document whose chunker raises `ValueError` is reported as failed and the run goes on (exit 3), as in `ingest`.

### Ingestion changes
- `run_ingest` takes a `ChunkerPlan` instead of a list and times the chunk stage per strategy.
- `DocumentOutcome` gains `chunks_by_strategy` and `structure_not_recognized: bool` (any chunk labelled `structure_not_recognized`). The ingestion report and the summary list those documents with source URL and document type, and the chunk duration per strategy (AC-002-07, metrics). The exit code ignores them.

### Structural report
`ingestion/structural_report.py`, `build_structural_report(store, strategies) -> StructuralReport`. For each stored document it re-runs structure detection on the stored pages and builds two word streams: the full one (every text-page word) and the kept one (removed content taken out), each word tagged with its line. Each chunk is located by searching its word sequence from the first word of `page_start` in the stream that matches it exactly (full for `fixed_words`, kept for `structure_aware`). Per (strategy, doc_type) it computes the metrics of AC-002-10:
- documents, chunks, structure-not-recognized documents; size in words (min, p10, median, p90, max); share spanning more than one page;
- page-header share: chunk text matches a district page-header pattern of *Structure detection*;
- checkbox-grid share (district only): FIRE, EXPLOSION, FATALITY and COLLISION all present as whole words;
- boundary-crossing share: a segment start falls strictly inside the chunk's span;
- missing: `narrative` and `acronyms` segments none of whose words is in a chunk span, listed per document with the labels.

Documents with no detected structure count in the totals but not in the crossing and missing metrics. A requested strategy with no chunks → exit 1, message naming it, no file (AC-002-12). Output: `data/reports/chunks-<UTC timestamp>.json` and a table on stdout (AC-002-10).

### Amendment of spec 001
AC-001-07 in `docs/specs/001-corpus-ingestion/spec.md` is replaced by the wording proposed in spec 002, in this branch, in the same commit as `tasks.md`, before approval. That changes 001's hash: at gate 1 the user runs `python scripts/approve.py 001` and `python scripts/approve.py 002`. The AC-001-07 tests in `tests/ingestion/test_chunking.py` apply the substring and coverage checks to `fixed_words` sets only, as the amended text says; the AC-002-08 tests cover `structure_aware`. The glossary terms are already in `docs/glossary.md`.

## Data model

### Migration 0002
`src/offshore_rag/db/migrations/0002_chunk_section.sql`:
```sql
ALTER TABLE chunks ADD COLUMN section text CHECK (section IS NULL OR length(section) > 0);
CREATE INDEX chunks_chunker_document ON chunks (chunker, document_id);
```
`section` is `NULL` for `fixed_words` and non-empty for `structure_aware` (enforced in code and checked by AC-002-01; not a database constraint so that the column stays strategy-agnostic). The existing `UNIQUE (document_id, chunker, chunker_params, ordinal)` already separates chunk sets. The index serves `rechunk` and `chunk-report`. Applies on a clean database and on a database migrated to 0001.

## Contracts

### Package layout
| Path | Change |
|---|---|
| `src/offshore_rag/ingestion/chunking.py` | `ChunkDraft.section: str \| None = None`; `Chunker.chunk(pages, doc_type)`; registry adds `structure_aware`; `ChunkerPlan`, `ChunkerConfigError` (replaces `UnknownChunkerError`) |
| `src/offshore_rag/ingestion/structure.py` | new: `DocumentStructure`, `Line`, `Segment`, `detect_structure(pages, doc_type)`, header patterns |
| `src/offshore_rag/ingestion/structure_aware.py` | new: `StructureAwareChunker` |
| `src/offshore_rag/ingestion/rechunk.py` | new: `run_rechunk`, `RechunkSummary` |
| `src/offshore_rag/ingestion/structural_report.py` | new: `build_structural_report`, `write_structural_report`, `format_structural_summary` |
| `src/offshore_rag/ingestion/store.py` | `section` in the chunk COPY; `iter_stored_documents(doc_types)`, `load_pages(document_id)`, `replace_chunk_set(document_id, chunker, drafts) -> Literal["created", "unchanged"]`, `chunks_for_report(strategies)` |
| `src/offshore_rag/ingestion/pipeline.py`, `report.py` | `ChunkerPlan`, per-strategy counts and durations, structure-not-recognized list |
| `src/offshore_rag/config.py` | `chunkers_by_doc_type: dict[str, list[str]] = {}` (JSON) |
| `src/offshore_rag/cli.py` | `rechunk` and `chunk-report` commands |

### Chunker interface
```python
class Chunker(Protocol):
    id: str
    params: Mapping[str, int | str]
    def chunk(self, pages: Sequence[PageText], doc_type: DocType) -> list[ChunkDraft]: ...
```
`FixedWordChunker` ignores `doc_type` and returns `section=None`: its output is byte-identical to spec 001 (AC-002-01). `StructureAwareChunker` raises nothing for unrecognized structure (it falls back); it raises `ValueError` only for invalid parameters.

### CLI and exit codes
| Command | Exit codes |
|---|---|
| `offshore-rag ingest` | as spec 001; config errors from `CHUNKERS`/`CHUNKERS_BY_DOC_TYPE` are fatal (1) before any network or DB access (AC-002-02) |
| `offshore-rag rechunk` | 0 ok; 3 some document failed; 1 fatal: invalid config (before DB access), unreachable DB or pending migrations, message without password (AC-002-02, AC-002-12) |
| `offshore-rag chunk-report [--strategy NAME …]` | 0 report written; 1 a requested strategy has no chunks (no file written), unreachable DB or pending migrations (AC-002-12). Default strategies: those present in `chunks`. |

`rechunk` and `chunk-report` reuse the connection and schema checks of `ingest` (extracted into one helper in `cli.py`).

### Test fixtures
Three trimmed real PDFs under `tests/fixtures/bsee/`, recorded in `SOURCES.md` (URL, date, sha256, trimming). Trimming keeps whole pages (page import with pypdfium2, a helper in `tests/support/trim_pdf.py`) and is done once by hand. Candidates found in the local sample, to be confirmed when the fixtures are cut:
- **District:** a 3-page Form 2010 with fields 17–24 filled and no images (sample sha256 prefix `003089839387`, MP 42 L, 2020).
- **Panel:** an OCS Report with a Contents page, an acronym list and a figure list on pages without photographs, trimmed to Contents + acronyms + figure list + the Executive Summary and Introduction sections. Its body pages keep their page-number line (first or last), so AC-002-05 checks its removal.
- **Safety Alert:** a recent alert with `Contact:`/`Phone:` lines and at least two heading lines ending in `:`, with no third-party photographs. Only 7 of 71 alerts in the sample have such lines; one is picked from those. Alert 469, already committed, has Contact/Phone but no heading lines.

`tests/support/pdfs.py` gains generators for: an MMS "Notice No. N" alert with numbered paragraphs, a district report without fields 17–24, a panel report without headings, and a document with an image-only page between two text pages.

## Test strategy
| AC | Layer | Test |
|---|---|---|
| AC-002-01 | integration (Postgres) | `ingest` on the three fixtures with both strategies for all types: one set per strategy per document, ids/params/labels recorded; `fixed_words` rows equal to a `fixed_words`-only run; `CHUNKERS_BY_DOC_TYPE` with one type → no `structure_aware` rows for the others |
| AC-002-02 | unit + CLI | `ChunkerPlan.from_settings` errors; `ingest` and `rechunk` with an unknown strategy / doc type exit 1, the local server gets no request and no table changes |
| AC-002-03 | unit | district fixture: labels for every filled field 17–24, no chunk mixes fields, every field word present, long field split ≤ 250 without overlap |
| AC-002-04 | unit | district fixture: no page-1 text, no grid labels set, no header line in any chunk |
| AC-002-05 | unit | panel fixture: headings → labelled chunks, no cross-section chunk, `acronyms` label, Contents and figure list absent, no page-number line |
| AC-002-06 | unit | alert fixture with large and small caps; generated Notice No. N alert, fitting and not fitting |
| AC-002-07 | unit + integration | generated unrecognized district and panel: fallback windows labelled, all words covered; `ingest` exit 0, `fixed_words` stored, report lists them with URL and type |
| AC-002-08 | integration (Postgres) | invariants on every stored `structure_aware` chunk of all fixtures and the image-only generated document, checked against stored pages minus removed content |
| AC-002-09 | integration (Postgres) | ingest `fixed_words` only → enable `structure_aware` → `rechunk`: sets created, server request count 0, `fixed_words` ids/text unchanged, second run same row counts, summary printed |
| AC-002-10 | integration (Postgres) | `chunk-report` on the fixtures: file under `data/reports/`, stdout summary, every metric present per strategy and type |
| AC-002-11 | integration (Postgres) | values of that report: zeros for `structure_aware`, max ≤ 250, nothing missing; `fixed_words` district header and crossing shares > 0 |
| AC-002-12 | CLI + integration | empty DB / never-run strategy → non-zero, strategy named, no file; unreachable DB and missing schema for `rechunk` and `chunk-report` → exit 1, no password in output |

Unit tests of the splitting rule and the break heuristics (paragraph, sentence, hard cut) live in `tests/unit/test_structure_aware_unit.py`; they support the ACs and carry no AC id of their own.

## Evaluation impact
None on retrieval or answer metrics: nothing is embedded, retrieved or answered, and no golden set exists yet. The structural report is the measurement of this spec. Before the PR, `rechunk` and `chunk-report` are run on the local 690-document sample and the summary table is pasted in the PR description (not a gate; the sample is never committed).

## Risks
- **Rules tuned to a sample.** BSEE layouts drift across decades (MMS vs BSEE era, two page-number positions in panel reports). Mitigation: unrecognized structure is a visible fallback, and the structural report on the 690-document sample shows the fallback share and missing sections per type before merge.
- **Heuristic breaks.** Bad paragraph detection only moves cuts inside the cap; AC-002-08 guarantees no word is lost, duplicated or reordered.
- **Contents titles that differ from body headings** (punctuation, line wraps). Mitigation: normalized matching; unmatched entries are reported as missing sections, not silently dropped.
- **Chunk location in the report** relies on exact word-sequence matching; a chunk that cannot be located is a bug and fails the report command loudly rather than being skipped.
- **Changing the `Chunker` signature** touches spec 001 code and tests; the AC-001 tests stay green as the regression check.

## Open points for the spec
Found while planning against the local sample and resolved in the spec (open questions 16–18):
- **P1. Panel page-number line position.** 22 of 36 sample panel reports have it as the first line, 13 as the last. The removed line is the first or last line of a page holding only a page number, arabic or roman.
- **P2. Text before the first section.** Labelled `preamble`; an alert without heading lines is one segment labelled `alert`.
- **P3. Alert size.** The cap stays 250 words; about a third of alerts fit whole. The structural report shows the real share.

## ADRs
- **ADR-0003 (proposed): structure detection from extracted line text with per-type rules**, instead of PDF layout coordinates, a document-layout library or an LLM.
