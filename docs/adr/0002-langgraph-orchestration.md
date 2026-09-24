# ADR-0002: Use LangGraph for agent orchestration

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

A recall check is a multi-step workflow with branching: perception may fail and require a new photo, an exact identifier match can skip semantic retrieval, and verification may abstain. Requirements:

- Explicit, inspectable control flow that can be unit-tested node by node.
- Durable state so a session can pause for user input (for example, "retake the photo closer to the lot code") and resume.
- Streaming of intermediate progress to the client.
- Per-node tracing for evaluation and debugging.

Options considered:

1. **LangGraph**: a typed state graph with checkpointing, interrupts and streaming.
2. **Role-based agent frameworks** (CrewAI, AutoGen): conversational agents that coordinate through messages.
3. **Hand-written orchestration** in plain Python.

## Decision

Use LangGraph. Each agent (perception, identifier, retrieval, verifier, advisor) is a graph node over a shared, typed state. A supervisor routes between nodes using conditional edges. State is checkpointed in Postgres (see [ADR-0001](0001-postgres-pgvector.md)).

## Consequences

- Control flow is a graph that can be drawn, reviewed and tested, not an emergent property of agents talking to each other.
- Human-in-the-loop pauses use built-in interrupts instead of custom session handling.
- Nodes are plain functions, so deterministic steps (range checks, identifier lookup) sit alongside LLM steps without special handling.
- The project takes a dependency on the LangChain ecosystem's release cadence. Nodes are kept free of framework types where practical, so they remain callable outside the graph.
- A single-agent baseline will be built in Phase 4 to show whether the multi-agent structure actually improves results.
