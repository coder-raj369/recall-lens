import random
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
        ("26532", "Vornado Recalls Small Room Tower Heaters", "Fire hazard", [0, 3], {}),
        ("26730", "Acme Recalls Bike Helmets", "Head injury hazard", [1],
         {("model", "H-100"), ("lot", "2023"), ("upc", "012345678905")}),
        ("26801", "Zen Recalls Crib Mattresses", "Suffocation hazard", [2], {("model", "ZM-300")}),
    ]  # fmt: skip
    ids = {}
    for source_id, title, hazard, axes, identifiers in rows:
        recall = Recall(
            agency="cpsc", source_id=source_id, title=title, hazard=hazard,
            recall_date=date(2026, 1, 1), raw={}, identifiers=frozenset(identifiers),
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


def test_dense_returns_full_candidate_list_through_hnsw_index(conn):
    rng = random.Random(0)
    for i in range(120):
        store.upsert(conn, Recall(agency="fda", source_id=f"F-{i}", title=f"Recall {i}",
                                  recall_date=date(2026, 1, 1), raw={}))  # fmt: skip
        conn.execute(
            "INSERT INTO recall_chunks (recall_id, ord, content, embedding)"
            " SELECT id, 0, title, %s::vector FROM recalls WHERE source_id = %s",
            (vector_literal([rng.gauss(0, 1) for _ in range(1024)]), f"F-{i}"),
        )
    conn.execute("SET enable_seqscan = off")  # force the HNSW index, as on a large corpus
    plan = conn.execute(
        "EXPLAIN SELECT 1 FROM recall_chunks ORDER BY embedding <=> %s::vector LIMIT 400",
        (vector_literal(one_hot(0)),),
    ).fetchall()
    assert any("recall_chunks_embedding_idx" in line for (line,) in plan)
    assert len(search.dense(conn, one_hot(0), limit=50)) == 50


def test_hits_preserve_rank_order(conn, corpus):
    order = [corpus["26801"], corpus["26532"]]
    assert [h.source_id for h in search.hits(conn, order)] == ["26801", "26532"]


def test_lexical_matches_any_term(conn, corpus):
    ranked = search.lexical(conn, "Are Vornado tower heaters a fire risk?")
    assert ranked[0] == corpus["26532"]
    assert search.lexical(conn, "helmets") == [corpus["26730"]]


def test_lexical_weights_rare_terms_above_common_ones(conn, corpus):
    conn.execute("REFRESH MATERIALIZED VIEW lexeme_stats")
    # "hazard" is in all three recalls; "helmets" in one, so it decides the ranking.
    assert search.lexical(conn, "hazard hazard helmets")[0] == corpus["26730"]
    idf = dict(conn.execute("SELECT lexeme, ndoc FROM lexeme_stats").fetchall())
    assert idf["hazard"] == 3 and idf["helmet"] == 1


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

    results = search.search(conn, "helmet", embedder=embed_towards_crib, use_rerank=False)
    top_two = {h.source_id for h in results[:2]}
    assert top_two == {"26730", "26801"}  # lexical finds the helmet, dense the crib mattress
    lexical_only = search.search(conn, "helmet", use_dense=False, use_rerank=False)
    assert [h.source_id for h in lexical_only] == ["26730"]


def test_filters_build_only_active_clauses():
    where, params = search.Filters(agencies=("fda",), since=date(2026, 1, 1)).sql()
    assert where == " AND r.agency = ANY(%(f_agencies)s) AND r.recall_date >= %(f_since)s"
    assert params == {"f_agencies": ["fda"], "f_since": date(2026, 1, 1)}
    assert not search.Filters() and search.Filters(product_types=("food",))


def test_filters_apply_to_dense_and_lexical(conn, corpus):
    heater = Recall(
        agency="fda", source_id="H-1", title="Heater recall", hazard="Fire hazard",
        recall_date=date(2025, 5, 1), raw={},
    )  # fmt: skip
    store.upsert(conn, heater)
    conn.execute(
        "INSERT INTO recall_chunks (recall_id, ord, content, embedding)"
        " SELECT id, 0, title, %s::vector FROM recalls WHERE source_id = 'H-1'",
        (vector_literal(one_hot(9)),),
    )
    fda_only = search.Filters(agencies=("fda",))
    heater_fda = conn.execute("SELECT id FROM recalls WHERE source_id = 'H-1'").fetchone()[0]
    assert search.dense(conn, one_hot(3), filters=fda_only) == [heater_fda]
    assert search.lexical(conn, "heater fire", filters=fda_only) == [heater_fda]
    in_2026 = search.Filters(since=date(2026, 1, 1))
    assert heater_fda not in search.lexical(conn, "heater fire", filters=in_2026)
    assert corpus["26532"] in search.lexical(conn, "heater fire", filters=in_2026)


def test_query_codes_take_labeled_and_bare_codes_but_skip_years_and_short_tokens():
    assert search.query_codes("Lot #: 82886 buprenorphine") == {"82886"}
    assert search.query_codes("2023 Honda CBR600RR engine") == {"CBR600RR"}
    assert search.query_codes("upc 0 12345 67890 5") == {"012345678905"}
    assert search.query_codes("F1 4x4 truck") == set()


def test_exact_identifier_matches_come_first(conn, corpus):
    def embed_towards_heater(texts):
        return [one_hot(0) for _ in texts]

    results = search.search(
        conn, "is zm-300 recalled", embedder=embed_towards_heater, use_rerank=False
    )
    assert results[0].source_id == "26801"
    assert search.identifier_matches(conn, "H-100 helmet 012345678905") == {corpus["26730"]: 2}
    assert search.identifier_matches(conn, "2023 heaters") == {}  # a year never short-circuits
    ablated = search.search(
        conn, "zm-300", use_identifiers=False, use_rerank=False, embedder=embed_towards_heater
    )
    assert ablated[0].source_id == "26532"  # no text overlap, so only the dense ranking remains


def test_rerank_reorders_fused_candidates_but_keeps_exact_matches_first(conn, corpus):
    def embed_towards_heater(texts):
        return [one_hot(0) for _ in texts]

    def prefers_mattresses(query, documents):
        return [1.0 if "Mattress" in d else 0.0 for d in documents]

    results = search.search(conn, "hazard", embedder=embed_towards_heater,
                            reranker=prefers_mattresses)  # fmt: skip
    assert results[0].source_id == "26801"
    exact_first = search.search(conn, "hazard H-100", embedder=embed_towards_heater,
                                reranker=prefers_mattresses)  # fmt: skip
    assert [h.source_id for h in exact_first[:2]] == ["26730", "26801"]


def test_bge_reranker_prefers_the_relevant_document():
    pytest.importorskip("sentence_transformers")
    from recall_lens.retrieval.rerank import default_reranker

    heater, helmet = default_reranker(
        "space heater that can catch fire",
        ["Tower heaters recalled due to fire hazard", "Bike helmets recalled due to head injury"],
    )
    assert heater > helmet
