import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from recall_lens.ingest import nhtsa

FIXTURE = (Path(__file__).parent / "fixtures" / "nhtsa_rcl.tsv").read_text()


def test_groups_rows_into_one_recall_per_campaign_within_window():
    recalls = list(nhtsa.parse(io.StringIO(FIXTURE), date(2026, 1, 1), date(2026, 12, 31)))
    assert [r.source_id for r in recalls] == ["26V061000"]
    recall = recalls[0]
    assert recall.agency == "nhtsa"
    assert recall.product_type == "vehicle"
    assert recall.recall_date == date(2026, 2, 3)
    assert recall.source_url.endswith("nhtsaId=26V061000")
    assert "Affected: FORD TRANSIT (2023, 2024)" in recall.description
    assert {("brand", "FORD"), ("model", "TRANSIT"), ("year", "2023"), ("year", "2024")} <= (
        recall.identifiers
    )
    assert recall.raw["affected"] == ["FORD TRANSIT (2023, 2024)"]


def test_window_excludes_other_dates():
    recalls = list(nhtsa.parse(io.StringIO(FIXTURE), date(2010, 1, 1), date(2010, 12, 31)))
    assert [r.source_id for r in recalls] == ["10V178000"]


def test_fetch_reads_zipped_flat_file(monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("FLAT_RCL_POST_2010.txt", FIXTURE)
    monkeypatch.setattr(nhtsa, "http_fetch", lambda url, timeout: buffer.getvalue())
    assert [r.source_id for r in nhtsa.fetch(date(2026, 1, 1))] == ["26V061000"]


def test_rejects_dates_before_flat_file_coverage():
    with pytest.raises(ValueError):
        next(nhtsa.fetch(date(2009, 12, 31)))
