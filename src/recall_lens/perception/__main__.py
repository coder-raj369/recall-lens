"""Find recalls for a product photo.

Usage: python -m recall_lens.perception photo.jpg [--no-detection] [--rerank] [--limit 5]
"""

import argparse
import os
import sys

import psycopg

from recall_lens.perception.image import load
from recall_lens.perception.recalls import find_recalls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recall_lens.perception", description=__doc__)
    parser.add_argument("photo", help="path or URL of a product photo")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--no-detection", action="store_true", help="read the whole photo only")
    parser.add_argument("--rerank", action="store_true", help="rerank with bge-reranker-v2-m3")
    args = parser.parse_args(argv)
    conninfo = os.environ.get("DATABASE_URL")
    if not conninfo:
        parser.error("DATABASE_URL is not set")
    with psycopg.connect(conninfo) as conn:
        result = find_recalls(
            conn, load(args.photo), limit=args.limit,
            use_detection=not args.no_detection, use_rerank=args.rerank,
        )  # fmt: skip
    print(
        "Identifiers:",
        ", ".join(f"{k}={v}" for k, v in sorted(result.reading.identifiers)) or "none",
    )
    for rank, hit in enumerate(result.hits, start=1):
        print(f"{rank:>2}. [{hit.agency.upper()} {hit.source_id}] {hit.recall_date}  {hit.title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
