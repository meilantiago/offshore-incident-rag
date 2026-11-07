# BSEE test fixtures: sources

All files were retrieved from bsee.gov on **2026-11-04** with the User-Agent
`offshore-incident-rag/0.0.1 (+https://github.com/meilantiago/offshore-incident-rag)`.
BSEE is a US federal agency; its own works are not subject to copyright (17 U.S.C. §105). Source: BSEE, https://www.bsee.gov.

The HTML pages are **trimmed**: scripts, styles, most of the site navigation and most table rows were removed. The
markup of what the parsers read (tables, cells, links, pager, attachment field) is kept as published, including
the root-relative links (`/safety-alerts/…`, `/sites/bsee.gov/files/…`) and one district link with no leading slash.
Tests serve these files from a local server whose address replaces `https://www.bsee.gov` (`BSEE_BASE_URL`).

| File | Source URL | Notes |
|---|---|---|
| `safety_alerts_listing_page0.html` | https://www.bsee.gov/guidance-and-regulations/guidance/safety-alerts-program (`?page=0`) | 3 of 50 rows kept (526, 523, 521). Row 523 links to a detail page outside `/safety-alerts/`, as on the live page. |
| `safety_alerts_listing_page1.html` | same, `?page=1` | Rows chosen for the test: 521 again (a row repeated across pages, to test de-duplication) and 469 (the committed PDF below). |
| `safety_alerts_listing_empty.html` | same, `?page=40` | A page past the end: the live site answers 200 with the form and pager but no table. |
| `safety_alert_detail.html` | https://www.bsee.gov/safety-alerts/mma-safety-alert-526-prevent-battery-ruptures | Detail page with the PDF attachment link. Tests derive the other detail pages from it by swapping the attachment link. |
| `panel_listing_page0.html` | https://www.bsee.gov/what-we-do/incident-investigations/panel-investigation-reports (301 to `/what-we-do/incident-investigations/offshore-incident-investigations/panel-investigation-reports`) | 2 of 15 rows kept (2024-01, 2023-001). |
| `panel_listing_empty.html` | same, `?page=9` | Past the end: no table. |
| `panel_detail.html` | https://www.bsee.gov/panel-investigation/bsee-panel-investigation-final-report-gc40 | Detail page with the PDF attachment link. |
| `district_listing.html` | https://www.bsee.gov/what-we-do/incident-investigations/district-investigation-reports (301 to `/what-we-do/incident-investigations/offshore-incident-investigations/district-investigation-reports`) | Two year tables (2026, 2022), 2 rows each. `sites/bsee.gov/files/cox-hi-472-a-21-oct-2022.pdf` has no leading slash on the live page; resolved against the page URL it 404s on bsee.gov, resolved against the site root it is the PDF (checked 2026-11-04). |
| `safety-alert-469.pdf` | https://www.bsee.gov/sites/bsee.gov/files/2023-10/BSEE%20Safety%20Alert%20469%20-%20BSEE%20Identifies%20Medical%20Evacuation%20and%20Emergency%20Hazards%20During%20Risk-Based%20Inspections.pdf | Safety Alert No. 469 (2023-10-20), 3 pages, text layer, 291,096 bytes, sha256 `9bafefd1b20bd498b50cdbe795feddd2d656eabce03a69bff9fc7f3bfb303bb6`. The only images are the BSEE logo and letterhead banner; no third-party photographs or figures. |

Synthetic PDFs (text with page markers, image-only, corrupt) are generated at test time by `tests/support/pdfs.py`
and are not committed.

Derived fixture (not a recording): `safety_alert_detail_no_pdf.html` is `safety_alert_detail.html` edited by hand: the
attachment field (the PDF link) is removed and the title changed to Safety Alert 395, to reproduce a BSEE detail page
published with no file (https://www.bsee.gov/safety-alerts/bsee-safety-alert-395-electrical-equipment-in-hazardous-locations-increase-risk-of, observed 2026-11-05).
