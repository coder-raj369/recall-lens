"""Recall search: exact identifier matches first, then dense and full-text retrieval fused
with reciprocal rank fusion.

Primitives return recall IDs, best match first; `search` combines them and returns Hits.
"""

import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import psycopg

from recall_lens.extract import rules
from recall_lens.ingest.embed import vector_literal

# A recall has at most eight chunks, so this many chunk hits always cover `limit` recalls.
_CHUNKS_PER_RECALL = 8
RRF_K = 60  # the constant from Cormack et al. (2009); damps the influence of top ranks
CANDIDATES = 50

CODE_KINDS = ["upc", "ndc", "model", "lot"]  # brands and years are too broad to short-circuit
MIN_BARE_CODE = 5  # unlabeled tokens shorter than this ("F1", "4x4") are too ambiguous
_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9+\-./_]*[A-Z0-9]", re.IGNORECASE)
_YEAR = re.compile(r"^(?:19|20)\d{2}$")

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
    """Full-text search that matches any query term, ranked by cover density.

    websearch_to_tsquery would require every term, which fails for natural-language questions.
    Lexemes come from to_tsvector, so stemming and stop words match the indexed text.
    """
    where, params = filters.sql()
    rows = conn.execute(
        f"""
        WITH q AS (
            SELECT string_agg(quote_literal(lexeme), ' | ')::tsquery AS query
            FROM unnest(to_tsvector('english', %(text)s))
            WHERE strpos(lexeme, chr(92)) = 0  -- backslashes would break the tsquery
        )
        SELECT r.id FROM recalls r, q
        WHERE r.search_tsv @@ q.query{where}
        ORDER BY ts_rank_cd(r.search_tsv, q.query, 1) DESC, r.id  -- 1: damp long documents
        LIMIT %(limit)s
        """,
        {"text": query, "limit": limit, **params},
    ).fetchall()
    return [row[0] for row in rows]


def query_codes(query: str) -> set[str]:
    """Identifier values a query may contain: labeled codes plus bare code-like tokens."""
    values = {value for _, value in rules.extract(query)}
    labeled = " ".join(values)
    for token in _TOKEN.findall(query):
        if len(token) < MIN_BARE_CODE or not any(c.isdigit() for c in token) or _YEAR.match(token):
            continue
        if token.isdigit() and token in labeled:  # a digit group of a spaced, labeled UPC
            continue
        values.add(token.upper())
    return values


def identifier_matches(
    conn: psycopg.Connection, query: str, filters: Filters = NO_FILTERS, limit: int = 50
) -> dict[int, int]:
    """Recalls whose stored identifiers exactly match codes in the query, with match counts."""
    codes = query_codes(query)
    if not codes:
        return {}
    where, params = filters.sql()
    rows = conn.execute(
        f"""
        SELECT r.id, count(DISTINCT i.value)
        FROM recall_identifiers i JOIN recalls r ON r.id = i.recall_id
        WHERE i.kind = ANY(%(kinds)s) AND i.value = ANY(%(codes)s){where}
        GROUP BY r.id
        ORDER BY 2 DESC, r.id
        LIMIT %(limit)s
        """,
        {"kinds": CODE_KINDS, "codes": sorted(codes), "limit": limit, **params},
    ).fetchall()
    return dict(rows)


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
    embedder: Embedder | None = None,
) -> list[Hit]:
    """Retrieve recalls for a free-text query. The use_* flags exist for ablations.

    Exact identifier matches come first, ordered by how many codes they match and then by
    their fused rank; the fused ranking follows.
    """
    rankings = []
    if use_dense:
        if embedder is None:
            from recall_lens.ingest.embed import default_embedder as embedder
        rankings.append(dense(conn, embedder([query])[0], CANDIDATES, filters))
    if use_lexical:
        rankings.append(lexical(conn, query, CANDIDATES, filters))
    fused = rrf(rankings)
    exact = identifier_matches(conn, query, filters) if use_identifiers else {}
    position = {recall_id: i for i, recall_id in enumerate(fused)}
    first = sorted(exact, key=lambda r: (-exact[r], position.get(r, len(fused))))
    ranked = first + [r for r in fused if r not in exact]
    return hits(conn, ranked[:limit])
