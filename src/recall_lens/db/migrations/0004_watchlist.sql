-- Watched products: re-checked after each ingestion, with an email when a recall covers one.
-- An item keeps what its check read (text, identifiers, codes), never the photo.

CREATE TABLE watch_items (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    token       text NOT NULL UNIQUE,        -- unguessable; shows and removes the item, no account
    email       text NOT NULL,
    state       jsonb NOT NULL,              -- the check's search text, text, identifiers and codes
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX watch_items_email_idx ON watch_items (email);

-- One row per product and recall the person was told about, so no recall is emailed twice.
CREATE TABLE watch_alerts (
    item_id     bigint NOT NULL REFERENCES watch_items (id) ON DELETE CASCADE,
    recall_id   bigint NOT NULL REFERENCES recalls (id) ON DELETE CASCADE,
    alerted_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (item_id, recall_id)
);
