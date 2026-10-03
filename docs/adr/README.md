# Architecture Decision Records

Significant design decisions are recorded here using a lightweight [Michael Nygard](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) format: context, decision, consequences. Records are immutable once accepted; a changed decision gets a new record that supersedes the old one.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-postgres-pgvector.md) | Use Postgres with pgvector as the single data store | Accepted |
| [0002](0002-langgraph-orchestration.md) | Use LangGraph for agent orchestration | Accepted |
| [0003](0003-deterministic-verification.md) | Verify matches deterministically before consulting an LLM | Accepted |
| [0004](0004-defer-fsis-ingestion.md) | Defer USDA FSIS ingestion until API access is available | Accepted |
| [0005](0005-scheduled-ingestion-github-actions.md) | Schedule ingestion with GitHub Actions instead of Prefect | Accepted |
| [0006](0006-local-open-vision-models.md) | Read photos with local open models (Florence-2 and OWLv2) | Accepted |
| [0007](0007-evaluate-and-observe-without-paid-llm-calls.md) | Evaluate and observe without paid LLM calls | Accepted |
| [0008](0008-static-client-and-one-command-container.md) | Ship a static client and a one-command container, not a hosted service | Accepted |
