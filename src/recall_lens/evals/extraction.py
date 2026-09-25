"""Field-level precision, recall and F1 for identifier extraction.

Usage: python -m recall_lens.evals.extraction [--split dev|test] [--systems rules model combined]

The dev split was used for error analysis while developing the rules; report the test split.

Codes (model, lot, upc, ndc) must match exactly after canonicalization. Brands match leniently:
corporate suffixes and punctuation are ignored and either name may contain the other, because
"Somerset Therapeutics, LLC" and "Somerset Therapeutics" name the same brand.
"""

import argparse
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path

from recall_lens.extract import rules
from recall_lens.ingest.models import Identifier, identifier

DATASETS = Path(__file__).resolve().parents[3] / "evals" / "datasets"
KINDS = ("brand", "model", "lot", "upc", "ndc")
CODE_KINDS = ("model", "lot", "upc", "ndc")
_SUFFIXES = re.compile(r"\b(?:INC|LLC|LTD|CO|CORP|CORPORATION|COMPANY|LIMITED|THE)\b")


def _brand_key(name: str) -> str:
    return " ".join(_SUFFIXES.sub(" ", re.sub(r"[^A-Z0-9& ]", " ", name.upper())).split())


def _brands_match(a: str, b: str) -> bool:
    a, b = _brand_key(a), _brand_key(b)
    return bool(a and b) and (a in b or b in a)


def score(predicted: set[Identifier], gold: set[Identifier]) -> Counter:
    """Count true positives, false positives and false negatives per kind for one record."""
    counts: Counter = Counter()
    for kind in KINDS:
        pred = {v for k, v in predicted if k == kind}
        want = {v for k, v in gold if k == kind}
        if kind == "brand":
            unmatched = set(want)
            for p in sorted(pred):
                hit = next((g for g in sorted(unmatched) if _brands_match(p, g)), None)
                if hit:
                    unmatched.discard(hit)
                    counts[kind, "tp"] += 1
                else:
                    counts[kind, "fp"] += 1
            counts[kind, "fn"] += len(unmatched)
        else:
            counts[kind, "tp"] += len(pred & want)
            counts[kind, "fp"] += len(pred - want)
            counts[kind, "fn"] += len(want - pred)
    return counts


def prf(counts: Counter, kinds: Iterable[str]) -> tuple[float, float, float]:
    tp, fp, fn = (sum(counts[k, c] for k in kinds) for c in ("tp", "fp", "fn"))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def load(split: str = "test") -> list[dict]:
    path = DATASETS / f"extraction_{split}.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for record in records:
        record["gold_ids"] = {
            ident
            for kind, values in record["gold"].items()
            for value in values
            if (ident := identifier(kind, value))
        }
    return records


def evaluate(records: list[dict], extract: Callable[[str], set[Identifier]]) -> Counter:
    total: Counter = Counter()
    for record in records:
        total += score(extract(record["text"]), record["gold_ids"])
    return total


def systems() -> dict[str, Callable[[str], set[Identifier]]]:
    from recall_lens.extract import model

    return {
        "rules": rules.extract,
        "model": model.extract,
        "combined": lambda text: rules.extract(text) | model.extract(text),
        "production": lambda text: rules.extract(text) | model.extract(text, model.BRAND_ONLY),
    }


def report(results: dict[str, Counter]) -> str:
    header = "| Kind | " + " | ".join(f"{name} P / R / F1" for name in results) + " |"
    lines = [header, "|---" * (len(results) + 1) + "|"]
    rows = [(kind, (kind,)) for kind in KINDS] + [
        ("**codes (micro)**", CODE_KINDS),
        ("**all (micro)**", KINDS),
    ]
    for label, kinds in rows:
        cells = [" / ".join(f"{v:.2f}" for v in prf(c, kinds)) for c in results.values()]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m recall_lens.evals.extraction")
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument(
        "--systems", nargs="+", default=["rules", "model", "combined", "production"]
    )
    args = parser.parse_args()
    records = load(args.split)
    available = systems() if set(args.systems) - {"rules"} else {"rules": rules.extract}
    results = {name: evaluate(records, available[name]) for name in args.systems}
    gold = Counter(k for r in records for k, _ in r["gold_ids"])
    print(f"{args.split}: {len(records)} recalls, gold identifiers: {dict(gold)}\n")
    print(report(results))


if __name__ == "__main__":
    main()
