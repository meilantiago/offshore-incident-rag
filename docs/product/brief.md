# Product brief

## 1. Problem
The US Bureau of Safety and Environmental Enforcement (BSEE) publishes investigation reports and Safety Alerts about incidents on offshore oil and gas facilities: well control events, crane and lifting accidents, fires, dropped objects, fatalities. The lessons in them are valuable to any operator, in the Gulf of Mexico or in Vaca Muerta, but they are spread across hundreds of PDFs with uneven structure, scanned tables and no cross-document search.

A safety or operations engineer preparing a job safety analysis, a management-of-change review or a toolbox talk wants to ask questions like:

- "Which incidents involved a failure of the crane boom hoist, and what root causes did the panels identify?"
- "What did BSEE recommend after well control events during plug and abandonment?"
- "Has a dropped object from a derrick ever been linked to a missing secondary retention?"

Keyword search finds documents, not answers, and a general-purpose chatbot answers confidently without sources. In a safety context an unsupported answer is worse than no answer.

## 2. Users
- **Safety / HSE engineer**: wants cited answers and the exact pages to read.
- **Operations or drilling engineer**: wants precedents for a specific operation or equipment.
- **System operator** (whoever runs the service): wants to ingest new reports, know what the system costs and how fast it is, and know when quality drops.

## 3. What the product does
1. Ingests the public BSEE corpus with full provenance (source URL, retrieval date, content hash), incrementally.
2. Retrieves evidence with hybrid search (lexical + semantic) and reranking.
3. Answers questions with citations to document and page, and refuses when the corpus does not support an answer.
4. Measures itself: retrieval and answer quality on a frozen evaluation set, with confidence intervals, as a CI gate.
5. Runs as a service (HTTP API) with structured logs and per-stage latency, locally with open models or with a hosted model provider through configuration.

## 4. Principles
- **Cited or silent** (constitution §5).
- **Measured, not demoed**: quality claims come from the evaluation reports (constitution §6).
- **Runs on modest hardware**: the default configuration works on a laptop-class GPU or CPU with open models; hosted providers are optional.
- **Reproducible**: anyone can rebuild the corpus from the manifest and reproduce the evaluation numbers.

## 5. Out of scope
- Real-time operational data, sensor streams or proprietary company documents.
- Regulatory or legal advice: the system points to documents, it does not interpret obligations.
- A polished end-user web UI. The interface is a CLI and an HTTP API.
- Fine-tuning models.

## 6. Data
- Source: BSEE public pages for incident investigations and Safety Alerts. US federal government works are in the public domain; the exact pages and terms are confirmed in spec 001.
- The raw corpus is downloaded by the ingestion pipeline and never committed. Small sample PDFs may be committed as test fixtures with their source URL.
