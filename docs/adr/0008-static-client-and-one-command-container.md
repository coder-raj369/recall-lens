# ADR-0008: Ship a static client and a one-command container, not a hosted service

- **Status:** Accepted
- **Date:** 2026-10-03
- **Supersedes:** the Next.js client, Fly.io deployment and Modal GPU serving of the original Phase 6 plan

## Context

Phase 6 planned a Next.js progressive web app, the API on Fly.io and the vision models on a Modal GPU. The project's budget is $0. The app needs a few gigabytes of memory for its models (bge-m3 for every check, Florence-2 and OWLv2 for photos), Postgres with pgvector, a nightly job and outbound SMTP for alerts. The client itself is one form and one event stream.

The free host first chosen no longer fits: Hugging Face requires a paid plan to create a Docker Space, and its Spaces have no persistent disk and allow outbound traffic only on ports 80, 443 and 8080, which rules out SMTP. A free virtual machine (Oracle's always-free tier, 2 Arm cores and 12 GB) would hold the app, at the price of operating a server.

## Decision

- **The client is a static page served by the API.** HTML, CSS and one JavaScript module, installable as a web app, with no framework, build step or second service.
- **No hosted deployment for now.** The deliverable is a container setup that runs the whole system with one command, `docker compose up --build`: the database, the app, and a first ingestion of recent recalls. A workflow builds the image, starts it and runs a check to an answer whenever what goes into the image changes.
- **Alerts go by plain SMTP, to listed addresses only.** Any mail provider works, and an open form cannot be used to email strangers. Opening the watchlist to anyone needs a confirmation step and a sending domain first.

## Consequences

- Nothing to pay for or keep alive, and no credentials outside a local `.env`.
- There is no public URL. The demo is a recording and screenshots; trying the app means running it.
- A first run downloads about 3 GB of model weights and ingests the last 30 days of recalls. The corpus used in the evaluations takes a backfill of a few hours.
- Photo reading in a CPU container is slower than the Apple-GPU figures in the README and has not been measured there.
- Hosting can be revisited when there is a budget: the image is the unit of deployment and needs a host with enough memory for the models.
