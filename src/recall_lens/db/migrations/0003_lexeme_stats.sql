-- Document frequency per lexeme, for IDF-weighted full-text ranking. Postgres's ts_rank
-- functions have no inverse document frequency, so words present in nearly every recall
-- ("recall", "lot", "hazard") otherwise outrank distinctive ones such as brand names.
-- Refreshed by the ingestion command after each sync.

CREATE MATERIALIZED VIEW lexeme_stats AS
    SELECT word AS lexeme, ndoc FROM ts_stat('SELECT search_tsv FROM recalls');

CREATE UNIQUE INDEX lexeme_stats_lexeme_idx ON lexeme_stats (lexeme);
