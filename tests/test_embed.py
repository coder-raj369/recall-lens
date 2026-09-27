from datetime import date

import pytest

from recall_lens.ingest import embed, store
from recall_lens.ingest.models import Recall


def test_chunks_are_sentence_aligned_bounded_and_titled(monkeypatch):
    monkeypatch.setattr(embed, "CHUNK_CHARS", 40)
    monkeypatch.setattr(embed, "MAX_CHUNKS", 3)
    body = "First sentence here. Second sentence here. Third one. Fourth. Fifth. Sixth. Seventh."
    chunks = embed.chunk("Heater recall", body)
    assert 1 < len(chunks) <= 3
    assert all(c.startswith("Heater recall\n\n") for c in chunks)
    assert chunks[0].endswith("First sentence here.")
    assert embed.chunk("Title only", "") == ["Title only"]


def fake_embedder(texts):
    return [[1.0] + [0.0] * 1023 for _ in texts]


def recall(source_id, hazard="Fire hazard"):
    return Recall(
        agency="cpsc", source_id=source_id, title="Heater recall", hazard=hazard,
        recall_date=date(2026, 1, 1), raw={},
    )  # fmt: skip


def test_embed_pending_is_idempotent_and_reembeds_changed_recalls(conn):
    store.upsert(conn, recall("A"))
    store.upsert(conn, recall("B"))
    conn.commit()
    assert embed.embed_pending(conn, fake_embedder, batch_size=1) == 2
    assert embed.embed_pending(conn, fake_embedder) == 0

    store.upsert(conn, recall("A", hazard="Fire and burn hazard"))
    conn.commit()
    assert embed.embed_pending(conn, fake_embedder) == 1
    nearest = conn.execute(
        "SELECT count(*) FROM recall_chunks WHERE embedding <=> %s::vector < 0.01",
        (embed.vector_literal(fake_embedder(["q"])[0]),),
    ).fetchone()
    assert nearest == (2,)


def test_bge_m3_embeds_to_1024_normalized_dimensions():
    pytest.importorskip("sentence_transformers")
    (vector,) = embed.default_embedder(["Space heater recalled due to fire hazard"])
    assert len(vector) == 1024
    assert abs(sum(v * v for v in vector) - 1) < 1e-3
