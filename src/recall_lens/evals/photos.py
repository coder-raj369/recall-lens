"""Photo evaluation: perception field accuracy and photo-to-recall retrieval.

Usage: python -m recall_lens.evals.photos [--split dev|test]

Stage 1 reads every photo twice, whole photo only and with detected label regions, using
Florence-2, OWLv2 and GLiNER. Stage 2 releases those models, loads bge-m3 and searches each
reading with the full-OCR and focused query strategies. Photos are downloaded once into
evals/.cache/photos.
"""

import argparse
import json
import os
import statistics
import time
from collections import Counter
from pathlib import Path

import psycopg

from recall_lens.evals.extraction import _brands_match, prf
from recall_lens.evals.retrieval import first_hit, summarize
from recall_lens.ingest.http import fetch
from recall_lens.ingest.models import identifier
from recall_lens.perception import release_models
from recall_lens.perception.image import load
from recall_lens.perception.read import Reading, read
from recall_lens.perception.recalls import build_query
from recall_lens.retrieval.search import search

DATASETS = Path(__file__).resolve().parents[3] / "evals" / "datasets"
CACHE = DATASETS.parent / ".cache" / "photos"
KINDS = ("brand", "model", "lot", "upc", "vin")
CODE_KINDS = ("model", "lot", "upc", "vin")
READ_CONFIGS = {"whole photo": False, "whole photo + regions": True}
QUERY_STRATEGIES = {"full OCR": {"focused": False}, "focused": {"focused": True}}


def load_split(split: str) -> list[dict]:
    path = DATASETS / f"photos_{split}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def photo(record: dict):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{record['id']}.img"
    if not path.exists():
        path.write_bytes(fetch(record["url"], timeout=120))
    return load(path)


def _code_key(value: str) -> str:
    """Kind-agnostic comparison key: UPCs ignore leading zeros, other codes ignore case."""
    return value.lstrip("0") if value.isdigit() else value.upper()


def field_counts(reading: Reading, gold: dict[str, list[str]]) -> Counter:
    """TP/FP/FN per identifier kind, plus kind-agnostic "codes" over every code read."""
    counts: Counter = Counter()
    want = {kind: {identifier(kind, v)[1] for v in gold.get(kind, [])} for kind in KINDS}
    got = {kind: {v for k, v in reading.identifiers if k == kind} for kind in KINDS}
    unmatched = set(want["brand"])
    for brand in got["brand"]:
        hit = next((g for g in sorted(unmatched) if _brands_match(brand, g)), None)
        counts["brand", "tp" if hit else "fp"] += 1
        unmatched.discard(hit)
    counts["brand", "fn"] += len(unmatched)
    for kind in CODE_KINDS:
        w, g = {_code_key(v) for v in want[kind]}, {_code_key(v) for v in got[kind]}
        counts[kind, "tp"] += len(w & g)
        counts[kind, "fp"] += len(g - w)
        counts[kind, "fn"] += len(w - g)
    w = {_code_key(v) for kind in CODE_KINDS for v in want[kind]}
    g = {_code_key(v) for v in reading.codes}
    counts["codes", "tp"] += len(w & g)
    counts["codes", "fp"] += len(g - w)
    counts["codes", "fn"] += len(w - g)
    return counts


def _reading(saved: list) -> Reading:
    texts, identifiers, codes = saved
    return Reading(tuple(texts), frozenset(map(tuple, identifiers)), frozenset(codes))


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m recall_lens.evals.photos")
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--dump", type=Path, help="write per-photo results as JSON lines")
    parser.add_argument("--reuse-readings", action="store_true", help="skip stage 1 if cached")
    args = parser.parse_args()
    dump: list[dict] = []
    records = load_split(args.split)

    readings: dict[str, list[Reading]] = {}
    fields: dict[str, Counter] = {}
    latency: dict[str, list[float]] = {}
    saved = CACHE.parent / f"readings_{args.split}.json"
    if args.reuse_readings and saved.exists():  # iterate on query strategies without re-reading
        state = json.loads(saved.read_text())
        readings = {n: [_reading(r) for r in rs] for n, rs in state["readings"].items()}
        fields = {
            n: Counter({tuple(k.split("|")): v for k, v in c.items()})
            for n, c in state["fields"].items()
        }
        latency = state["latency"]
    for name, use_detection in READ_CONFIGS.items():
        if name in readings:
            continue
        readings[name], fields[name], latency[name] = [], Counter(), []
        for record in records:
            image = photo(record)
            start = time.perf_counter()
            reading = read(image, use_detection=use_detection)
            latency[name].append(time.perf_counter() - start)
            readings[name].append(reading)
            fields[name] += field_counts(reading, record["gold"])
    saved.write_text(json.dumps({
        "readings": {n: [[list(r.texts), sorted(r.identifiers), sorted(r.codes)] for r in rs]
                     for n, rs in readings.items()},
        "fields": {n: {"|".join(k): v for k, v in c.items()} for n, c in fields.items()},
        "latency": latency,
    }))  # fmt: skip
    release_models()

    retrieval: dict[tuple[str, str], dict] = {}
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for name, strategy in [(n, s) for n in READ_CONFIGS for s in QUERY_STRATEGIES]:
            strict, lenient, by_source = [], [], {}
            for record, reading in zip(records, readings[name], strict=True):
                query = build_query(reading, **QUERY_STRATEGIES[strategy])
                hits = search(conn, query, limit=10, extra_codes=reading.codes) if query else []
                ranked = [f"{h.agency}:{h.source_id}" for h in hits]
                strict.append(first_hit(ranked, {record["target"]}))
                lenient.append(first_hit(ranked, set(record["relevant"])))
                by_source.setdefault(record["source"], []).append(strict[-1])
                legible = "legible text" if any(record["gold"].values()) else "product only"
                by_source.setdefault(legible, []).append(strict[-1])
                if args.dump:
                    dump.append({"id": record["id"], "reading": name, "query_strategy": strategy,
                                 "query": query, "codes": sorted(reading.codes), "rank": strict[-1],
                                 "top": ranked[:3], "target": record["target"]})  # fmt: skip
            retrieval[name, strategy] = {
                "strict": summarize(strict),
                "lenient": summarize(lenient),
                "by_source": {
                    s: summarize(r) | {"n": len(r)} for s, r in sorted(by_source.items())
                },
            }
    if args.dump:
        args.dump.write_text("".join(json.dumps(row) + "\n" for row in dump))
    print(report(args.split, len(records), fields, latency, retrieval))


def report(split, n, fields, latency, retrieval) -> str:
    lines = [
        f"### Photos, {split} split ({n} photos)",
        "",
        "Field accuracy (precision / recall / F1):",
        "",
    ]
    kinds = (*KINDS, "codes")
    lines.append("| Reading | " + " | ".join(kinds) + " | p50 s | p95 s |")
    lines.append("|---" * (len(kinds) + 3) + "|")
    for name, counts in fields.items():
        cells = [" / ".join(f"{v:.2f}" for v in prf(counts, (k,))) for k in kinds]
        p50 = statistics.median(latency[name])
        p95 = statistics.quantiles(latency[name], n=20)[-1]
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {p50:.1f} | {p95:.1f} |")
    sources = list(next(iter(retrieval.values()))["by_source"])
    lines += [
        "",
        "Photo to recall (strict R@1 / R@5 / MRR@10; lenient R@5; strict R@5 by source):",
        "",
    ]
    header = " | ".join(
        f"{s} ({next(iter(retrieval.values()))['by_source'][s]['n']})" for s in sources
    )
    lines.append(f"| Reading | Query | R@1 | R@5 | MRR@10 | Lenient R@5 | {header} |")
    lines.append("|---" * (6 + len(sources)) + "|")
    for (name, strategy), r in retrieval.items():
        s, le = r["strict"], r["lenient"]
        by = " | ".join(f"{r['by_source'][src]['R@5']:.2f}" for src in sources)
        lines.append(
            f"| {name} | {strategy} | {s['R@1']:.2f} | {s['R@5']:.2f} | {s['MRR@10']:.2f}"
            f" | {le['R@5']:.2f} | {by} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
