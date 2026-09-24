-- Initial recall corpus: normalized recalls, typed identifiers and embedded chunks.
-- Design rationale: docs/adr/0001-postgres-pgvector.md

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE recalls (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agency        text NOT NULL CHECK (agency IN ('cpsc', 'fda', 'fsis', 'nhtsa')),
    source_id     text NOT NULL,             -- the agency's own recall number
    title         text NOT NULL,
    description   text,
    hazard        text,
    remedy        text,
    product_type  text,                      -- e.g. food, drug, device, vehicle, consumer_product
    recall_date   date,
    source_url    text,
    raw           jsonb NOT NULL,            -- original payload, kept for reprocessing
    content_hash  text NOT NULL,             -- detects upstream changes for idempotent upserts
    search_tsv    tsvector GENERATED ALWAYS AS (
                      to_tsvector('english',
                          coalesce(title, '') || ' ' ||
                          coalesce(description, '') || ' ' ||
                          coalesce(hazard, ''))
                  ) STORED,
    ingested_at   timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (agency, source_id)
);

CREATE INDEX recalls_search_tsv_idx ON recalls USING gin (search_tsv);
CREATE INDEX recalls_recall_date_idx ON recalls (recall_date DESC);

-- Identifiers that decide whether a specific unit is affected.
-- Values are stored as printed; range semantics are applied by the verifier (ADR-0003).
CREATE TABLE recall_identifiers (
    recall_id  bigint NOT NULL REFERENCES recalls (id) ON DELETE CASCADE,
    kind       text NOT NULL CHECK (kind IN ('upc', 'model', 'lot', 'vin', 'brand')),
    value      text NOT NULL,
    PRIMARY KEY (recall_id, kind, value)
);

CREATE INDEX recall_identifiers_lookup_idx ON recall_identifiers (kind, value);

CREATE TABLE recall_chunks (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recall_id  bigint NOT NULL REFERENCES recalls (id) ON DELETE CASCADE,
    ord        integer NOT NULL,
    content    text NOT NULL,
    embedding  vector(1024),                 -- bge-m3 dense dimension
    UNIQUE (recall_id, ord)
);

CREATE INDEX recall_chunks_embedding_idx ON recall_chunks USING hnsw (embedding vector_cosine_ops);
