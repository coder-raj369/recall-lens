from datetime import date

import pytest

from recall_lens.ingest import store
from recall_lens.ingest.embed import vector_literal
from recall_lens.ingest.models import Recall
from recall_lens.retrieval import search


def one_hot(i, dim=1024):
    return [1.0 if j == i else 0.0 for j in range(dim)]


@pytest.fixture
def corpus(conn):
    """Three recalls whose chunk embeddings point along distinct axes."""
    rows = [
        ("26532", "Vornado Recalls Small Room Tower Heaters", "Fire hazard", [0, 3]),
        ("26730", "Acme Recalls Bike Helmets", "Head injury hazard", [1]),
        ("26801", "Zen Recalls Crib Mattresses", "Suffocation hazard", [2]),
    ]
    ids = {}
    for source_id, title, hazard, axes in rows:
        recall = Recall(
            agency="cpsc", source_id=source_id, title=title, hazard=hazard,
            recall_date=date(2026, 1, 1), raw={},
        )  # fmt: skip
        store.upsert(conn, recall)
        recall_id = conn.execute(
            "SELECT id FROM recalls WHERE source_id = %s", (source_id,)
        ).fetchone()[0]
        for ord_, axis in enumerate(axes):
            conn.execute(
                "INSERT INTO recall_chunks (recall_id, ord, content, embedding)"
                " VALUES (%s, %s, %s, %s::vector)",
                (recall_id, ord_, title, vector_literal(one_hot(axis))),
            )
        ids[source_id] = recall_id
    conn.commit()
    return ids


def test_dense_ranks_by_closest_chunk_and_collapses_chunks(conn, corpus):
    query = [0.0] * 1024
    query[3], query[1] = 1.0, 0.5  # closest to the heater's second chunk, then the helmet
    ranked = search.dense(conn, query, limit=3)
    assert ranked[:2] == [corpus["26532"], corpus["26730"]]
    assert len(ranked) == len(set(ranked)) == 3


def test_hits_preserve_rank_order(conn, corpus):
    order = [corpus["26801"], corpus["26532"]]
    assert [h.source_id for h in search.hits(conn, order)] == ["26801", "26532"]
