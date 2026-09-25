# Roadmap

RecallLens ships in six phases over roughly twelve weeks (about 15–20 hours per week). Each phase ends with something that runs, a measured result, and a short write-up in the README. Each phase is broken into 8–12 planned commits, written as [Conventional Commits](https://www.conventionalcommits.org/). The commit lists are a plan: expect them to change as work reveals better boundaries.

Progress is tracked with one GitHub milestone and one tracking issue per phase.

| Phase | Weeks | Theme | Status |
|---|---|---|---|
| [0](#phase-0--foundations) | 1 | Foundations | Complete |
| [1](#phase-1--ingestion-and-corpus) | 2–3 | Ingestion and corpus | Planned |
| [2](#phase-2--retrieval) | 3–4 | Retrieval | Planned |
| [3](#phase-3--perception) | 5–6 | Perception | Planned |
| [4](#phase-4--multi-agent-orchestration) | 7–8 | Multi-agent orchestration | Planned |
| [5](#phase-5--evaluation-and-llmops) | 9–10 | Evaluation and LLMOps | Planned |
| [6](#phase-6--product-and-launch) | 11–12 | Product and launch | Planned |

---

## Phase 0 — Foundations

**Goal:** a repository anyone can clone, run and test, with the core architectural decisions written down.

**Exit criteria**
- `docker compose up` starts Postgres with pgvector.
- Migrations apply cleanly and are idempotent.
- CI runs lint and tests against a real pgvector database on every push.

**Planned commits**
- [x] `chore: initialize repository`
- [x] `docs: add project README`
- [x] `docs: add phased delivery roadmap`
- [x] `docs(adr): adopt Postgres with pgvector as the single data store`
- [x] `docs(adr): adopt LangGraph for agent orchestration`
- [x] `docs(adr): verify matches deterministically before consulting an LLM`
- [x] `build: add Python project configuration`
- [x] `build: add local Postgres with pgvector via Docker Compose`
- [x] `feat(db): add initial recall corpus schema`
- [x] `feat(db): add ordered SQL migration runner`
- [x] `ci: run lint and tests against pgvector on every push`
- [x] `docs: add development setup and close out Phase 0`

---

## Phase 1 — Ingestion and corpus

**Goal:** one normalized, continuously updated recall corpus from all four agencies, with typed identifiers extracted.

**Exit criteria**
- Recalls from CPSC, FDA (food, drug, device) and NHTSA are loaded. USDA FSIS is deferred ([ADR-0004](docs/adr/0004-defer-fsis-ingestion.md)).
- Nightly incremental sync is idempotent: re-running it changes nothing.
- Identifier extraction F1 is measured on 100 hand-labeled recalls.

**Planned commits**
- [ ] `feat(ingest): define normalized recall model and content hashing`
- [ ] `feat(ingest): add HTTP client with retries, backoff and per-agency rate limits`
- [ ] `feat(ingest): add CPSC SaferProducts connector`
- [ ] `feat(ingest): add openFDA enforcement connector for food, drugs and devices`
- [ ] `docs(adr): defer USDA FSIS ingestion until API access is available`
- [ ] `feat(ingest): add NHTSA connector using bulk recall files`
- [ ] `feat(db): track ingestion runs and upsert recalls idempotently`
- [ ] `feat(extract): extract UPC, model, lot and VIN identifiers with GLiNER and rules`
- [ ] `feat(ingest): chunk and embed recalls with bge-m3`
- [ ] `feat(ingest): add sync CLI and nightly scheduled ingestion`
- [ ] `test(extract): add labeled extraction set and field-level F1 report`
- [ ] `docs: publish Phase 1 corpus statistics and extraction results`

---

## Phase 2 — Retrieval

**Goal:** find the right recall for a text query, and prove which retrieval design is best.

**Exit criteria**
- 150-case text-query gold set.
- Recall@5 and MRR reported for dense, hybrid, and hybrid + rerank.

**Planned commits**
- [ ] `feat(retrieval): add dense vector search over recall chunks`
- [ ] `feat(retrieval): add Postgres full-text search`
- [ ] `feat(retrieval): fuse dense and full-text results with reciprocal rank fusion`
- [ ] `feat(retrieval): filter by agency, product type and recall date`
- [ ] `feat(retrieval): rerank candidates with bge-reranker-v2-m3`
- [ ] `feat(retrieval): short-circuit on exact identifier matches`
- [ ] `feat(evals): define gold-set format and loader`
- [ ] `feat(evals): add 150-case text-query gold set`
- [ ] `feat(evals): add Recall@k and MRR harness`
- [ ] `feat(evals): add retrieval ablation runner`
- [ ] `perf(db): tune HNSW parameters from measured recall and latency`
- [ ] `docs: publish Phase 2 retrieval results`

---

## Phase 3 — Perception

**Goal:** turn a photo into typed identifiers reliably.

**Exit criteria**
- 100+ labeled product photos.
- Field accuracy reported with and without detection-based cropping.

**Planned commits**
- [ ] `feat(perception): add client for GPU model endpoints`
- [ ] `feat(perception): detect label, barcode and lot-code regions with OWLv2`
- [ ] `feat(perception): crop and upscale detected regions`
- [ ] `feat(perception): read labels into structured fields with a VLM`
- [ ] `feat(perception): decode barcodes and resolve products via Open Food Facts`
- [ ] `feat(perception): decode VINs via NHTSA vPIC`
- [ ] `feat(perception): parse receipts into line items`
- [ ] `feat(evals): add labeled product-photo set`
- [ ] `feat(evals): add field-accuracy metrics for perception`
- [ ] `feat(evals): add crop versus full-frame ablation`
- [ ] `docs: publish Phase 3 perception results`

---

## Phase 4 — Multi-agent orchestration

**Goal:** photo in, cited and verified answer out, with abstention when uncertain.

**Exit criteria**
- End-to-end flow served over an SSE endpoint.
- End-to-end gold set with hard negatives (same product, different lot).
- Multi-agent graph compared against a single-agent baseline.

**Planned commits**
- [ ] `feat(agents): define graph state and LangGraph skeleton`
- [ ] `feat(agents): add perception and identifier nodes`
- [ ] `feat(agents): add retrieval node`
- [ ] `feat(agents): verify lot, date and model ranges deterministically`
- [ ] `feat(agents): arbitrate fuzzy matches with an LLM and emit confidence`
- [ ] `feat(agents): enforce citations and abstain below confidence threshold`
- [ ] `feat(agents): interrupt to request a better photo when unreadable`
- [ ] `feat(agents): checkpoint graph state in Postgres`
- [ ] `feat(api): stream graph progress over server-sent events`
- [ ] `feat(evals): add end-to-end gold set with hard negatives`
- [ ] `feat(evals): compare against a single-agent baseline`
- [ ] `docs: publish Phase 4 end-to-end results`

---

## Phase 5 — Evaluation and LLMOps

**Goal:** make quality, cost and latency observable and protected by CI.

**Exit criteria**
- 300-case evaluation set; LLM judge calibrated with Cohen's κ reported.
- Pull requests fail when the false-negative rate regresses.
- p50/p95 latency and cost per query measured under load.

**Planned commits**
- [ ] `feat(evals): expand end-to-end set to 300 cases`
- [ ] `feat(evals): add LLM-as-judge rubric for faithfulness and remedy accuracy`
- [ ] `feat(evals): calibrate judge against human labels`
- [ ] `ci: gate pull requests on false-negative rate`
- [ ] `ci: run the full evaluation nightly and publish the report`
- [ ] `feat(obs): trace graph nodes with Langfuse`
- [ ] `feat(obs): version prompts in Langfuse`
- [ ] `feat(llm): route requests between Haiku and Sonnet by task`
- [ ] `feat(cache): add Redis semantic cache`
- [ ] `feat(ingest): add circuit breakers around agency APIs`
- [ ] `test(load): add Locust load tests and latency report`
- [ ] `docs: publish Phase 5 quality, cost and latency results`

---

## Phase 6 — Product and launch

**Goal:** a deployed, usable product and a write-up that explains the engineering.

**Exit criteria**
- Public URL, demo video and README results table complete.
- Watchlist alerts delivered by email on new matching recalls.

**Planned commits**
- [ ] `feat(web): add Next.js PWA shell`
- [ ] `feat(web): add camera capture and upload`
- [ ] `feat(web): stream results with citations`
- [ ] `feat(watchlist): add watchlist schema and API`
- [ ] `feat(watchlist): build watchlists from receipt photos`
- [ ] `feat(watchlist): match new recalls nightly and send email alerts`
- [ ] `feat(privacy): purge uploaded images after extraction`
- [ ] `build: containerize the API and deploy to Fly.io`
- [ ] `build: deploy GPU models on Modal`
- [ ] `docs: finalize README results, architecture and demo`
- [ ] `docs: add launch write-up`
