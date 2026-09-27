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


def test_lexical_matches_any_term_and_ranks_by_coverage(conn, corpus):
    ranked = search.lexical(conn, "Are Vornado tower heaters a fire risk?")
    assert ranked[0] == corpus["26532"]
    assert search.lexical(conn, "helmets") == [corpus["26730"]]


def test_lexical_handles_queries_without_terms(conn, corpus):
    assert search.lexical(conn, "the and of") == []
    assert search.lexical(conn, "it's a \\ o'brien") == []


def test_rrf_rewards_agreement_between_rankings():
    assert search.rrf([[1, 2, 3], [3, 1, 4]]) == [1, 3, 2, 4]
    assert search.rrf([[5]], k=0) == [5]
    assert search.rrf([]) == []


def test_search_fuses_dense_and_lexical(conn, corpus):
    def embed_towards_crib(texts):
        return [one_hot(2) for _ in texts]

    results = search.search(conn, "helmet", embedder=embed_towards_crib)
    top_two = {h.source_id for h in results[:2]}
    assert top_two == {"26730", "26801"}  # lexical finds the helmet, dense the crib mattress
    lexical_only = search.search(conn, "helmet", use_dense=False)
    assert [h.source_id for h in lexical_only] == ["26730"]
