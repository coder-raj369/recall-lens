"""Search the recall corpus from the command line.

Usage: python -m recall_lens.retrieval "vornado space heater fire" [--limit 10]
       python -m recall_lens.retrieval "airbag inflator" --agency nhtsa --since 2025-01-01
"""

import argparse
import os
import sys
from datetime import date

import psycopg

from recall_lens.ingest.models import AGENCIES
from recall_lens.retrieval.search import Filters, search


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recall_lens.retrieval", description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--agency", nargs="+", choices=sorted(AGENCIES), default=())
    parser.add_argument("--product-type", nargs="+", default=(), help="e.g. food drug vehicle")
    parser.add_argument("--since", type=date.fromisoformat)
    parser.add_argument("--until", type=date.fromisoformat)
    args = parser.parse_args(argv)
    filters = Filters(tuple(args.agency), tuple(args.product_type), args.since, args.until)
    conninfo = os.environ.get("DATABASE_URL")
    if not conninfo:
        parser.error("DATABASE_URL is not set")
    with psycopg.connect(conninfo) as conn:
        for rank, hit in enumerate(
            search(conn, args.query, limit=args.limit, filters=filters), start=1
        ):
            print(
                f"{rank:>2}. [{hit.agency.upper()} {hit.source_id}] {hit.recall_date}  {hit.title}"
            )
            if hit.source_url:
                print(f"    {hit.source_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
