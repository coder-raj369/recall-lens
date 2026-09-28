"""Known-item retrieval evaluation with an ablation over the search pipeline.

Usage: python -m recall_lens.evals.retrieval [--split dev|test] [--configs ...] [--hnsw-check]

Metrics per configuration, strict (the target recall) and lenient (any relevant recall):
Recall@k as a hit rate (is a relevant recall in the top k?) and MRR@10. Query embeddings are
computed once and cached, so latencies compare the search stages rather than the encoder.
"""

import argparse
import json
import os
import statistics
import time
from collections import defaultdict
from functools import cache
from pathlib import Path

import psycopg

from recall_lens.retrieval import search

DATASETS = Path(__file__).resolve().parents[3] / "evals" / "datasets"
K = (1, 5, 10)
CONFIGS = {
    "dense": {"use_lexical": False, "use_identifiers": False, "use_rerank": False},
    "full-text (IDF)": {"use_dense": False, "use_identifiers": False, "use_rerank": False},
    "hybrid": {"use_identifiers": False, "use_rerank": False},
    "hybrid+ids": {},
    "hybrid+ids+rerank": {"use_rerank": True},
}


def load(split: str) -> list[dict]:
    path = DATASETS / f"retrieval_{split}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def first_hit(ranked: list[str], relevant: set[str]) -> int | None:
    """1-based rank of the first relevant result, or None."""
    return next((i for i, key in enumerate(ranked, start=1) if key in relevant), None)


def summarize(ranks: list[int | None]) -> dict[str, float]:
    n = len(ranks)
    metrics = {f"R@{k}": sum(r is not None and r <= k for r in ranks) / n for k in K}
    metrics["MRR@10"] = sum(1 / r for r in ranks if r is not None and r <= 10) / n
    return metrics


def run(conn: psycopg.Connection, records: list[dict], options: dict) -> dict:
    """Search every query with one configuration and collect ranks and latencies."""
    strict, lenient, latency, by_type = [], [], [], defaultdict(list)
    for record in records:
        start = time.perf_counter()
        results = search.search(conn, record["query"], limit=10, embedder=_embed, **options)
        latency.append(time.perf_counter() - start)
        ranked = [f"{hit.agency}:{hit.source_id}" for hit in results]
        strict.append(first_hit(ranked, {record["target"]}))
        lenient.append(first_hit(ranked, set(record["relevant"])))
        by_type[record["type"]].append(strict[-1])
    return {
        "strict": summarize(strict),
        "lenient": summarize(lenient),
        "by_type": {
            kind: summarize(ranks) | {"n": len(ranks)} for kind, ranks in sorted(by_type.items())
        },
        "p50_ms": statistics.median(latency) * 1000,
        "p95_ms": statistics.quantiles(latency, n=20)[-1] * 1000,
    }


@cache
def _embed_one(text: str) -> tuple[float, ...]:
    from recall_lens.ingest.embed import default_embedder

    return tuple(default_embedder([text])[0])


def _embed(texts):
    return [_embed_one(text) for text in texts]


def _release_encoder() -> None:
    """Unload bge-m3 once queries are cached, so it and the reranker (about 2.2 GB each) are
    never resident together; on an 8 GB machine the pair pushed the evaluation into swap."""
    import gc

    from recall_lens.ingest import embed

    embed._model.cache_clear()
    gc.collect()


def hnsw_check(conn: psycopg.Connection, records: list[dict], k: int = 50) -> str:
    """Compare HNSW dense retrieval against an exact scan: neighbor overlap and latency."""
    overlap, approx_ms, exact_ms = [], [], []
    for record in records:
        vector = _embed([record["query"]])[0]
        start = time.perf_counter()
        approx = search.dense(conn, vector, k)
        approx_ms.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        # Any filter forces the exact scan; this one matches every recall.
        exact = search.dense(conn, vector, k, search.Filters(agencies=("cpsc", "fda", "nhtsa")))
        exact_ms.append((time.perf_counter() - start) * 1000)
        overlap.append(len(set(approx) & set(exact)) / max(len(exact), 1))
    return (
        f"HNSW vs exact dense top-{k}: mean overlap {statistics.mean(overlap):.3f}, "
        f"p50 {statistics.median(approx_ms):.0f} ms vs {statistics.median(exact_ms):.0f} ms"
    )


def report(split: str, n: int, results: dict[str, dict]) -> str:
    lines = [
        f"### Retrieval, {split} split ({n} queries)",
        "",
        "| Configuration | Strict R@1 | R@5 | R@10 | MRR@10 | Lenient R@5 | MRR@10"
        " | p50 ms | p95 ms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, r in results.items():
        s, le = r["strict"], r["lenient"]
        lines.append(
            f"| {name} | {s['R@1']:.2f} | {s['R@5']:.2f} | {s['R@10']:.2f} | {s['MRR@10']:.2f}"
            f" | {le['R@5']:.2f} | {le['MRR@10']:.2f} | {r['p50_ms']:.0f} | {r['p95_ms']:.0f} |"
        )
    by_type = next(iter(results.values()))["by_type"]
    lines += ["", "Strict R@5 by query type:", ""]
    header = " | ".join(f"{kind} ({m['n']})" for kind, m in by_type.items())
    lines.append(f"| Configuration | {header} |")
    kinds = list(by_type)
    lines.append("|---" * (len(kinds) + 1) + "|")
    for name, r in results.items():
        cells = [f"{r['by_type'][kind]['R@5']:.2f}" for kind in kinds]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m recall_lens.evals.retrieval")
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--configs", nargs="+", choices=list(CONFIGS), default=list(CONFIGS))
    parser.add_argument("--hnsw-check", action="store_true", help="compare HNSW with exact scan")
    args = parser.parse_args()
    records = load(args.split)
    for record in records:  # encode every query once, then free the encoder
        _embed([record["query"]])
    _release_encoder()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for record in records:  # warm caches and load the reranker outside the timings
            search.search(conn, record["query"], embedder=_embed, **CONFIGS[args.configs[-1]])
        results = {name: run(conn, records, CONFIGS[name]) for name in args.configs}
        print(report(args.split, len(records), results))
        if args.hnsw_check:
            print("\n" + hnsw_check(conn, records))


if __name__ == "__main__":
    main()
