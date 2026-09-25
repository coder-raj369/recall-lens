-- Ingestion bookkeeping, identifier kinds and search limits introduced by the Phase 1 connectors.

ALTER TABLE recall_identifiers DROP CONSTRAINT recall_identifiers_kind_check;
ALTER TABLE recall_identifiers ADD CONSTRAINT recall_identifiers_kind_check
    CHECK (kind IN ('upc', 'ndc', 'model', 'lot', 'vin', 'brand', 'year'));

CREATE TABLE ingestion_runs (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agency       text NOT NULL CHECK (agency IN ('cpsc', 'fda', 'fsis', 'nhtsa')),
    since        date NOT NULL,
    until        date NOT NULL,
    status       text NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'succeeded', 'failed')),
    fetched      integer NOT NULL DEFAULT 0,
    inserted     integer NOT NULL DEFAULT 0,
    updated      integer NOT NULL DEFAULT 0,
    unchanged    integer NOT NULL DEFAULT 0,
    error        text,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz
);

CREATE INDEX ingestion_runs_agency_idx ON ingestion_runs (agency, started_at DESC);

-- Some enforcement reports list thousands of lot codes (one FDA description exceeds 6 MB),
-- which overflows tsvector's 1 MB limit. Index only a bounded prefix; full text stays stored.
ALTER TABLE recalls DROP COLUMN search_tsv;
ALTER TABLE recalls ADD COLUMN search_tsv tsvector GENERATED ALWAYS AS (
    to_tsvector('english', left(
        coalesce(title, '') || ' ' || coalesce(description, '') || ' ' || coalesce(hazard, ''),
        100000))
) STORED;
CREATE INDEX recalls_search_tsv_idx ON recalls USING gin (search_tsv);
