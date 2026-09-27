"""Chunk recalls and store dense embeddings for vector search.

Embedding is a separate, idempotent pass over recalls that have no chunks: new recalls and
recalls whose content changed (the upsert drops their chunks) are picked up automatically.
Requires the optional `ml` dependency group for the default embedder.
"""

import re
from collections.abc import Callable, Sequence
from functools import cache

import psycopg

MODEL_ID = "BAAI/bge-m3"  # 1024-dimension dense vectors, matching recall_chunks.embedding
CHUNK_CHARS = 1_200
# ponytail: very long reports (thousands of lot codes) are embedded from their opening text only;
# exact codes are still searchable through recall_identifiers.
MAX_CHUNKS = 8

Embedder = Callable[[Sequence[str]], Sequence[Sequence[float]]]

_SENTENCE_END = re.compile(r"(?<=[.;!?])\s+|\n+")


def chunk(title: str, body: str) -> list[str]:
    """Split body into sentence-aligned pieces of about CHUNK_CHARS, each prefixed by the title."""
    pieces, current = [], ""
    for sentence in filter(None, (s.strip() for s in _SENTENCE_END.split(body))):
        if current and len(current) + len(sentence) + 1 > CHUNK_CHARS:
            pieces.append(current)
            if len(pieces) == MAX_CHUNKS:
                break
            current = ""
        current = f"{current} {sentence}".strip()[: CHUNK_CHARS * 2]
    else:
        if current:
            pieces.append(current)
    return [f"{title}\n\n{piece}" for piece in pieces] or [title]


@cache
def _model():
    from sentence_transformers import SentenceTransformer  # heavy optional import

    model = SentenceTransformer(MODEL_ID)
    model.max_seq_length = 512  # chunks are ~300 tokens; the 8k default only costs memory
    return model


def default_embedder(texts: Sequence[str]) -> list[list[float]]:
    return _model().encode(list(texts), normalize_embeddings=True, batch_size=16).tolist()


def vector_literal(values: Sequence[float]) -> str:
    """Format a vector as a pgvector literal for use with a ::vector cast."""
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


def embed_pending(
    conn: psycopg.Connection, embedder: Embedder = default_embedder, batch_size: int = 32
) -> int:
    """Chunk and embed every recall without chunks. Returns the number of recalls embedded."""
    done = 0
    while True:
        rows = conn.execute(
            """
            SELECT r.id, r.title, concat_ws(E'\\n', r.hazard, r.remedy, r.description)
            FROM recalls r
            WHERE NOT EXISTS (SELECT 1 FROM recall_chunks c WHERE c.recall_id = r.id)
            ORDER BY r.id
            LIMIT %s
            """,
            (batch_size,),
        ).fetchall()
        if not rows:
            return done
        chunks = [(recall_id, i, text) for recall_id, title, body in rows
                  for i, text in enumerate(chunk(title, body))]  # fmt: skip
        vectors = embedder([text for _, _, text in chunks])
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO recall_chunks (recall_id, ord, content, embedding)"
                " VALUES (%s, %s, %s, %s::vector)",
                [
                    (rid, i, text, vector_literal(v))
                    for (rid, i, text), v in zip(chunks, vectors, strict=True)
                ],
            )
        conn.commit()
        done += len(rows)
