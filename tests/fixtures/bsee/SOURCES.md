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

## Spec 002 fixtures (structure-aware chunking)

Taken from the local sample ingested with spec 001, whose files were retrieved from bsee.gov on **2026-11-05**
(`retrieved_at` of each document row) with the same User-Agent. They were cut on 2026-11-07 with
`tests/support/trim_pdf.py` (pypdfium2), which keeps whole pages and their published text layer; the text that
`parse_pdf` extracts from each committed file is identical to the text it extracts from the same pages of the source
file (checked when cutting). No third-party photograph is committed: the district and panel pages kept have no
images, and the one photograph of the Safety Alert was removed (object and pixel data); the federal letterhead and
seal stay.

| File | Source URL | Source sha256 | Trimming | Committed sha256 |
|---|---|---|---|---|
| `district-mp-42-l-2020.pdf` | https://www.bsee.gov/sites/bsee.gov/files/mp-42-cantium-9-sep-2020.pdf (listed on https://www.bsee.gov/what-we-do/incident-investigations/district-investigation-reports) | `0030898393870d994a14e5e1e8df72bbfa0b552e369d2255c6f0b90f0b35d4df` | None: the original file, 3 pages, 619,231 bytes, no images. MMS Form 2010, Main Pass 42 L, Cantium LLC, 9 Sep 2020. Page 1 is the checkbox grid; fields 17–23 have text (17 over 250 words), 24 has only its title; repeated header lines `For Public Release`, `MMS - FORM 2010 PAGE: N OF 3`, `EV2010R 05-JAN-2021`. | same as source |
| `panel-mms-2009-042-trimmed.pdf` | https://www.bsee.gov/sites/bsee.gov/files/incident-statisticssummaries-fatalities/reports/2009-042-pdf.pdf (detail page https://www.bsee.gov/panel-investigation/investigation-of-fatality-from-falling-load-main-pass-block-30-well-no-a-14) | `d10324074a861ca0d1f3420def367185bb8dd98cecb93a10fc00f541c14db0ee` | Pages 3–9 of 36 kept (`--pages 3-9`), 23,058 bytes: Contents (i), List of Figures and Tables (ii), Abbreviations and Acronyms (1–2), Executive Summary (3–4), Introduction with Authority and Background (5). The page-number line is the first line of every page. No images on those pages. OCS Report MMS 2009-042, Main Pass Block 30 fatality, 7 March 2009. | `de017e0da8bb6a2cc11e8af9c0360b0066db77fcbdadd068e8963f55be1ca848` |
| `safety-alert-526-trimmed.pdf` | https://www.bsee.gov/sites/bsee.gov/files/2026-10/MMA%20Safety%20Alert%20526_Prevent%20Battery%20Ruptures_30OCT26.pdf (detail page https://www.bsee.gov/safety-alerts/mma-safety-alert-526-prevent-battery-ruptures) | `991f38066a14e750940ea5c4fa5065ef27d4c544f4ea3a4ab93bb5d4162e1a03` | All 3 pages kept; the photograph on page 1 (443 x 225 pt, 848 x 430 px, two battery photos behind the Figure 1 and Figure 2 captions) removed with `--drop-images-over 60000`, 303,906 bytes. The captions stay. Recent format: `Safety Alert No.`, `Date:`, `Contact:`, `Phone:`, title, heading lines `Background:`, `Incident 1 (Figure 1):`, `Incident 2 (Figure 2):`, `Incident Findings:`. | `669a82c31931728a0362f7c7103b125300335b0406080f27b13552a6399b0af1` |

Generated at test time by `tests/support/pdfs.py` (not committed): an MMS-era "Notice No. N" alert with numbered
paragraphs and no heading lines, a district report without fields 17–24, a panel report without a Contents page or
headings, and a Form 2010 district report with an image-only page between two text pages.
