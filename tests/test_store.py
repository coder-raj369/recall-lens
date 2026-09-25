from datetime import date

import pytest

from recall_lens.ingest import store
from recall_lens.ingest.models import Recall


def recall(**overrides):
    fields = {
        "agency": "cpsc",
        "source_id": "TEST-1",
        "title": "Space heater recall",
        "hazard": "Fire hazard",
        "recall_date": date(2026, 9, 1),
        "raw": {"id": 1},
        "identifiers": frozenset({("model", "SH-100"), ("brand", "ACME")}),
    }
    return Recall(**(fields | overrides))


def identifiers(conn):
    return set(conn.execute("SELECT kind, value FROM recall_identifiers").fetchall())


def test_upsert_inserts_then_skips_unchanged_then_updates(conn):
    assert store.upsert(conn, recall()) == "inserted"
    assert store.upsert(conn, recall()) == "unchanged"

    changed = recall(hazard="Fire and burn hazard", identifiers=frozenset({("model", "SH-200")}))
    assert store.upsert(conn, changed) == "updated"
    assert conn.execute("SELECT hazard FROM recalls").fetchone() == ("Fire and burn hazard",)
    assert identifiers(conn) == {("model", "SH-200")}


def test_update_drops_stale_chunks(conn):
    store.upsert(conn, recall())
    conn.execute(
        "INSERT INTO recall_chunks (recall_id, ord, content) SELECT id, 0, 'x' FROM recalls"
    )
    store.upsert(conn, recall(title="Space heater recall (expanded)"))
    assert conn.execute("SELECT count(*) FROM recall_chunks").fetchone() == (0,)


def test_sync_records_counts_and_supports_incremental_start(conn):
    batch = [recall(), recall(source_id="TEST-2")]
    counts = store.sync(
        conn, "cpsc", lambda since, until: batch, date(2026, 1, 1), date(2026, 9, 1)
    )
    assert counts == {"fetched": 2, "inserted": 2}

    counts = store.sync(
        conn, "cpsc", lambda since, until: batch, date(2026, 8, 1), date(2026, 9, 2)
    )
    assert counts == {"fetched": 2, "unchanged": 2}

    runs = conn.execute("SELECT status, inserted, unchanged FROM ingestion_runs ORDER BY id")
    assert runs.fetchall() == [("succeeded", 2, 0), ("succeeded", 0, 2)]
    assert store.incremental_since(conn, "cpsc", date(2020, 1, 1)) == date(2026, 8, 3)
    assert store.incremental_since(conn, "fda", date(2020, 1, 1)) == date(2020, 1, 1)


def test_failed_sync_is_recorded_and_keeps_committed_rows(conn):
    def failing_fetch(since, until):
        yield recall()
        raise ConnectionError("agency API down")

    with pytest.raises(ConnectionError):
        store.sync(conn, "cpsc", failing_fetch, date(2026, 1, 1), date(2026, 9, 1))
    status, inserted, error = conn.execute(
        "SELECT status, inserted, error FROM ingestion_runs"
    ).fetchone()
    assert (status, inserted) == ("failed", 1)
    assert "agency API down" in error
    assert conn.execute("SELECT count(*) FROM recalls").fetchone() == (1,)
