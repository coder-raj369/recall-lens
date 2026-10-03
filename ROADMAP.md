# Roadmap

RecallLens ships in six phases over roughly twelve weeks (about 15–20 hours per week). Each phase ends with something that runs, a measured result, and a short write-up in the README. Each phase is broken into 8–12 planned commits, written as [Conventional Commits](https://www.conventionalcommits.org/). The commit lists are a plan: expect them to change as work reveals better boundaries.

Progress is tracked with one GitHub milestone and one tracking issue per phase.

| Phase | Weeks | Theme | Status |
|---|---|---|---|
| [0](#phase-0--foundations) | 1 | Foundations | Complete |
| [1](#phase-1--ingestion-and-corpus) | 2–3 | Ingestion and corpus | Complete |
| [2](#phase-2--retrieval) | 3–4 | Retrieval | Complete |
| [3](#phase-3--perception) | 5–6 | Perception | Complete |
| [4](#phase-4--multi-agent-orchestration) | 7–8 | Multi-agent orchestration | Complete |
| [5](#phase-5--evaluation-and-llmops) | 9–10 | Evaluation and LLMOps | Complete |
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
- [x] `fix(perception): let detection unit tests run without Pillow`

---

## Phase 4 — Multi-agent orchestration

**Goal:** photo in, cited and verified answer out, with abstention when uncertain.

**Exit criteria**
- End-to-end flow served over an SSE endpoint.
- End-to-end gold set with hard negatives (same product, different lot).
- Multi-agent graph compared against baselines. The non-LLM baselines are measured. The Claude single-agent baseline and Claude arbitration are built and tested against a mocked API, but not run while the LLM budget is $0.

**Commits** (revised during the phase: the LLM steps target Claude Opus 5.5 and are off by default at a $0 budget; building the gold set exposed two ways a unit could be ruled out against an incomplete code list, fixed before measuring; as in Phase 3, the comparison and the published results are one commit)
- [x] `feat(agents): define graph state and LangGraph skeleton`
- [x] `feat(agents): add perception and identifier nodes`
- [x] `feat(agents): add retrieval node`
- [x] `feat(agents): verify lot, date and model ranges deterministically`
- [x] `feat(agents): arbitrate undetermined candidates with Claude, off by default`
- [x] `feat(agents): cite recalls in the answer and abstain below a confidence threshold`
- [x] `feat(agents): interrupt to request a better photo when unreadable`
- [x] `feat(agents): checkpoint graph state in Postgres`
- [x] `feat(api): stream graph progress over server-sent events`
- [x] `fix(agents): never rule a unit out against an incomplete code list`
- [x] `feat(evals): add end-to-end gold set with hard negatives`
- [x] `feat(evals): compare the graph with baselines and publish Phase 4 results`

---

## Phase 5 — Evaluation and LLMOps

**Goal:** make quality, cost and latency observable and protected by CI.

**Exit criteria**
- 300-case evaluation set, with a fresh holdout for measuring fixes. (The LLM judge and its calibration wait for an LLM budget; citations are checked in code, [ADR-0007](docs/adr/0007-evaluate-and-observe-without-paid-llm-calls.md).)
- Changes fail CI when they add missed recalls or unsafe answers.
- p50/p95 latency measured under load; cost per query measured for rules and estimated for Claude.

**Commits** (revised during the phase: at a $0 LLM budget the judge, prompt versioning and model routing gave way to fixing and re-measuring the Phase 4 bugs; OpenTelemetry replaced a Langfuse SDK and stays Langfuse-compatible; the Redis cache was dropped; load and cost measurement found two more fixes)
- [x] `chore: support a local pgserver database without Docker`
- [x] `feat(evals): add a fresh 150-case held-out split`
- [x] `fix(agents): never answer "no recall" from a photo that could not be read`
- [x] `fix(agents): tie recalls through punctuation, OCR slips and multi-word makes`
- [x] `fix(agents): keep a brand's other products from answering for yours`
- [x] `fix(agents): ask about the closest recall instead of guessing "no match"`
- [x] `fix(agents): judge the product from how the notice describes it`
- [x] `feat(obs): trace every graph step with OpenTelemetry`
- [x] `feat(http): skip failing hosts with a circuit breaker and keep lookups short`
- [x] `ci: gate every change on missed recalls and unsafe answers`
- [x] `test(load): measure latency under load and cost per check`
- [x] `docs: publish Phase 5 quality, cost and latency results`

---

## Phase 6 — Product and launch

**Goal:** a deployed, usable product and a write-up that explains the engineering.

**Exit criteria**
- The whole system runs with one command, with a demo recording and the README results complete (revised from a public URL: [ADR-0008](docs/adr/0008-static-client-and-one-command-container.md)).
- Watchlist alerts delivered by email on new matching recalls.

Still open: the container's first build in CI (it was written on a machine without Docker), the demo recording, and a run of the alerts against a real mail server (they are tested with a stand-in and were dry-run on the real corpus).

**Commits** (revised during the phase: a static page served by the API replaced the Next.js client, since it needs no build and no second service; receipt parsing and GPU serving were dropped, the first from scope and the second because the budget is $0; uploaded photos have been deleted after each request since Phase 4; the two rule problems Phase 5's holdout named were fixed first, which led to the exact vehicle lookup; the free Hugging Face Docker Space the deployment was planned for now needs a paid plan, so the app ships as a container that runs anywhere instead of as a hosted service ([ADR-0008](docs/adr/0008-static-client-and-one-command-container.md)))
- [x] `feat(web): add an installable web client served by the API`
- [x] `feat(web): check a product from a photo and retake unreadable ones`
- [x] `fix(extract): stop reading sizes and product names as model numbers`
- [x] `feat(agents): look up recalls of the named vehicle and model year exactly`
- [x] `fix(verify): ask which vehicle model only when it could be theirs`
- [x] `fix(retrieval): search an empty corpus without failing`
- [x] `test(evals): re-record the replay fixture and raise the gate baseline`
- [x] `feat(watchlist): email when a recall newly covers a watched product`
- [x] `feat(web): watch a product from its answer and stop from the email link`
- [x] `docs: publish Phase 6 vehicle results and document the web client and watchlist`
- [x] `build: run the app, its database and a first ingestion with docker compose`
- [x] `docs: record the delivery decision, add the write-up and finish the README`
