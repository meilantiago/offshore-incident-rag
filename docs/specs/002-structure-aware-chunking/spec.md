---
id: "002"
title: Structure-aware chunking
status: approved
roadmap_refs: ["R2", "brief §3.2", "brief §1"]
approved_hash: sha256:4b87365e8274b22d7dadbe5954b2dec0657c8d20451d0f4b682109dfc1f30d71
approved_at: 2026-11-07
approved_by: Tiagod
---

# 002 — Structure-aware chunking

## Problem
The brief says BSEE lessons are "spread across hundreds of PDFs with uneven structure" (brief §1), and R2 must retrieve evidence from them with hybrid search (brief §3.2). Spec 001 cuts every document into the same `fixed_words` windows (250 words, 40 overlap) regardless of its **document type**. A sample ingested with spec 001 shows that this hurts the material retrieval will index. The sample was measured on 2026-11-05 and holds 690 documents, 3,809 pages and 5,517 `fixed_words` chunks.

| Document type | Docs in sample | Words per doc (p10 / median / p90) | Pages per doc (median) | Chunks per doc (median) | Docs in a single chunk |
|---|---|---|---|---|---|
| `safety_alert` | 88 (of ~610 listed) | 213 / 373 / 649 | 1 | 2 | 23% |
| `panel_report` | 35 | 3,123 / 8,530 / 18,028 | 33 | 41 | — |
| `district_report` | 567 | 689 / 1,138 / 1,919 | 4 | 6 | — |

- **District reports (MMS Form 2010) are 67% of all chunks, and the noisiest.**
  - The page-1 checkbox grid is extracted as every option label (FIRE, EXPLOSION, FATALITY, COLLISION, POLLUTION…), and the "X" marks come out as detached tokens. Which box was checked is lost.
  - 564 of the 946 district chunks that start on page 1 contain FIRE, EXPLOSION, FATALITY and COLLISION all at once. That is systematic noise for lexical and semantic retrieval alike.
  - A page header repeats on every page: `PAGE: N OF`, a date, `MMS - FORM 2010`, `EV2010R`, the page count and `For Public Release`. It makes up 4.9% of district words and sits inside 61% of district chunks.
  - The narrative lives in numbered fields present in 94–100% of reports: 17 INVESTIGATION FINDINGS, 18 LIST THE PROBABLE CAUSE(S) OF ACCIDENT, 19 LIST THE CONTRIBUTING CAUSE(S) OF ACCIDENT, 20 LIST THE ADDITIONAL INFORMATION, 21 PROPERTY DAMAGED, 22 RECOMMENDATIONS TO PREVENT RECURRANCE NARRATIVE, 23 POSSIBLE OCS VIOLATIONS RELATED TO ACCIDENT, 24 SPECIFY VIOLATIONS DIRECTLY OR INDIRECTLY CONTRIBUTING (and 25 DATE OF ONSITE INVESTIGATION). Fixed windows ignore those field boundaries.
- **Panel reports** have a Contents page listing their sections with page numbers, Title Case in-text headings, and the page number as the first line of each page (22 of 36 in the sample) or, in older MMS OCS Reports, as the last line (13 of 36). Contents, acronym and figure-list pages are 2.6% of panel words, and 69% of panel chunks span more than one page.
- **Safety Alerts** are short.
  - Recent ones follow "Safety Alert No. / Date / Contact / Phone / title / Background: / … / recommendations", and "recommend" appears in 64% of them.
  - Old MMS-era notices ("Notice No. N", from 1993) are prose with numbered lists, and photo captions are mixed into the text.
  - Most fit in one or two fixed windows, and the window often separates the incident from the recommendations.
- 61% of district chunks span more than one page. Image-only pages are 1.1% of all pages.

This spec is the first slice of R2. It adds one **chunking strategy**, `structure_aware`, which follows the structure of each document type. It sits next to the unchanged `fixed_words` control. The spec also adds a **structural report** that measures chunk quality without a golden set, so that the next R2 spec can compare the two strategies on retrieval metrics. The measurements above were made by hand on a local sample. The structural report makes them reproducible.

## Users
- **System operator**: chooses which chunking strategies run for each document type, produces their chunks for new and already-ingested documents, and reads the structural report.
- **The system itself**: the next R2 spec (embeddings, hybrid search, golden-set comparison) reads the chunk sets stored here. Nothing is retrieved or answered in this spec.
- Safety and operations engineers do nothing directly here. They benefit later from chunks that follow the report's own fields and sections and keep page-accurate citations (constitution §5).

## Stories
- As a system operator, I want to choose the chunking strategies per document type in configuration, with `fixed_words` always available as the control, so that the strategies can later be compared on the same documents.
- As a system operator, I want district reports chunked by their narrative fields, without the repeated page header or page 1, so that retrieval does not match every report on FIRE, EXPLOSION, FATALITY and COLLISION.
- As a system operator, I want panel reports chunked by their sections, with front-matter pages kept out of the narrative chunks, so that a chunk is about one topic of the investigation.
- As a system operator, I want a Safety Alert kept whole when it is short, so that the incident and its recommendations stay together.
- As a system operator, I want to add a strategy to an already-ingested corpus without downloading it again, so that trying a strategy is cheap and polite to BSEE.
- As a system operator, I want a structural report per strategy and document type, so that I can see header noise, boundary crossings, size distribution and coverage before any golden set exists.

## Definitions
Terms used in the acceptance criteria:
- **Size cap**: the maximum number of words in a `structure_aware` chunk. It is a parameter recorded in `chunker_params`, set to 250 words for every document type, and it allows no overlap.
- **Splitting rule**: when a field or section is over the size cap, it is cut into consecutive pieces. Each cut is at the last paragraph break within the cap; if there is none, at the last sentence break within the cap; if there is none, at the cap word.
- **Removed content**: the text that `structure_aware` leaves out on purpose. It is:
  - district page 1 (the checkbox grid and the loose page-1 fields) and the repeated district page-header lines;
  - the panel Contents and figure-list pages and the page-number line of each panel page: its first or last line when that line holds only a page number (arabic or roman);
  - the Contact and Phone lines of a Safety Alert's header block.
- **Section label**: the field or section a chunk belongs to, stored in its own column and never added to the chunk text. Special values: `acronyms` (a panel list of acronyms), `preamble` (text before the first field or section, such as a panel title page or the opening of an alert before its first heading line), `alert` (a Safety Alert with no heading lines) and `structure_not_recognized` (AC-002-07).

## Acceptance criteria
- **AC-002-01** — Given configuration that runs `fixed_words` for all three document types and `structure_aware` for all three, when the operator runs `ingest` on a manifest with one committed fixture of each document type, then each document has exactly one `fixed_words` chunk set and one `structure_aware` chunk set. Every chunk records its strategy id and parameters, and every `structure_aware` chunk records a non-empty section label. The `fixed_words` chunks are identical (text, page range, ordinal, parameters) to the ones produced when `fixed_words` is the only configured strategy. With `structure_aware` configured for only one type, documents of the other types get no `structure_aware` chunks.
- **AC-002-02** — Given configuration that names an unknown strategy or an unknown document type, when the operator runs `ingest` or re-chunking, then the command exits with the fatal code before any download or database write. The error names the offending setting, the available strategies and the valid document types.
- **AC-002-03** — Given the committed district report fixture (MMS Form 2010), when it is chunked with `structure_aware`, then every narrative field 17 to 24 that has text in the fixture is in at least one chunk whose section label names that field's number and title. No chunk holds text from two different fields, and every word of each field's text appears in that field's chunks. A field over the size cap is split by the splitting rule into chunks of at most 250 words that share its section label and do not overlap.
- **AC-002-04** — Given the same district fixture, when it is chunked with `structure_aware`, then no chunk contains text from page 1: no checkbox-grid option labels (FIRE, EXPLOSION, FATALITY, COLLISION…) and no loose page-1 field. No chunk contains a repeated page-header line (`PAGE: N OF`, `MMS - FORM 2010`, `EV2010R`, `For Public Release`).
- **AC-002-05** — Given the committed panel report fixture, trimmed to its Contents page, its list of acronyms, its figure list and two or three sections, when it is chunked with `structure_aware`, then:
  - every section heading in the fixture is in at least one chunk labelled with that section's title;
  - no chunk holds text from two sections, and long sections are split by the splitting rule within the size cap;
  - the list of acronyms is in its own chunk or chunks, labelled `acronyms`;
  - the Contents page and the figure list are in no chunk (the fixture includes a figure-list page);
  - no chunk contains a page-number line (the first or last line of a page holding only a page number).
- **AC-002-06** — Given the committed Safety Alert fixture, when it is chunked with `structure_aware`, then:
  - with a size cap at least the alert's length, it is exactly one chunk holding the whole alert text, from its first to its last text page;
  - with a smaller cap, chunk boundaries fall only at heading lines ending in `:` (for example `Background:`, `Recommendations:`), plus splitting-rule cuts inside a section over the cap;
  - no chunk contains the Contact or Phone lines, while photo captions stay in the text.
  - Given an MMS-era alert with no such heading lines (a "Notice No. N" document), it is one chunk when it fits the cap and is otherwise split at paragraph breaks within the cap.
- **AC-002-07** — Given a document whose structure `structure_aware` cannot find, when it is ingested or re-chunked, then its `structure_aware` chunks are fixed windows of at most 250 words with no overlap, covering every word of its text pages, each labelled `structure_not_recognized`. The document is not counted as failed: the run's exit code is unaffected, and its `fixed_words` chunks are stored as usual. The ingestion report lists it under structure not recognized, with its source URL and document type. Examples: a `district_report` without Form 2010 fields 17–24, or a `panel_report` without headings.
- **AC-002-08** — Given every `structure_aware` chunk produced from the committed fixtures, which include a document with an image-only page, when the chunks are inspected in the database, then:
  - each chunk belongs to one document and has 1 ≤ `page_start` ≤ `page_end` ≤ the document's page count;
  - its first word comes from `page_start` and its last word from `page_end`;
  - its words appear in order and contiguously in the text of its page range once the removed content is taken out, and no other word of that range is skipped;
  - no chunk contains text from an image-only page;
  - every word of the document's text pages, once the removed content is taken out, is in exactly one chunk of the set (the coverage guarantee that AC-001-07 keeps for `fixed_words` only).
- **AC-002-09** — Given a corpus ingested with `fixed_words` only, when the operator enables `structure_aware` and runs re-chunking of the stored documents, then:
  - `structure_aware` chunks are created for every stored document of the configured types, and the local test server receives no HTTP request;
  - the existing `fixed_words` chunks keep their ids and text;
  - running re-chunking again leaves the number of chunk rows per strategy and document unchanged (no duplicate chunk set);
  - a summary is printed with the documents processed, the chunks created per strategy, the structure-not-recognized documents and the duration per strategy.
- **AC-002-10** — Given a corpus holding the fixtures chunked with `fixed_words` and `structure_aware`, when the operator runs the structural report, then a machine-readable file is written under `data/reports/` and a summary is printed to stdout. Both carry, per strategy and document type:
  - the number of documents, chunks and structure-not-recognized documents;
  - chunk size in words (min, p10, median, p90, max);
  - the share of chunks spanning more than one page;
  - the share of chunks containing a repeated district page-header line;
  - for district reports, the share of chunks containing the grid labels FIRE, EXPLOSION, FATALITY and COLLISION together;
  - the share of chunks crossing a field or section boundary;
  - the documents whose narrative fields or sections appear in no chunk, with the missing fields or sections named.
- **AC-002-11** — Given the structural report of AC-002-10 on the committed fixtures, when its values are read, then for `structure_aware` the page-header share, the checkbox-grid share and the boundary-crossing share are 0, no field or section is missing and the maximum chunk size is at most 250 words. For `fixed_words` on the district fixture, the page-header share and the boundary-crossing share are above 0, so the report is shown to detect the noise it measures.
- **AC-002-12** — Given a database with no chunks for a requested strategy (an empty corpus, or a strategy never run), when the operator runs the structural report, then it exits with a non-zero code, names the strategy that has no chunks and writes no report file. Given an unreachable database or a missing schema, re-chunking and the structural report both exit with the fatal code and name the connection without the password, as `ingest` does (AC-001-12).
- **AC-002-13** — Given a stored chunk set whose chunks can no longer be located in the stored pages (for example, a `structure_aware` set produced by older rules and not re-chunked), when the operator runs the structural report, then the report file is still written and the summary printed; the metrics leave that document's set out; the report lists it under stale chunk sets with its source URL, strategy and the ordinal of the first chunk that could not be located; the summary tells the operator to run re-chunking; and the command exits with code 3.

## Amendment of spec 001
This spec amends **AC-001-07**. Spec 001 must be edited and re-approved together with this spec, and the plan decides how. This spec does not edit spec 001. The current AC-001-07 requires two things of *every* chunk, whatever its strategy: its text must be found in the concatenated text of its pages, and every page with extractable text must be covered. `structure_aware` leaves out removed content by design, so the amended criterion keeps those two clauses for `fixed_words` only.

Proposed wording for AC-001-07:
> Given an ingested corpus, when its chunks are inspected in the database, then every chunk belongs to exactly one document, records the chunking strategy and parameters that produced it, records a page range with 1 ≤ page_start ≤ page_end ≤ the document's page count, and has non-empty text. For the `fixed_words` strategy, the chunk text can be found in the concatenated text of the pages in its range, and every page with extractable text is covered by at least one chunk. Chunks of other strategies meet the guarantees of the spec that defines them (for `structure_aware`, AC-002-08). Chunks from different strategies can coexist for the same document without mixing.

Stored page text is unchanged: removed content is dropped in the chunker, not in the parser, so the `fixed_words` control stays exact (AC-002-01).

## Non-goals
- **Comparing strategies on retrieval quality**: recall@k, MRR, bootstrap intervals and paired tests on a golden set belong to the next R2 spec, together with embeddings, pgvector, full-text search, fusion and reranking. This spec has no golden set, no retrieval and no retrieval ACs. The roadmap stays as it is: R2 is delivered by this spec and the next one.
- **Quality gates on chunking**: the structural metrics of the real corpus are reported only. Gates arrive with the golden set in the retrieval spec.
- **Changing `fixed_words`**: it stays at 250 words with 40 overlap, unchanged, as the control.
- **Sentence-based and semantic (embedding-similarity) chunkers**: they go with the retrieval spec.
- **Token-based size caps**: the cap is in words here. Tokens are decided with the embedding model in the retrieval spec.
- **Prepending section labels to chunk text** for embedding or lexical search: the retrieval spec decides it. Here the label is only a chunk attribute.
- **Form 2010 page-1 metadata**: extracting the loose page-1 fields and which checkbox is ticked (from PDF layout coordinates) as document metadata is a later spec. In this spec page 1 produces no chunks.
- **Answering, citations to the user, refusal**: R3. No question is answered here, so no refusal AC applies. No model provider is called, so an unreachable provider is not a failure path of this spec. Malformed PDFs and duplicate documents keep spec 001's behaviour (AC-001-02, AC-001-08, AC-001-10). The duplicate concern specific to this spec is re-chunking idempotency (AC-002-09).
- **OCR of image-only pages and structured table extraction**: still out, as in spec 001.
- **Deleting old chunk sets or choosing a "winning" strategy**: the comparison that would justify it is the next R2 spec.

## Data and provenance
**Read.** The documents and pages stored by spec 001 in Postgres. Stored page text is not modified. The sources are the BSEE listing pages documented in spec 001. BSEE documents are US federal works, not subject to copyright (17 U.S.C. §105), with the third-party-image caveat recorded in spec 001.

**Created.**
- `structure_aware` chunk rows in Postgres, each with its strategy id, parameters and section label (a new attribute of a chunk). They are kept until the document is replaced (AC-001-09) or the database is rebuilt.
- The structural report under `data/reports/` (gitignored, never committed).

**Fixtures.** They are committed under `tests/fixtures/bsee/`, each recorded in `SOURCES.md` with its source URL, retrieval date and how it was trimmed. They are trimmed real documents taken from the already downloaded sample, without third-party images. The plan picks the files.
- One district report (MMS Form 2010) with text in its narrative fields, the repeated page header and the page-1 checkbox grid.
- One Safety Alert in the recent format, with heading lines ending in `:` and a Contact/Phone header block.
- One panel report trimmed to a few pages: its Contents page, its list of acronyms and two or three sections.
- Cases with no real fixture are generated at test time by `tests/support/pdfs.py`, as spec 001 does for its synthetic PDFs. These cases are an MMS-era "Notice No. N" alert, a document whose structure is not recognized, and a document with an image-only page.
- CI never contacts bsee.gov.

**Never committed.** The downloaded corpus, the sample used for the motivation figures, and the structural reports.

## Metrics
- **Structural report per strategy and document type** (AC-002-10):
  - chunk count and size distribution, to size the embedding and storage cost of the next R2 spec and to check the size cap;
  - share of chunks spanning more than one page, because citations point to a page and a wide range is a less precise citation;
  - page-header share and checkbox-grid share: the two kinds of noise measured in the sample (61% of district chunks, and 564 of 946 page-1 district chunks);
  - boundary-crossing share: whether a chunk mixes fields or sections;
  - coverage and structure-not-recognized counts, so that no narrative is silently lost and the fallback share is visible.
- **Chunking duration per strategy** (ingest and re-chunking), to know what re-chunking the full corpus costs on the target workstation.
- **No threshold on the real corpus.** The structural numbers of the real corpus are reported, not gated. The exact values on fixtures (AC-002-11) are test expectations. Retrieval and answer metrics, with their thresholds, start with the golden set of the next R2 spec.

## Open questions
- [x] **1. Where removal of page furniture lives, given AC-001-07** → in the chunker. Stored pages and `fixed_words` stay unchanged. AC-001-07 is amended so that its substring and coverage clauses apply to `fixed_words` only (see *Amendment of spec 001*). Spec 001 is edited and re-approved together with 002, and the plan decides how. The glossary's *Chunk* definition is updated (question 12).
- [x] **2. Form 2010 page 1** → dropped in 002: the checkbox grid and the loose page-1 fields produce no chunks (AC-002-04). Metadata extraction, including the ticked box from PDF coordinates, is a later spec.
- [x] **3. Size cap** → 250 words with no overlap, for every type. Splits prefer a paragraph break, then a sentence break, then a hard word cut. Tokens are decided with the embedding model in the retrieval spec.
- [x] **4. Section label in the text or beside it** → only beside it, in its own column, never prepended. The retrieval spec decides whether to prepend it for embedding.
- [x] **5. Panel front matter** → the Contents page and the figure list produce no chunks. The list of acronyms goes into its own chunk labelled `acronyms`. The page-number first line is removed (AC-002-05).
- [x] **6. Structure not recognized** → a marked fallback: fixed windows under `structure_aware` (250 words, no overlap) labelled `structure_not_recognized`. The document does not count as failed, and the reports list it (AC-002-07).
- [x] **7. Sentence-based and semantic chunkers** → out of 002, with the retrieval spec.
- [x] **8. Safety Alerts** → section boundaries are heading lines ending in `:`. Old MMS "Notice No. N" alerts are one chunk if they fit and are otherwise split by paragraph under the cap. Only the Contact and Phone lines are removed; the alert number, date and title stay, and so do photo captions (AC-002-06).
- [x] **9. Corpus-level targets** → reported only, no gate. The fixtures keep exact expectations (AC-002-11), and quality gates arrive with the golden set in the retrieval spec.
- [x] **10. Strategy identity** → one strategy id, `structure_aware`, which dispatches on `doc_type` and supports all three types. Configuration per document type still decides which strategies run (AC-002-01, AC-002-02).
- [x] **11. Re-chunking** → in scope, without download (AC-002-09).
- [x] **12. Glossary** → the definitions below, applied to `docs/glossary.md` with this draft.
  - Amended **Chunk**: A piece of text from one document, with its page range, its chunking strategy and (for `structure_aware`) its section label, that is indexed and retrieved. A `fixed_words` chunk is a contiguous slice of its pages' text. A `structure_aware` chunk keeps the words of its pages in order and contiguous, except for removed content.
  - **Chunking strategy**: An implementation of the `Chunker` interface with its parameters, recorded on every chunk. `fixed_words` is the control; `structure_aware` follows the structure of each document type.
  - **Page furniture**: Text repeated on the pages of a document that is not content: the Form 2010 page header, the page-number line of panel reports.
  - **Narrative field**: A numbered free-text field of MMS Form 2010 (17 to 24), the unit of `structure_aware` chunks for district reports.
  - **Section label**: The field or section a chunk belongs to, stored beside the chunk text and never inside it. Special values: `acronyms`, `structure_not_recognized`.
  - **Structural report**: The report of chunk quality per strategy and document type (size, page span, page-furniture and checkbox-grid noise, boundary crossings, coverage), computed without a golden set.
- [x] **13. Size cap in tests** → the cap is a recorded parameter (250 by default); a test may set it, so AC-002-06 can check the "fits" case regardless of the fixture alert's length.
- [x] **14. Generated fixtures** → three cases with no real fixture are generated at test time by `tests/support/pdfs.py`, as in spec 001: an MMS "Notice No. N" alert, a document whose structure is not recognized, and a document with an image-only page.
- [x] **15. Panel coverage** → checked against the section headings present in the trimmed fixture, not against every entry of its Contents page.
- [x] **16. Panel page-number line position** (plan P1) → removed when it is the first or last line of a panel page and holds only a page number, arabic or roman (*Removed content*, AC-002-05).
- [x] **17. Text before the first section** (plan P2) → labelled `preamble`, so AC-002-08 skips nothing. `alert` labels a Safety Alert with no heading lines (*Section label*, glossary).
- [x] **18. Alert size** (plan P3) → the size cap stays 250 words for alerts. In the sample about a third of alerts fit whole; the rest split at heading lines or paragraph breaks. The structural report shows the real share.
