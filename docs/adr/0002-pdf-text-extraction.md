# ADR-0002: PDF text extraction with pypdfium2

- **Status:** proposed
- **Date:** 2026-11-04
- **Originating spec:** 001
- **Decided by:** Tiago Meilan

## Context
Spec 001 needs page-accurate text from about 1,300 BSEE PDFs (AC-001-05). It also needs to detect pages with no text layer (AC-001-06) and to fail cleanly on corrupt files (AC-001-10). The repository is MIT-licensed and meant to run as a service, so the licence of the dependency matters. The ingestion runs on a workstation and in CI without a GPU.

## Options considered

### Option A: pypdfium2 (Python bindings to Google's PDFium)
- For:
  - It uses the same engine as Chrome's PDF viewer, so it is robust with malformed files.
  - It is fast (native code) and extracts text page by page.
  - It ships prebuilt wheels for Windows, macOS and Linux.
  - Licence: Apache-2.0 / BSD-3-Clause.
- Against:
  - The text API is lower-level, with no table structure.
  - Its layout analysis is less tunable than pdfminer's.
- Cost / risk: low. If table structure becomes necessary later, a second extractor can be added for those pages only.

### Option B: PyMuPDF (fitz)
- For: the best speed and text quality of the group, rich layout data, built-in OCR hooks.
- Against: **AGPL-3.0** (or a commercial licence). Using it in a network service would force the service's source to be AGPL. That conflicts with the MIT licence and with how a company would deploy this.
- Cost / risk: a licence risk that a reviewer from industry would rightly flag.

### Option C: pdfplumber / pdfminer.six
- For: MIT licence, good table extraction (pdfplumber), detailed layout analysis.
- Against: pure Python, about 10–50× slower than PDFium on large reports, and it chokes on some malformed files.
- Cost / risk: a first full ingestion measured in hours instead of minutes.

### Option D: pypdf
- For: BSD licence, pure Python, simple.
- Against: the weakest text extraction of the group (spacing and ordering issues), and slow on large files.

## Decision
Use **pypdfium2** for text extraction and page counting. It is fast, robust with real-world PDFs, page-accurate, and has a permissive licence compatible with an MIT service.

## Consequences
- `parse_pdf` depends only on pypdfium2. Synthetic test PDFs are generated with fpdf2 (dev dependency only).
- Table text comes out in reading order, without structure. That is accepted by spec 001.
- If R2's evaluation shows that tables or column order hurt retrieval, revisit with a page-level fallback (for example pdfplumber on pages flagged as tabular) rather than replacing the extractor.
- Watch: the share of pages with garbled order in the first ingestion report, and PDFium wheel availability for the Python versions in use.
