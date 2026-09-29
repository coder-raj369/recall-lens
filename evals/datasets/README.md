# Evaluation datasets

## Identifier extraction

| File | Records | Source | Purpose |
|---|---|---|---|
| `extraction_dev.jsonl` | 100 (40 FDA, 35 CPSC, 25 NHTSA) | Recalls dated 2026 | Error analysis while developing the extractors |
| `extraction_test.jsonl` | 60 (24 FDA, 21 CPSC, 15 NHTSA) | Enforcement reports and campaigns published in 2025 | Held-out evaluation; not inspected for errors before reporting |

Each line holds `agency`, `source_id`, the evaluated `text` (title and description as stored; NHTSA's generated "Affected:" line is removed) and `gold` identifiers by kind. Records were sampled with fixed seeds, stratified by agency (and by food, drug and device for FDA), and limited to texts of at most 1,500 characters so every identifier could be labeled reliably. That limit favors shorter recalls and is a known bias.

Status: **v0**. Labeled by the project author against the guidelines below; a second independent pass is planned before publishing agreement figures.

### Labeling guidelines

- **brand**: brand, product-line or company names shown on the product or named as its manufacturer, distributor or recalling firm. Online sellers and importers that are not the brand are excluded. Matching is lenient (see `recall_lens.evals.extraction`).
- **model**: model, item, SKU, catalog, REF, article and part numbers, including vehicle model names, **only when they contain a digit**. Names without digits ("Grand Cherokee", "SRTH") are excluded; vehicle models come from NHTSA's structured data.
- **lot**: lot, batch and serial numbers and other codes identifying affected production units. Ranges ("A2001 through A2310", "335314-335315") are labeled as their endpoints. Dates are excluded unless the text explicitly calls them lot codes. Codes without a digit are excluded.
- **upc**: UPC, GTIN and UDI-DI barcode numbers, digits only.
- **ndc**: National Drug Codes as printed.
- Every gold value must appear in its text (checked when the files were built).

## Retrieval

| File | Queries | Purpose |
|---|---|---|
| `retrieval_dev.jsonl` | 50 | Tuning retrieval parameters and error analysis |
| `retrieval_test.jsonl` | 100 | Held-out evaluation |

Known-item search: each query was written by reading one target recall (2024 onward, sampled with a fixed seed and stratified by agency and query type) and phrasing what a consumer, clinician or owner would plausibly type. Queries were written before any retrieval results were inspected. Every third query goes to the dev split.

| Type | Share | Example |
|---|---|---|
| `describe` | 27% | "wire bristle grill brush bristles came off and ended up in food" (no brand) |
| `brand` | 23% | "Peloton Bike+ seat post breaking" |
| `code` | 20% | "duloxetine lot 222205C", "NDC 16729-442-15" |
| `vehicle` | 23% | "2025 Ford Bronco front upper control arm ball joint nut missing" |
| `equipment` | 7% | "Mopar brake pedal 68607178AA", "Bell Scout Air motorcycle helmet penetration" |

Each record has the `target` recall and the full `relevant` set, built by fixed rules rather than by judging results:

- The target is always relevant.
- **FDA**: every recall in the target's enforcement event (same `event_id`: one firm, one recall action, often several product sizes or store brands).
- **Code and equipment queries**: every recall whose text contains a code that appears both in the target and as a whole token in the query (word-boundary match; UPCs match on digits).

Most queries have exactly one relevant recall (97 of 150). Large FDA events make the relevant set lenient for a few queries (up to 116 recalls), so results are reported both **strict** (the target only) and **lenient** (any relevant recall). Status: **v0**, written by the project author; queries were not paraphrased or reviewed by a second person.

## Photos

| File | Photos | Purpose |
|---|---|---|
| `photos_dev.jsonl` | 50 (37 CPSC, 13 food) | Tuning and error analysis |
| `photos_test.jsonl` | 100 (73 CPSC, 27 food) | Held-out evaluation |

Only URLs and labels are stored; images are downloaded when an evaluation runs and are not redistributed.

- **CPSC** (110): one photo per recall from 2024 onward, sampled with a fixed seed from recall-notice images whose caption mentions a model, lot, batch, UPC, serial, date code, item number or SKU. They are published on cpsc.gov with each recall notice; some are supplied by the recalling firm. Many are product shots or low-resolution crops, which is realistic.
- **Food** (40): for FDA food recalls whose UPC appears in [Open Food Facts](https://world.openfoodfacts.org/), the product's first uploaded photo (usually the front of the pack). Open Food Facts images are contributed under CC BY-SA.

Each record has the photo `url`, the `target` recall, the `relevant` recalls (for food, every recall listing that UPC, compared without leading zeros) and the `gold` identifiers **legible in the photo**:

- **brand**: the product's brand mark; the manufacturer or distributor only when no brand mark is shown. Retail sellers are excluded unless they are the brand.
- **model**: model, item, SKU, style and part numbers containing a digit. Placeholder text such as "XXXXX" is excluded.
- **lot**: lot, batch, serial, production and date codes that identify units, except plain dates.
- **upc**: digits printed under a barcode, or, when a complete barcode is in frame but its digits are cut off, the product's Open Food Facts code (a decoder can still read the bars).
- **vin**: vehicle identification numbers.
- Text too small or blurred for a person to read at the published resolution is not labeled; 38 photos have no legible identifier at all (86 show no code), which tests that the pipeline returns nothing rather than guessing.

Status: **v0**, labeled by the project author by viewing each photo.
