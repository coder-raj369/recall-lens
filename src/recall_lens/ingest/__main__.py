"""Sync recalls from agency sources into Postgres, then embed new or changed recalls.

Usage:
    python -m recall_lens.ingest                      # incremental sync of all agencies
    python -m recall_lens.ingest --since 2020-01-01   # backfill from a date
    python -m recall_lens.ingest --no-model --no-embed  # rules only, no ML dependencies
"""

import argparse
import os
import sys
from datetime import date

import psycopg

from recall_lens.extract.enrich import enrich
from recall_lens.ingest import cpsc, nhtsa, openfda, store

CONNECTORS = {"cpsc": cpsc.fetch, "fda": openfda.fetch, "nhtsa": nhtsa.fetch}  # FSIS: ADR-0004
BACKFILL_START = date(2020, 1, 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m recall_lens.ingest", description=__doc__)
    parser.add_argument(
        "--agency", nargs="+", choices=sorted(CONNECTORS), default=sorted(CONNECTORS)
    )
    parser.add_argument("--since", type=date.fromisoformat, help="default: incremental")
    parser.add_argument("--until", type=date.fromisoformat, default=date.today())
    parser.add_argument("--no-model", action="store_true", help="skip GLiNER extraction")
    parser.add_argument("--no-embed", action="store_true", help="skip chunk embedding")
    args = parser.parse_args(argv)

    conninfo = os.environ.get("DATABASE_URL")
    if not conninfo:
        parser.error("DATABASE_URL is not set")

    failed = []
    with psycopg.connect(conninfo) as conn:
        for agency in args.agency:
            since = args.since or store.incremental_since(conn, agency, BACKFILL_START)
            fetch = CONNECTORS[agency]

            def enriched(start, end, fetch=fetch):
                return (enrich(r, use_model=not args.no_model) for r in fetch(start, end))

            try:
                counts = store.sync(conn, agency, enriched, since, args.until)
            except Exception as error:  # one agency being down must not block the others
                print(f"{agency}: FAILED {since}..{args.until}: {error!r}", file=sys.stderr)
                failed.append(agency)
                continue
            print(
                f"{agency}: {since}..{args.until} "
                + " ".join(f"{k}={v}" for k, v in counts.items())
            )

        if not args.no_embed:
            from recall_lens.ingest.embed import embed_pending

            print(f"embedded: {embed_pending(conn)} recalls")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
