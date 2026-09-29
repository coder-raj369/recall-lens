# ADR-0006: Read photos with local open models (Florence-2 and OWLv2)

- **Status:** Accepted
- **Date:** 2026-09-29
- **Supersedes:** the hosted 7B vision-language model in the original Phase 3 plan

## Context

Phase 3 turns product photos into identifiers. The plan named an open vision-language model (Qwen-VL, about 7B parameters) served on a GPU host. The project runs on an 8 GB Apple-silicon laptop without a GPU host or paid accounts, and model downloads on its network are slow and unreliable. A 7B VLM does not fit in memory beside Postgres and the retrieval models.

Options considered:

1. **Local small models**: OWLv2 zero-shot detection to find label regions, Florence-2-large OCR to read them, then the Phase 1 rule and GLiNER extractors.
2. **Claude vision through the Anthropic API**: strongest reading, but needs an API key and per-image cost.
3. **A hosted open VLM** (Modal, Hugging Face Endpoints): closest to the plan, but needs an account and GPU spend.

## Decision

Use local open models: OWLv2 (Apache-2.0) for regions, Florence-2-large (MIT) for OCR, zxing-cpp for barcodes and NHTSA vPIC for VINs, all through native `transformers` code with no remote model code. The OCR text goes through the same extractors as recall text, so photo and document identifiers are canonicalized identically.

## Consequences

- No accounts or per-image cost; the pipeline runs offline once weights are cached.
- Latency is 5.7 s median per photo with region reading on the laptop (2.9 s whole-photo only), and the perception models must be released before retrieval loads bge-m3.
- Reading is limited by OCR at 768 x 768 input: small print (lot codes, serials) is the weakest field. A VLM comparison arm and GPU serving are revisited in Phase 5, where latency budgets and serving exist.
