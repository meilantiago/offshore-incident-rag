# Glossary

Use these names in code, specs and tests.

| Term | Meaning |
|---|---|
| **Corpus** | The set of source documents the system can answer from. |
| **Manifest** | Versioned list of corpus documents (source URL, type, expected hash). Rebuilds the corpus. |
| **Document** | One source file (a PDF report or alert) with its provenance: source URL, retrieval date, content hash. |
| **Document type** | `safety_alert`, `panel_report` or `district_report`. |
| **Page** | A page of a document, numbered as in the original PDF (1-based). |
| **Image-only page** | A page with no extractable text layer (scanned). Detected and reported; not chunked. |
| **Ingestion run** | One execution of `ingest` over a manifest. |
| **Ingestion report** | The machine-readable summary of an ingestion run: counts, failures by stage and reason, durations. |
| **Chunk** | A piece of text from one document, with its page range, its chunking strategy and (for `structure_aware`) its section label, that is indexed and retrieved. A `fixed_words` chunk is a contiguous slice of its pages' text. A `structure_aware` chunk keeps the words of its pages in order and contiguous, except for removed content. |
| **Chunking strategy** | An implementation of the `Chunker` interface with its parameters, recorded on every chunk. `fixed_words` is the control; `structure_aware` follows the structure of each document type. |
| **Page furniture** | Text repeated on the pages of a document that is not content: the Form 2010 page header, the page-number line of panel reports. |
| **Narrative field** | A numbered free-text field of MMS Form 2010 (17 to 24), the unit of `structure_aware` chunks for district reports. |
| **Section label** | The field or section a chunk belongs to, stored beside the chunk text and never inside it. Special values: `acronyms`, `structure_not_recognized`. |
| **Structural report** | The report of chunk quality per strategy and document type (size, page span, page-furniture and checkbox-grid noise, boundary crossings, coverage), computed without a golden set. |
| **Retrieval** | Finding the chunks most relevant to a question. **Hybrid** retrieval combines lexical (full-text) and semantic (embedding) search. |
| **Reranking** | Re-ordering retrieved chunks with a more expensive model (a cross-encoder). |
| **Evidence** | The chunks passed to the generator for one question. |
| **Citation** | A reference in an answer to a chunk of the evidence: document, page, chunk id. |
| **Grounded answer** | An answer whose every claim is supported by its citations. |
| **Refusal** | The system's explicit statement that the corpus does not support an answer. A correct refusal is a success. |
| **Provider** | An implementation of the `LLMProvider` interface (Ollama, a hosted API). |
| **Golden set** | Frozen, human-curated questions with their relevant chunks and reference answers, in `eval/golden/`. |
| **Candidate** | A proposed golden item in `eval/candidates/`, waiting for human review. |
| **Baseline** | The stored metrics of the configuration on `main`, used by the regression gate. |
| **Gate** | An automated harness check (`scripts/check.py`) or a human approval (gate 1: spec; gate 2: merge). |
| **AC** | Acceptance criterion of a spec, `AC-NNN-XX`. |
