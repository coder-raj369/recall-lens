# ADR-0004: Defer USDA FSIS ingestion until API access is available

- **Status:** Accepted
- **Date:** 2026-09-25

## Context

The corpus was planned to cover four agencies. The USDA FSIS Recall API (`https://www.fsis.usda.gov/fsis/api/recall/v/1`), which covers meat, poultry and egg products, returned `403 Access Denied` to every automated client tried during Phase 1:

| Client | Result |
|---|---|
| Local development machine (non-US network) | 403; all `usda.gov` pages are blocked |
| GitHub Actions `ubuntu-latest` runner (US cloud network) | 403 on the API endpoint |
| Hosted web-fetch service | 403 on the API and its PDF documentation |

The block comes from the site's edge protection, not from the request. Working around bot or geographic protection is out of bounds for this project. The alternatives found (the data.gov annual summary dataset and the recalls.gov feed) either link back to the same blocked domain or no longer exist.

## Decision

Ship Phase 1 with CPSC, FDA and NHTSA. Do not write an FSIS connector against an unverified schema. Revisit when one of the following is true:

1. FSIS grants API access or allow-lists the ingestion host (a request can be made through the FSIS developer resources page), or
2. The ingestion job runs from an environment the API accepts, verified by a recorded sample payload.

## Consequences

- Meat, poultry and egg products regulated by FSIS are not covered. The README states this gap explicitly, and the advisor must not imply coverage for those products.
- FDA food recalls still cover most other food categories.
- The normalized `Recall` model and `agency` constraint already include `fsis`, so adding the connector later needs no schema change.
