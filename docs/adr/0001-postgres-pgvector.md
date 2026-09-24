# ADR-0001: Use Postgres with pgvector as the single data store

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

RecallLens needs to store normalized recalls, typed identifiers (UPC, model, lot, VIN), text chunks with dense embeddings, watchlists and evaluation runs. Retrieval must combine vector similarity, full-text search, exact identifier lookup and structured filters (agency, product type, recall date) in a single query path.

The corpus is modest: tens of thousands of recalls and low hundreds of thousands of chunks, well within the range where a single Postgres instance with an HNSW index performs well.

Options considered:

1. **Postgres + pgvector** for everything.
2. **Postgres + a managed vector database** (Pinecone, Weaviate) for embeddings.
3. **A search engine** (OpenSearch, Elasticsearch) for text and vectors, Postgres for the rest.

## Decision

Use PostgreSQL 16 with the pgvector extension as the only data store. Dense search uses an HNSW index; lexical search uses a generated `tsvector` column with a GIN index; identifier lookup uses ordinary B-tree indexes.

## Consequences

- Hybrid retrieval and metadata filtering happen in one SQL query with joins, with no cross-system consistency problems.
- One service to run locally, in CI and in production; one backup story.
- Ingestion can update a recall, its identifiers and its chunks in a single transaction.
- Postgres full-text search is weaker than BM25 in a dedicated engine. This is acceptable because the cross-encoder reranker dominates final ranking quality; the Phase 2 ablation will confirm it.
- If the corpus or query volume grows by orders of magnitude, vector search can move to a dedicated store behind the retrieval module without changing callers. That would be recorded in a superseding ADR.
