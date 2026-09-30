# ADR-0007: Evaluate and observe without paid LLM calls

- **Status:** Accepted
- **Date:** 2026-09-30
- **Supersedes:** the LLM-as-judge, Langfuse, model routing and Redis cache items of the original Phase 5 plan

## Context

Phase 5 was planned around an LLM judge calibrated against human labels, Langfuse tracing and prompt versioning, routing between Claude models, and a Redis semantic cache. The project's LLM budget is $0 (the Claude steps are built but off, see [ADR-0003](0003-deterministic-verification.md)), Docker is not available to self-host Langfuse or Redis, and the rules-only graph answers a check in about 0.1 s.

## Decision

- **Check faithfulness in code.** Answers are assembled from templates, the cited recall and quotes verified to occur in its notice, so citations and quotes are checked deterministically. The LLM judge, its calibration, prompt versioning and model routing wait until LLM calls are budgeted.
- **Gate on a replay fixture.** Every end-to-end case's facts and retrieved candidates are recorded once; CI replays verification and advice on them in seconds, without a database or models, and fails a change that adds missed recalls or unsafe answers or loses right answers.
- **Trace with OpenTelemetry.** Every graph step is a span. Spans go to a local file by default and to any OTLP backend when configured, including Langfuse Cloud, so no vendor SDK or account is required.
- **No semantic cache.** Rules-only checks are already fast and free per call; a cache would add a second data store ([ADR-0001](0001-postgres-pgvector.md)) for no measured gain. It is reconsidered if Claude arbitration is enabled.

## Consequences

- Quality, latency and cost stay observable and protected at no running cost.
- The gate measures verification and advice only; retrieval changes are measured by the retrieval evaluation and require re-recording the fixture.
- Claude's cost is estimated from the exact prompts it would receive, not measured; the estimate should be replaced by metered usage once a budget exists.
