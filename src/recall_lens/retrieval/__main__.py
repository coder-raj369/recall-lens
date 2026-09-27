"""Search the recall corpus from the command line.

Usage: python -m recall_lens.retrieval "vornado space heater fire" [--limit 10]
"""

import argparse
import os
import sys

import psycopg

from recall_lens.retrieval.search import search


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recall_lens.retrieval", description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    conninfo = os.environ.get("DATABASE_URL")
    if not conninfo:
        parser.error("DATABASE_URL is not set")
    with psycopg.connect(conninfo) as conn:
        for rank, hit in enumerate(search(conn, args.query, limit=args.limit), start=1):
            print(
                f"{rank:>2}. [{hit.agency.upper()} {hit.source_id}] {hit.recall_date}  {hit.title}"
            )
            if hit.source_url:
                print(f"    {hit.source_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
