---
id: "001"
title: Corpus ingestion
status: approved
roadmap_refs: ["R1", "brief §3.1", "brief §6"]
approved_hash: sha256:a4ad0a4c863d69f934d3e33c64131ad7da6a11af33a1ed2e79738483a3b16640
approved_at: 2026-11-05
approved_by: Tiagod
---

# 001 — Corpus ingestion

## Problem
BSEE publishes its offshore lessons learned as hundreds of separate PDFs: Safety Alerts, panel investigation reports and district investigation reports. Their structure is uneven, some tables are scanned, and they cannot be searched across documents (brief §1). Retrieval (R2) and grounded answering (R3) both need a local, reproducible **corpus** where every **chunk** traces back to a **document**, a **page** and the exact public file it came from (brief §3.1, constitution §12). Every later roadmap item depends on this, so it comes first.

## Users
- **System operator**: builds and validates the **manifest**, runs `ingest`, reads the ingestion report, and re-runs it when BSEE publishes new documents.
- **The system itself**: R2 and R3 read the documents, pages and chunks stored here. In this spec nothing is retrieved or answered.
- Safety and operations engineers do nothing directly in this spec. They benefit later from the page-accurate provenance it stores.

## Stories
- As a system operator, I want a versioned manifest of BSEE documents, so that anyone can rebuild the same corpus without the raw files being committed.
- As a system operator, I want to download the corpus politely and with full provenance (source URL, retrieval date, sha256), so that every answer can be traced back to a public file and BSEE's servers are not hammered.
- As a system operator, I want each document split into pages numbered as in the original PDF and into chunks that keep their page range, so that citations point to the page an engineer will actually open.
- As a system operator, I want re-running `ingest` to skip unchanged documents and replace changed ones atomically, so that I can update the corpus without duplicates or half-written documents.
- As a system operator, I want one broken PDF to be reported without aborting the run, plus a report of what happened, so that a large ingestion is not lost to a single bad file.

## Acceptance criteria
- **AC-001-01** — Given recorded copies of the BSEE listing pages for Safety Alerts, panel investigation reports and district investigation reports (and the detail pages they link to), served locally, when the operator builds the manifest, then the manifest file lists one entry per PDF with its document type (`safety_alert`, `panel_report` or `district_report`), its absolute source URL and the URL of the page it was found on, contains no duplicate source URL, and building it twice from the same input produces byte-identical files.
- **AC-001-02** — Given a manifest that is malformed (an entry without a source URL, an unknown document type, a duplicate source URL, or no entries at all), when the operator runs `ingest`, then the command exits with a non-zero code, names each offending entry (or states that the manifest is empty), and nothing is downloaded or written to the database.
- **AC-001-03** — Given a valid manifest whose PDFs are served by a local test server, when the operator runs `ingest`, then each document is stored in Postgres with its source URL, document type, UTC retrieval timestamp and the sha256 of the downloaded bytes, the raw file is saved under `data/`, and its sha256 equals the stored hash. If a manifest entry declares an expected hash that does not match, the document is recorded as failed with reason `hash_mismatch` and nothing from it is stored.
- **AC-001-04** — Given a local test server that records request headers and timestamps and returns a transient error (HTTP 429, HTTP 5xx or a timeout) a configured number of times before succeeding, when the operator runs `ingest`, then every request carries the configured User-Agent, which names the project and its repository URL and contains no e-mail address; consecutive requests never exceed the configured rate; transient errors are retried up to the configured limit and then succeed or are recorded as failed; and an HTTP 404 is recorded as failed without being retried.
- **AC-001-05** — Given a committed text-based sample PDF with N pages, each with a known text marker, when it is ingested, then exactly N pages are stored for that document, numbered 1 to N, and the text stored for page k contains the marker of page k of the original PDF and no marker from any other page.
- **AC-001-06** — Given a committed sample PDF whose pages have no text layer (image-only), when it is ingested, then the document and its pages are stored, those pages are flagged as image-only, no chunk is created from them, the document appears in the ingestion report under image-only documents, and the run does not count it as failed.
- **AC-001-07** — Given an ingested corpus, when its chunks are inspected in the database, then every chunk belongs to exactly one document, records the chunking strategy and parameters that produced it, records a page range with 1 ≤ page_start ≤ page_end ≤ the document's page count, has non-empty text that can be found in the concatenated text of the pages in its range, and, for each strategy, every page with extractable text is covered by at least one chunk. Chunks from different strategies can coexist for the same document without mixing.
- **AC-001-08** — Given a corpus already ingested from a manifest, when the operator runs `ingest` again and every downloaded file has the same sha256 as the stored one, then each document is reported as `skipped_unchanged`, the numbers of document, page and chunk rows are the same as before the run, and no source URL has more than one document row.
- **AC-001-09** — Given an ingested document whose file at the same source URL now has different bytes, when the operator runs `ingest` again, then that document keeps a single document row with the new sha256 and retrieval timestamp, all its previous pages and chunks are gone and replaced by the new ones, and it is reported as `replaced`. If processing the new version fails at any point, the previous version stays in the database unchanged and the document is reported as failed.
- **AC-001-10** — Given a manifest in which one entry points to a corrupt PDF and another to a URL that returns 404, alongside valid entries, when the operator runs `ingest`, then every valid document is fully ingested, each failure is listed in the report with its source URL, stage (`download`, `parse` or `store`) and reason, and the command exits with a code that is different from both full success and a fatal error.
- **AC-001-11** — Given any `ingest` run that gets past validation, when it finishes, then a machine-readable report is written under `data/` and a summary is printed to stdout, both with the manifest entry count, documents ingested, skipped unchanged, replaced, failed and image-only, total pages and chunks stored, and the wall-clock duration of the run and of each stage (download, parse, chunk, store).
- **AC-001-12** — Given Postgres is unreachable or its schema is missing, when the operator runs `ingest`, then the command exits with a non-zero fatal code before downloading anything and prints an error that names the database connection (without the password) as the cause.

## Non-goals
- **Comparing chunking strategies**: R1 ships one baseline strategy behind a chunker interface and stores which strategy produced each chunk. Adding other strategies (structure-aware, sentence-based, semantic) and comparing them on the golden set is R2, because it needs retrieval metrics.
- **Embeddings, pgvector indexes and full-text indexes**: R2 (spec for hybrid retrieval). This spec stores text only.
- **Search, question answering and citations to the user**: R2 and R3.
- **OCR of image-only pages**: this spec only detects and reports them (AC-001-06). If the first ingestion report shows a large share of image-only pages, OCR becomes its own roadmap item.
- **Structured table extraction** (cells, rows, columns): table text is kept as it appears in the page text, in reading order. Turning tables into structured data is left to a later spec if the evaluation shows it is needed.
- **Scheduled or automatic re-ingestion** (cron, watching BSEE for new documents): the operator runs `ingest` by hand. R5 may add scheduling.
- **The `data.bsee.gov` Incident Investigations grid** (an ASP.NET data grid) and its incident metadata (lease, block, status): not used in this spec; the HTML listing pages are the source.
- **Older reports not on the current listing pages**: the district reports behind "View Archive" (2005 to 2013) and panel reports before 2017. They can be added to the roadmap once their links are located.
- **Other BSEE material** (press releases, research reports, BOEM documents): out of scope unless added to the roadmap.
- **An HTTP API for ingestion**: R5.
- If this slice turns out too large in the plan, the first thing to cut into a later spec is **building the manifest from the listing pages** (AC-001-01). In that case the first manifest would be curated by hand and validated by AC-001-02.

## Data and provenance
**Sources** (checked on 2026-11-04):

| Document type | Listing page | Shape of the listing | Approximate size |
|---|---|---|---|
| Safety Alerts | https://www.bsee.gov/guidance-and-regulations/guidance/safety-alerts-program | Paginated HTML table (`?page=N`, 50 rows per page, about 13 pages) with number, title, date and safety category; category filter and sort by query parameters. Each title links to an HTML detail page (`/safety-alerts/<slug>`) that holds the PDF link (for example `/sites/bsee.gov/files/2026-10/MMA%20Safety%20Alert%20526_Prevent%20Battery%20Ruptures_30OCT26.pdf`). The alert text is only in the PDF. | Hundreds. The latest number seen is 526 (2026-10-30). The page count suggests about 600, but the numbering suggests about 525 and has gaps (493 missing). |
| Panel investigation reports | https://www.bsee.gov/what-we-do/incident-investigations/panel-investigation-reports (also reachable as https://www.bsee.gov/node/13904) | Paginated HTML list (`?page=0..2`, 15 rows per page) with report number, block and title. Each title links to a detail page (`/panel-investigation/<slug>`) that holds the PDF link (for example `/sites/bsee.gov/files/2024-08/MP%2064%20No-19%20Report%2030May24.pdf`, 3.9 MB, 22 pages). | Tens on the current list (about 45; numbers 2017-002 to 2024-01). `data.bsee.gov` states that panel reports since 1992 exist; where older ones are linked has not been confirmed. |
| District investigation reports | https://www.bsee.gov/what-we-do/incident-investigations/district-investigation-reports (also https://www.bsee.gov/node/14050) | One HTML page with tables grouped by year (2026 back to 2014). Each row has date, time, lease, area/block and accident type, and the date links straight to the PDF. No pagination or search form; a "View Archive" link exists. PDF paths vary: `/sites/bsee.gov/files/YYYY-MM/…`, `/sites/bsee.gov/files/reports/safety/…`, `/sites/bsee.gov/files/reports/incident-and-investigations/…`, some relative without the leading slash. | Hundreds (estimated at 700 or more on the page; about 28 in 2026, 39 in 2025, 34 in 2024). `data.bsee.gov` states that district reports since 2005 are available. |

The BSEE status grid at https://data.bsee.gov/Other/DataTables/IncidentInvestigations.aspx lists about 2,031 formal investigations (panel and district, pending and complete). Not all of them have a published report. It is not a source for this spec.

**PDF characteristics.** One recent panel report was checked: it has embedded fonts and a tagged structure, which suggests extractable text, and it also contains images. Whether older reports (2005 to around 2013) and older Safety Alerts are scanned images has **not** been confirmed. The share of image-only pages will be measured by the first full ingestion report (AC-001-11).

**Licence.** BSEE is a US federal agency. Works prepared by US government employees as part of their official duties are not subject to copyright (17 U.S.C. §105). BSEE's own site policy page (https://www.bsee.gov/node/14531, as summarised by a search result; the page returned HTTP 403 to automated fetch) says materials produced by federal agencies are generally in the public domain, but **not all materials on the site are**: some, especially images, come from third parties. Whether every report and alert PDF is entirely public domain (for example, operator photographs or contractor figures embedded in a panel report) is not confirmed, so committed fixtures avoid documents with third-party images. The repository records the source URL of every document, and its README credits BSEE as the source.

**Automated access.** https://www.bsee.gov/robots.txt (fetched 2026-11-04) is a standard Drupal file. For `User-agent: *` it disallows `/admin/`, `/search/`, `/user/*`, `/node/add/` and similar, and has no `Crawl-delay`. It does not disallow `/safety-alerts/`, `/panel-investigation/`, `/what-we-do/` or `/sites/bsee.gov/files/`. It points to `https://www.bsee.gov/sitemap.xml`. No BSEE-specific rate limit or usage policy for automated download was found. The site returned HTTP 403 to some automated fetches (node/14531), so bot protection may exist. Ingestion therefore uses a conservative default rate, an identifiable User-Agent (project name and repository URL, no personal e-mail), retries with backoff, and honours robots.txt.

**What is stored and where.**
- `data/` (gitignored, never committed): the downloaded PDFs, the recorded listing pages used to build the manifest, and the ingestion reports.
- Postgres: documents (source URL, document type, listing page URL, retrieval timestamp, sha256, page count, image-only flag), pages (document, page number from 1, text, image-only flag) and chunks (document, page range, text). Kept until the document is replaced or the database is rebuilt.
- Repository (committed): the manifest; a few small sample PDFs under `tests/` as fixtures, each with its source URL recorded next to it; recorded HTML listing pages trimmed to what the tests need, with their source URL. CI never contacts bsee.gov: tests use a local server and committed fixtures.

## Metrics
- **Per-stage wall-clock duration** (download, parse, chunk, store) and total run duration: to size full re-ingestion on the target workstation and to find the slow stage.
- **Counts per run**: manifest entries, ingested, skipped unchanged, replaced, failed (by stage and reason), image-only documents, pages, chunks. They show whether incremental re-ingestion works and how much of the corpus is unusable without OCR.
- **Bytes downloaded and number of HTTP requests, including retries**: to check that a re-run on an unchanged corpus is cheap and that the rate limit is respected.
- **Share of image-only pages** over the corpus: the evidence needed to decide whether OCR deserves a spec.
- **Chunk size distribution** (min, median, max characters or tokens): an input to the R2 retrieval design. No quality threshold applies in this spec; retrieval quality starts with R2's golden set.

## Open questions
- [x] **Scope of the first corpus** → everything on the current listing pages: all Safety Alerts on the listing, the panel reports on the current list (2017 onwards) and the district reports on the current page (2014 to 2026). Roughly 1,300 PDFs.
- [x] **Date range for district reports** → current page only (2014 to 2026). The "View Archive" reports (2005 to 2013) and the older panel reports are out of R1; they can be added to the roadmap once their links are located.
- [x] **OCR** → out of R1. Image-only pages are detected and reported (AC-001-06). If the first ingestion report shows a large share of image-only pages, OCR becomes its own roadmap item; where it goes in the order is decided then, with that data.
- [x] **Tables** → table text in page reading order is enough for R1. Structured extraction only if the R2/R4 evaluation shows it is needed.
- [x] **Licence of embedded third-party material** → record the source URL of every document and credit BSEE in the README. Committed sample fixtures are limited to documents with no third-party images.
- [x] **Default download rate and retry limit** → about 1 request per second, a few retries with exponential backoff; a first full run of about an hour is acceptable. Exact values go in the plan and are configurable.
- [x] **Manifest refresh policy** → regenerated from the listing pages on demand only. `ingest` does not contact the listing pages to look for new entries.
- [x] **Safety Alerts with several attachments, or reports in several parts** → one document per PDF.
- [x] **Documents removed from BSEE** → if an already ingested document later returns 404, the stored version is kept and the download is reported as failed.
- [x] **Glossary** → accepted: *Document type*, *Image-only page*, *Ingestion report*, *Ingestion run* (added to `docs/glossary.md`).
