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
