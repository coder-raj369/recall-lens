"""Recall search: dense and full-text retrieval fused with reciprocal rank fusion.

Primitives return recall IDs, best match first; `search` combines them and returns Hits.
"""

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import psycopg

from recall_lens.ingest.embed import vector_literal

# A recall has at most eight chunks, so this many chunk hits always cover `limit` recalls.
_CHUNKS_PER_RECALL = 8
RRF_K = 60  # the constant from Cormack et al. (2009); damps the influence of top ranks
CANDIDATES = 50

Embedder = Callable[[Sequence[str]], Sequence[Sequence[float]]]


@dataclass(frozen=True)
class Hit:
    recall_id: int
    agency: str
    source_id: str
    title: str
    recall_date: date | None
    source_url: str | None


def dense(conn: psycopg.Connection, query_vector: Sequence[float], limit: int = 50) -> list[int]:
    """Nearest recalls by cosine distance of their closest chunk."""
    chunks = limit * _CHUNKS_PER_RECALL
    with conn.transaction():
        # An HNSW scan returns at most ef_search rows (default 40), silently truncating LIMIT.
        conn.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(min(chunks, 1000)),))
        rows = conn.execute(
            """
            SELECT recall_id FROM (
                SELECT recall_id, embedding <=> %(q)s::vector AS distance
                FROM recall_chunks
                ORDER BY distance
                LIMIT %(chunks)s
            ) nearest
            GROUP BY recall_id
            ORDER BY min(distance)
            LIMIT %(limit)s
            """,
            {"q": vector_literal(query_vector), "chunks": chunks, "limit": limit},
        ).fetchall()
    return [row[0] for row in rows]


def lexical(conn: psycopg.Connection, query: str, limit: int = 50) -> list[int]:
    """Full-text search that matches any query term, ranked by cover density.

    websearch_to_tsquery would require every term, which fails for natural-language questions.
    Lexemes come from to_tsvector, so stemming and stop words match the indexed text.
    """
    rows = conn.execute(
        """
        WITH q AS (
            SELECT string_agg(quote_literal(lexeme), ' | ')::tsquery AS query
            FROM unnest(to_tsvector('english', %(text)s))
            WHERE strpos(lexeme, chr(92)) = 0  -- backslashes would break the tsquery
        )
        SELECT r.id FROM recalls r, q
        WHERE r.search_tsv @@ q.query
        ORDER BY ts_rank_cd(r.search_tsv, q.query, 1) DESC, r.id  -- 1: damp long documents
        LIMIT %(limit)s
        """,
        {"text": query, "limit": limit},
    ).fetchall()
    return [row[0] for row in rows]


def hits(conn: psycopg.Connection, recall_ids: Sequence[int]) -> list[Hit]:
    """Load display fields for recall IDs, preserving their order."""
    rows = conn.execute(
        "SELECT id, agency, source_id, title, recall_date, source_url FROM recalls"
        " WHERE id = ANY(%s)",
        (list(recall_ids),),
    ).fetchall()
    by_id = {row[0]: Hit(*row) for row in rows}
    return [by_id[i] for i in recall_ids if i in by_id]


def rrf(rankings: Sequence[Sequence[int]], k: int = RRF_K) -> list[int]:
    """Reciprocal rank fusion: score each ID by the sum of 1 / (k + rank) across rankings."""
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, recall_id in enumerate(ranking, start=1):
            scores[recall_id] += 1 / (k + rank)
    return sorted(scores, key=lambda recall_id: -scores[recall_id])


def search(
    conn: psycopg.Connection,
    query: str,
    *,
    limit: int = 10,
    use_dense: bool = True,
    use_lexical: bool = True,
    embedder: Embedder | None = None,
) -> list[Hit]:
    """Retrieve recalls for a free-text query. The flags exist for ablations."""
    rankings = []
    if use_dense:
        if embedder is None:
            from recall_lens.ingest.embed import default_embedder as embedder
        rankings.append(dense(conn, embedder([query])[0], CANDIDATES))
    if use_lexical:
        rankings.append(lexical(conn, query, CANDIDATES))
    return hits(conn, rrf(rankings)[:limit])
