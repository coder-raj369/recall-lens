"""Idempotent persistence of recalls and bookkeeping of ingestion runs."""

from collections import Counter
from collections.abc import Callable, Iterable
from datetime import date, timedelta
from typing import Literal

import psycopg
from psycopg.types.json import Jsonb

from recall_lens.ingest.models import Recall

Outcome = Literal["inserted", "updated", "unchanged"]

# Agencies revise recent recalls, so incremental runs re-read a trailing window.
# Unchanged rows cost one hash comparison each.
INCREMENTAL_OVERLAP = timedelta(days=30)

_UPSERT = """
INSERT INTO recalls (agency, source_id, title, description, hazard, remedy, product_type,
                     recall_date, source_url, raw, content_hash)
VALUES (%(agency)s, %(source_id)s, %(title)s, %(description)s, %(hazard)s, %(remedy)s,
        %(product_type)s, %(recall_date)s, %(source_url)s, %(raw)s, %(content_hash)s)
ON CONFLICT (agency, source_id) DO UPDATE SET
    title = EXCLUDED.title, description = EXCLUDED.description, hazard = EXCLUDED.hazard,
    remedy = EXCLUDED.remedy, product_type = EXCLUDED.product_type,
    recall_date = EXCLUDED.recall_date, source_url = EXCLUDED.source_url, raw = EXCLUDED.raw,
    content_hash = EXCLUDED.content_hash, updated_at = now()
WHERE recalls.content_hash IS DISTINCT FROM EXCLUDED.content_hash
RETURNING id, xmax = 0 AS inserted
"""


def upsert(conn: psycopg.Connection, recall: Recall) -> Outcome:
    """Insert or update one recall and replace its identifiers; skip it if unchanged."""
    with conn.transaction():
        params = {
            "agency": recall.agency,
            "source_id": recall.source_id,
            "title": recall.title,
            "description": recall.description,
            "hazard": recall.hazard,
            "remedy": recall.remedy,
            "product_type": recall.product_type,
            "recall_date": recall.recall_date,
            "source_url": recall.source_url,
            "raw": Jsonb(recall.raw),
            "content_hash": recall.content_hash,
        }
        row = conn.execute(_UPSERT, params).fetchone()
        if row is None:
            return "unchanged"
        recall_id, inserted = row
        if not inserted:
            # Content changed: identifiers are replaced and stale chunks dropped for re-embedding.
            conn.execute("DELETE FROM recall_identifiers WHERE recall_id = %s", (recall_id,))
            conn.execute("DELETE FROM recall_chunks WHERE recall_id = %s", (recall_id,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO recall_identifiers (recall_id, kind, value) VALUES (%s, %s, %s)",
                [(recall_id, kind, value) for kind, value in sorted(recall.identifiers)],
            )
        return "inserted" if inserted else "updated"


def incremental_since(conn: psycopg.Connection, agency: str, default: date) -> date:
    """Start date for the next run: the last successful run's end minus the overlap window."""
    row = conn.execute(
        "SELECT max(until) FROM ingestion_runs WHERE agency = %s AND status = 'succeeded'",
        (agency,),
    ).fetchone()
    return row[0] - INCREMENTAL_OVERLAP if row and row[0] else default


def sync(
    conn: psycopg.Connection,
    agency: str,
    fetch: Callable[[date, date], Iterable[Recall]],
    since: date,
    until: date,
) -> Counter:
    """Fetch and upsert one agency's recalls, recording the run and its counts."""
    run_id = conn.execute(
        "INSERT INTO ingestion_runs (agency, since, until) VALUES (%s, %s, %s) RETURNING id",
        (agency, since, until),
    ).fetchone()[0]
    conn.commit()
    counts: Counter = Counter()
    try:
        for recall in fetch(since, until):
            counts["fetched"] += 1
            counts[upsert(conn, recall)] += 1
            conn.commit()
    except Exception as error:
        conn.rollback()
        conn.execute(
            "UPDATE ingestion_runs SET status = 'failed', error = %s, finished_at = now(),"
            " fetched = %s, inserted = %s, updated = %s, unchanged = %s WHERE id = %s",
            (repr(error), *(counts[k] for k in ("fetched", "inserted", "updated", "unchanged")),
             run_id),
        )  # fmt: skip
        conn.commit()
        raise
    conn.execute(
        "UPDATE ingestion_runs SET status = 'succeeded', finished_at = now(),"
        " fetched = %s, inserted = %s, updated = %s, unchanged = %s WHERE id = %s",
        (*(counts[k] for k in ("fetched", "inserted", "updated", "unchanged")), run_id),
    )
    conn.commit()
    return counts
