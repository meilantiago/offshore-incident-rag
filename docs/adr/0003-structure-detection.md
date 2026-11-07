# ADR-0003: Structure detection from extracted line text with per-type rules

- **Status:** proposed
- **Date:** 2026-11-07
- **Originating spec:** 002
- **Decided by:** Tiago Meilan (pending, with the approval of spec 002)

## Context
Spec 002 chunks each BSEE document type by its own structure: Form 2010 narrative fields 17–24 for district reports, Contents-listed sections for panel reports, heading lines for Safety Alerts. It also removes page furniture (Form 2010 page header, panel page numbers, alert Contact/Phone lines). The text is already extracted page by page with pypdfium2 (ADR-0002) and stored line by line. The pipeline runs on a workstation and in CI without a GPU or network access to a model, and the repository is MIT-licensed. Three document types cover the whole corpus (690 documents in the local sample: 567 district, 88 alerts, 35 panel).

## Options considered

### Option A: rules over the extracted line text, one function per document type
- For:
  - No new dependency; runs on the stored page text, so `rechunk` needs no PDF and no download.
  - Deterministic and fast; every rule is unit-testable on committed fixtures.
  - The structures are regular: Form 2010 field titles appear in 94–100% of district reports; panel reports carry a Contents page.
- Against:
  - Layout drift across eras (MMS vs BSEE) needs rule variants (for example two page-number positions in panel reports).
  - The ticked checkbox on Form 2010 page 1 cannot be recovered from text alone (out of scope in spec 002).
- Cost / risk: low. Unrecognized documents fall back visibly and the structural report shows the fallback share.

### Option B: PDF layout coordinates (pypdfium2 character boxes, font sizes)
- For: headings by font size, checkbox detection, robust to line-order quirks.
- Against: needs the raw PDF at chunk time (no re-chunking from stored text), much more code, and the same per-type rules on top.
- Cost / risk: medium; worth it later for Form 2010 page-1 metadata, not for chunk boundaries.

### Option C: a document-layout library (unstructured, docling, LayoutParser)
- For: generic titles/sections/tables out of the box.
- Against: heavy dependencies (ML models, sometimes OCR stacks), slower, a second text extraction that may disagree with the stored pages and break page-accurate citations, generic labels that do not know Form 2010 field numbers.
- Cost / risk: high for three regular document types.

### Option D: an LLM that segments each document
- For: flexible with irregular layouts.
- Against: non-deterministic, costly over ~1,300 documents, needs a model provider in ingestion, and the output must still be verified word by word against the pages.
- Cost / risk: high; contradicts the "no provider called" scope of spec 002.

## Decision
Use **rules over the extracted line text, one function per document type** (`ingestion/structure.py`), shared by the `structure_aware` chunker and the structural report, with a labelled fixed-window fallback when the structure is not recognized.

## Consequences
- Re-chunking works from Postgres alone; no PDF or network is needed.
- Rule changes bump the `version` parameter of `structure_aware`, so `rechunk` regenerates the chunk sets.
- Watch: the structure-not-recognized share and the missing-section list in the structural report on the full corpus. A high fallback share for one type is the signal to add a rule variant or move to Option B for that type.
