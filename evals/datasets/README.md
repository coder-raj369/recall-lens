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

## End to end

| File | Cases | Purpose |
|---|---|---|
| `e2e_dev.jsonl` | 48 | Error analysis and, once LLM runs are budgeted, tuning the confidence threshold |
| `e2e_test.jsonl` | 102 | Held-out evaluation |

Each case is what a person would send (a `query`, a `photo` from the photo set, or both) and the `expected` outcome:

- **affected**: a recall in the corpus covers this unit.
- **not_affected**: a recall covers this product but not this unit (a hard negative), or no recall covers this vehicle's model year.
- **needs_info**: whether the unit is covered depends on something the person has not given, such as a lot code, a model year or a brand.
- **no_recall**: nothing in the corpus is about this product.

A construction rule fixes each outcome, and every recall-derived case was checked against the notice it comes from:

| Type | Cases | Construction | Expected |
|---|---|---|---|
| `listed_code` | 24 | Recalls whose notice lists specific lots, batches or serial numbers (7 FDA drugs, 7 foods, 4 devices; 6 CPSC), sampled with a fixed seed from notices of at most 1,500 characters without range, "all lots" or incomplete-list wording, then read to confirm the list is the whole scope. The query names the product and the first code the list prints. | affected |
| `unlisted_code` | 24 | The same product with an adjacent code: the listed code with its last digit (or the one before) changed to the first value that appears nowhere in the corpus. One Julian date code was changed in its day digits instead. | not_affected |
| `no_code` | 16 | The same product with no code; every other recall of that product in the corpus is lot-specific too. One more case names a product whose notice covers a single model. | needs_info |
| `all_units` | 14 | Recalls that cover every unit of the named product (10 CPSC notices with no unit restriction, 4 FDA "All lots"), read to confirm; wording such as "distributed by" or "produced ... and prior" excluded. When a notice names models, the query names one. | affected |
| `vehicle_in` | 15 | A make, model and model year from an NHTSA affected-vehicle list (consumer makes; no buses or heavy trucks). | affected |
| `vehicle_out` | 12 | A model year between two covered years that no recall in the corpus covers, for models with four or more recalls, and that no variant or broader model name ("Silverado 1500 LD", "Silverado") covers either. | not_affected |
| `vehicle_no_year` | 6 | A make and model with no year, where recalls cover only some years. | needs_info |
| `no_recall` | 15 | Well-known products whose brand appears nowhere in the corpus; any code in the query is absent too. | no_recall |
| `describe` | 9 | A product category with no brand ("space heater") that at least two recall titles match. | needs_info |
| `photo` | 15 | Recall-notice photos from the photo set, labeled by comparing what is legible with the notice's scope: a listed code or an every-unit model is affected; a brand alone against a lot-, date- or VIN-scoped recall, or a photo with nothing legible, needs information. | 8 affected, 7 needs_info |

Each case records its `target` recall and the `relevant` recalls that are correct to cite, so citations can be scored strictly or leniently as in retrieval: for codes, the recalls in the same FDA event that print the code; for vehicles, every recall covering that make, model and year (any year for `vehicle_out` and `vehicle_no_year`); for descriptions, every recall whose title matches the category. Cases built from the same recall or model share a split, with every third group going to dev; photos keep their split from the photo set.

**Corrections (v0.1).** After the first held-out run, all 54 unlisted-code, no-code and all-units cases were re-audited with checks independent of the verifier: code ranges in every other recall, brand-level sibling recalls, and model restrictions in the notice. One label was wrong: `e2e-test-045` asks about a NICREW light without its model number while the notice covers only model N21743, so the outcome is `needs_info`, not `affected`. The graph had answered `needs_info`, so the correction raises its score; the Phase 4 results say so. The corpus was also rebuilt on 2026-09-30 after the local database was lost, and every construction rule was re-checked against it. One new NHTSA recall now also covers 2016–2017 Silverado and Sierra 1500s; no outcome changed.

Known limitations: outcomes are relative to the corpus (recalls published from 2024 onward), so an older recall could cover a `vehicle_out` vehicle; product phrases and query templates were written by the project author and are less varied than real queries; hard negatives are adjacent codes, not codes seen in the wild. Status: **v0.1**, one annotator.
