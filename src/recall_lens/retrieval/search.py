"""Recall search: exact identifier matches first, then dense and full-text retrieval fused
with reciprocal rank fusion and reranked by a cross-encoder.

Primitives return recall IDs, best match first; `search` combines them and returns Hits.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date

import psycopg

from recall_lens.extract import rules
from recall_lens.ingest.embed import vector_literal
from recall_lens.retrieval.rerank import Reranker

# A recall has at most eight chunks, so this many chunk hits always cover `limit` recalls.
_CHUNKS_PER_RECALL = 8
RRF_K = 60  # the constant from Cormack et al. (2009); damps the influence of top ranks
CANDIDATES = 50
RERANK_CANDIDATES = 30
RERANK_TEXT_CHARS = 2_000  # the cross-encoder reads ~512 tokens

CODE_KINDS = ["upc", "ndc", "model", "lot"]  # brands and years are too broad to short-circuit

Embedder = Callable[[Sequence[str]], Sequence[Sequence[float]]]


@dataclass(frozen=True)
class Filters:
    agencies: tuple[str, ...] = ()
    product_types: tuple[str, ...] = ()
    since: date | None = None
    until: date | None = None

    def __bool__(self) -> bool:
        return bool(self.agencies or self.product_types or self.since or self.until)

    def sql(self) -> tuple[str, dict]:
        """AND-clauses over the recalls table aliased as r, with their parameters."""
        clauses = {
            "r.agency = ANY(%(f_agencies)s)": list(self.agencies) or None,
            "r.product_type = ANY(%(f_product_types)s)": list(self.product_types) or None,
            "r.recall_date >= %(f_since)s": self.since,
            "r.recall_date <= %(f_until)s": self.until,
        }
        active = {clause: value for clause, value in clauses.items() if value is not None}
        params = {clause.split("%(")[1].split(")")[0]: value for clause, value in active.items()}
        return "".join(f" AND {clause}" for clause in active), params


NO_FILTERS = Filters()


@dataclass(frozen=True)
class Hit:
    recall_id: int
    agency: str
    source_id: str
    title: str
    recall_date: date | None
    source_url: str | None


def dense(
    conn: psycopg.Connection,
    query_vector: Sequence[float],
    limit: int = 50,
    filters: Filters = NO_FILTERS,
) -> list[int]:
    """Nearest recalls by cosine distance of their closest chunk."""
    chunks = limit * _CHUNKS_PER_RECALL
    where, params = filters.sql()
    # ponytail: filtered queries scan exactly (the "+ 0" keeps the planner off the HNSW index),
    # because pgvector < 0.8 filters after the index scan and selective filters starve results.
    # Exact search over ~26k chunks takes milliseconds; use iterative index scans if it grows.
    order = "(c.embedding <=> %(q)s::vector) + 0" if filters else "distance"
    with conn.transaction():
        # An HNSW scan returns at most ef_search rows (default 40), silently truncating LIMIT.
        conn.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(min(chunks, 1000)),))
        rows = conn.execute(
            f"""
            SELECT recall_id FROM (
                SELECT c.recall_id, c.embedding <=> %(q)s::vector AS distance
                FROM recall_chunks c
                {"JOIN recalls r ON r.id = c.recall_id WHERE TRUE" + where if filters else ""}
                ORDER BY {order}
                LIMIT %(chunks)s
            ) nearest
            GROUP BY recall_id
            ORDER BY min(distance)
            LIMIT %(limit)s
            """,
            {"q": vector_literal(query_vector), "chunks": chunks, "limit": limit, **params},
        ).fetchall()
    return [row[0] for row in rows]


def lexical(
    conn: psycopg.Connection, query: str, limit: int = 50, filters: Filters = NO_FILTERS
) -> list[int]:
    """Full-text search ranked by the summed inverse document frequency of matched terms.

    Each distinct query lexeme contributes ln(N / (1 + df)), so distinctive terms such as brand
    names outweigh words found in nearly every recall ("recall", "lot", "hazard"). Postgres's
    ts_rank functions have no IDF; document frequencies come from the lexeme_stats view, which
    ingestion refreshes. Terms newer than the last refresh count as rare. Lexemes come from
    to_tsvector, so stemming and stop words agree with the indexed text.
    """
    where, params = filters.sql()
    rows = conn.execute(
        f"""
        WITH terms AS (
            SELECT DISTINCT u.lexeme, greatest(
                ln(greatest((SELECT count(*) FROM recalls), 1)::float  -- no recalls yet: 1
                   / (1 + coalesce(s.ndoc, 0))), 0
            ) AS idf
            FROM unnest(to_tsvector('english', %(text)s)) u
            LEFT JOIN lexeme_stats s ON s.lexeme = u.lexeme
            WHERE strpos(u.lexeme, chr(92)) = 0  -- backslashes would break the tsquery
        )
        SELECT r.id
        FROM terms t JOIN recalls r ON r.search_tsv @@ quote_literal(t.lexeme)::tsquery
        WHERE TRUE{where}
        GROUP BY r.id
        ORDER BY sum(t.idf) DESC, r.id
        LIMIT %(limit)s
        """,
        {"text": query, "limit": limit, **params},
    ).fetchall()
    return [row[0] for row in rows]


def identifier_matches(
    conn: psycopg.Connection,
    query: str,
    filters: Filters = NO_FILTERS,
    limit: int = 50,
    extra_codes: Iterable[str] = (),
) -> dict[int, int]:
    """Recalls whose stored identifiers exactly match codes in the query, with match counts.

    extra_codes adds codes found outside the query text, such as decoded barcodes. UPCs match
    regardless of leading zeros: scanners report EAN-13 ("0799403302902") where recall text
    prints UPC-A ("799403302902").
    """
    codes = rules.codes(query) | set(extra_codes)
    if not codes:
        return {}
    digits = sorted({c.lstrip("0") for c in codes if c.isdigit() and len(c) >= 8})
    where, params = filters.sql()
    rows = conn.execute(
        f"""
        SELECT r.id, count(DISTINCT i.value)
        FROM recall_identifiers i JOIN recalls r ON r.id = i.recall_id
        WHERE ((i.kind = ANY(%(kinds)s) AND i.value = ANY(%(codes)s))
               OR (i.kind = 'upc' AND ltrim(i.value, '0') = ANY(%(digits)s))){where}
        GROUP BY r.id
        ORDER BY 2 DESC, r.id
        LIMIT %(limit)s
        """,
        {"kinds": CODE_KINDS, "codes": sorted(codes), "digits": digits, "limit": limit, **params},
    ).fetchall()
    return dict(rows)


def rerank(
    conn: psycopg.Connection, query: str, recall_ids: Sequence[int], reranker: Reranker
) -> list[int]:
    """Reorder recalls by cross-encoder relevance of their title, hazard and description."""
    rows = conn.execute(
        "SELECT id, concat_ws(E'\\n', title, hazard, left(description, %s)) FROM recalls"
        " WHERE id = ANY(%s)",
        (RERANK_TEXT_CHARS, list(recall_ids)),
    ).fetchall()
    texts = dict(rows)
    ordered = [recall_id for recall_id in recall_ids if recall_id in texts]
    scores = reranker(query, [texts[recall_id] for recall_id in ordered])
    by_score = sorted(zip(scores, range(len(ordered)), ordered, strict=True), reverse=True)
    return [recall_id for _, _, recall_id in by_score]


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
    filters: Filters = NO_FILTERS,
    use_dense: bool = True,
    use_lexical: bool = True,
    use_identifiers: bool = True,
    use_rerank: bool = False,  # opt-in: ~5 s per query on CPU; see README, Phase 2 results
    extra_codes: Iterable[str] = (),
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
) -> list[Hit]:
    """Retrieve recalls for a free-text query. The use_* flags exist for ablations.

    Exact identifier matches come first, ordered by how many codes they match and then by
    their fused rank; the fused ranking follows, its head optionally reordered by the
    cross-encoder.
    """
    rankings = []
    if use_dense:
        if embedder is None:
            from recall_lens.ingest.embed import default_embedder as embedder
        rankings.append(dense(conn, embedder([query])[0], CANDIDATES, filters))
    if use_lexical:
        rankings.append(lexical(conn, query, CANDIDATES, filters))
    fused = rrf(rankings)
    exact = (
        identifier_matches(conn, query, filters, extra_codes=extra_codes) if use_identifiers else {}
    )
    position = {recall_id: i for i, recall_id in enumerate(fused)}
    first = sorted(exact, key=lambda r: (-exact[r], position.get(r, len(fused))))
    rest = [r for r in fused if r not in exact]
    if use_rerank and rest:
        if reranker is None:
            from recall_lens.retrieval.rerank import default_reranker as reranker
        head = rerank(conn, query, rest[:RERANK_CANDIDATES], reranker)
        rest = head + rest[RERANK_CANDIDATES:]
    return hits(conn, (first + rest)[:limit])
