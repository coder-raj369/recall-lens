# Roadmap

RecallLens ships in six phases over roughly twelve weeks (about 15–20 hours per week). Each phase ends with something that runs, a measured result, and a short write-up in the README. Each phase is broken into 8–12 planned commits, written as [Conventional Commits](https://www.conventionalcommits.org/). The commit lists are a plan: expect them to change as work reveals better boundaries.

Progress is tracked with one GitHub milestone and one tracking issue per phase.

| Phase | Weeks | Theme | Status |
|---|---|---|---|
| [0](#phase-0--foundations) | 1 | Foundations | Complete |
| [1](#phase-1--ingestion-and-corpus) | 2–3 | Ingestion and corpus | Complete |
| [2](#phase-2--retrieval) | 3–4 | Retrieval | Complete |
| [3](#phase-3--perception) | 5–6 | Perception | Complete |
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

**Goal:** one normalized, continuously updated recall corpus across US recall agencies, with typed identifiers extracted.

**Exit criteria**
- Recalls from CPSC, FDA (food, drug, device) and NHTSA are loaded. USDA FSIS is deferred ([ADR-0004](docs/adr/0004-defer-fsis-ingestion.md)).
- Nightly incremental sync is idempotent: re-running it changes nothing.
- Identifier extraction F1 is measured on hand-labeled recalls (100 dev, 60 held-out test).

**Planned commits**
- [x] `feat(ingest): define normalized recall model and content hashing`
- [x] `feat(ingest): add HTTP client with retries, backoff and per-host rate limits`
- [x] `feat(ingest): add CPSC SaferProducts connector`
- [x] `feat(ingest): add openFDA enforcement connector for food, drugs and devices`
- [x] `docs(adr): defer USDA FSIS ingestion until API access is available`
- [x] `feat(ingest): add NHTSA connector using bulk recall files`
- [x] `feat(db): track ingestion runs and upsert recalls idempotently`
- [x] `feat(extract): extract UPC, model, lot and NDC identifiers with rules and GLiNER`
- [x] `feat(ingest): chunk and embed recalls with bge-m3`
- [x] `feat(ingest): add sync CLI and nightly scheduled ingestion`
- [x] `feat(evals): add labeled extraction splits and field-level F1 harness`
- [x] `docs: publish Phase 1 corpus statistics and extraction results`

---

## Phase 2 — Retrieval

**Goal:** find the right recall for a text query, and prove which retrieval design is best.

**Exit criteria**
- 150-query known-item gold set (50 dev, 100 held-out test).
- Recall@k and MRR reported for dense, full-text, hybrid, hybrid + identifiers and hybrid + identifiers + rerank.

**Commits** (revised during the phase: ablation results added the IDF and HNSW fixes, and a flaky network exposed an ingestion bug; the planned HNSW tuning became a measurement once the fix showed no tuning was needed)
- [x] `perf(ingest): re-embed recalls only when their text changes`
- [x] `feat(retrieval): add dense vector search over recall chunks`
- [x] `feat(retrieval): add Postgres full-text search`
- [x] `feat(retrieval): fuse dense and full-text results with reciprocal rank fusion`
- [x] `fix(retrieval): widen the HNSW search so dense retrieval returns full candidate lists`
- [x] `feat(retrieval): filter by agency, product type and recall date`
- [x] `feat(retrieval): short-circuit on exact identifier matches`
- [x] `feat(evals): add known-item retrieval gold set`
- [x] `fix(ingest): retry responses truncated by dropped connections`
- [x] `feat(retrieval): rerank candidates with bge-reranker-v2-m3`
- [x] `feat(retrieval): weight full-text matches by inverse document frequency`
- [x] `feat(evals): add retrieval ablation harness and publish Phase 2 results`

---

## Phase 3 — Perception

**Goal:** turn a photo into typed identifiers reliably, and find its recall.

**Exit criteria**
- 150 labeled public product photos (50 dev, 100 held-out test).
- Field accuracy reported for whole-photo reading and with detected regions.
- Photo-to-recall retrieval measured end to end.

**Commits** (revised during the phase: local Florence-2 and OWLv2 replaced the hosted VLM and GPU endpoint client ([ADR-0006](docs/adr/0006-local-open-vision-models.md)); receipt parsing moved to Phase 6, where the watchlist uses it; dev error analysis added two fixes)
- [x] `feat(evals): add labeled public photo set for perception`
- [x] `feat(perception): load photos as upright, size-bounded RGB images`
- [x] `feat(perception): read label text with Florence-2 OCR`
- [x] `feat(perception): detect label, barcode and rating-plate regions with OWLv2`
- [x] `feat(perception): crop detected regions for OCR without distortion`
- [x] `feat(perception): extract identifiers from OCR text of photos and label regions`
- [x] `feat(perception): decode barcodes and resolve products via Open Food Facts`
- [x] `feat(perception): find VINs in photo text and decode them with NHTSA vPIC`
- [x] `fix(extract): recognize date-code labels and linked code lists`
- [x] `feat(perception): find recalls from a product photo`
- [x] `fix(perception): join barcode digit groups that OCR splits apart`
- [x] `feat(evals): add photo evaluation harness and publish Phase 3 results`

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
- [ ] `feat(watchlist): parse receipt photos into line items (moved from Phase 3)`
- [ ] `feat(watchlist): build watchlists from receipt photos`
- [ ] `feat(watchlist): match new recalls nightly and send email alerts`
- [ ] `feat(privacy): purge uploaded images after extraction`
- [ ] `build: containerize the API and deploy to Fly.io`
- [ ] `build: deploy GPU models on Modal`
- [ ] `docs: finalize README results, architecture and demo`
- [ ] `docs: add launch write-up`
