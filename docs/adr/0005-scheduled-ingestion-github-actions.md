# ADR-0005: Schedule ingestion with GitHub Actions instead of Prefect

- **Status:** Accepted
- **Date:** 2026-09-25
- **Supersedes:** the Prefect choice listed in the original roadmap

## Context

Ingestion is one nightly command (`python -m recall_lens.ingest`) that syncs each agency, records every run in the `ingestion_runs` table, isolates per-agency failures and embeds changed recalls. The plan named Prefect for scheduling. Prefect would add a server or cloud account, a worker process and deployment configuration to get a cron trigger, run logs and retries.

## Decision

Run ingestion from a scheduled GitHub Actions workflow (`.github/workflows/ingest.yml`), with a manual trigger that accepts a backfill start date.

- When a `DATABASE_URL` secret is configured, the workflow runs the full pipeline (rules, GLiNER, bge-m3) against that database, with model weights cached between runs.
- Until then, it runs a 30-day, rules-only sync into an ephemeral pgvector container. That still verifies every connector against the live agency APIs each night and publishes a run summary.

## Consequences

- No additional service to operate; schedules, logs, secrets and history live next to the code.
- Run history and counts are already durable in `ingestion_runs`; the workflow summary is a convenience view.
- Jobs are limited to 6 hours and have no DAG view or automatic task-level retries. The command is idempotent, so a failed night is repaired by the next run's overlap window or a manual re-run.
- Revisit a workflow engine (Prefect, Dagster) if ingestion grows into multi-step DAGs, parallel per-agency backfills or cross-job dependencies.
