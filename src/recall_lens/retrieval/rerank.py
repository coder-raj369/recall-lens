"""Cross-encoder reranking with BAAI/bge-reranker-v2-m3 (Apache-2.0).

Requires the optional `ml` dependency group.
"""

from collections.abc import Callable, Sequence
from functools import cache

MODEL_ID = "BAAI/bge-reranker-v2-m3"
MAX_TOKENS = 512

Reranker = Callable[[str, Sequence[str]], Sequence[float]]


@cache
def _model():
    from sentence_transformers import CrossEncoder  # heavy optional import

    return CrossEncoder(MODEL_ID, max_length=MAX_TOKENS)


def default_reranker(query: str, documents: Sequence[str]) -> list[float]:
    """Relevance score for each document; higher is more relevant."""
    if not documents:
        return []
    pairs = [(query, document) for document in documents]
    return _model().predict(pairs, batch_size=16).tolist()
