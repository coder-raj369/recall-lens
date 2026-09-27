"""Recall search primitives. Each returns recall IDs, best match first."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import psycopg

from recall_lens.ingest.embed import vector_literal

# A recall has at most eight chunks, so this many chunk hits always cover `limit` recalls.
_CHUNKS_PER_RECALL = 8


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
        {"q": vector_literal(query_vector), "chunks": limit * _CHUNKS_PER_RECALL, "limit": limit},
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
