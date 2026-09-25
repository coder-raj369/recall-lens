from datetime import date

import pytest

from recall_lens.ingest import __main__ as cli
from recall_lens.ingest.models import Recall


def fake_fetch(since, until):
    yield Recall(
        agency="cpsc", source_id="TEST-1", title="Acme Recalls Heaters",
        description="Model SH-100 heaters.", recall_date=since, raw={},
    )  # fmt: skip


def broken_fetch(since, until):
    raise ConnectionError("agency API down")
    yield


@pytest.fixture
def connectors(monkeypatch, conn, database_url):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setattr(cli, "CONNECTORS", {"cpsc": fake_fetch, "fda": broken_fetch})


def test_sync_enriches_and_stores_recalls(connectors, conn, capsys):
    argv = ["--agency", "cpsc", "--since", "2026-01-01", "--no-model", "--no-embed"]
    assert cli.main(argv) == 0
    assert "cpsc: 2026-01-01" in capsys.readouterr().out
    assert conn.execute("SELECT kind, value FROM recall_identifiers").fetchall() == [
        ("model", "SH-100")
    ]


def test_failing_agency_does_not_block_others(connectors, conn):
    assert cli.main(["--since", "2026-01-01", "--no-model", "--no-embed"]) == 1
    assert conn.execute("SELECT count(*) FROM recalls").fetchone() == (1,)
    statuses = conn.execute("SELECT agency, status FROM ingestion_runs ORDER BY agency").fetchall()
    assert statuses == [("cpsc", "succeeded"), ("fda", "failed")]


def test_incremental_default_starts_from_backfill_date(connectors, conn):
    cli.main(["--agency", "cpsc", "--until", "2026-09-01", "--no-model", "--no-embed"])
    assert conn.execute("SELECT since FROM ingestion_runs").fetchone() == (date(2020, 1, 1),)
