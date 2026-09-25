import json
from datetime import date
from pathlib import Path

from recall_lens.ingest import cpsc

RECORDS = json.loads((Path(__file__).parent / "fixtures" / "cpsc.json").read_text())


def test_normalizes_recall_fields():
    recall = cpsc.normalize(RECORDS[0])
    assert recall.agency == "cpsc"
    assert recall.source_id == "26789"
    assert recall.recall_date == date(2026, 9, 24)
    assert recall.product_type == "consumer_product"
    assert recall.source_url.startswith("https://cpsc.gov/Recalls/")
    assert "head injury" in recall.hazard
    assert "full refund" in recall.remedy
    assert ("brand", "5COLOR") in recall.identifiers


def test_extracts_structured_upcs():
    recall = cpsc.normalize(RECORDS[1])
    upcs = {value for kind, value in recall.identifiers if kind == "upc"}
    assert upcs == {u["UPC"] for u in RECORDS[1]["ProductUPCs"]}


def test_fetch_requests_one_window_per_year(monkeypatch):
    calls = []
    monkeypatch.setattr(cpsc, "get_json", lambda url, params: calls.append(params) or [])
    list(cpsc.fetch(date(2024, 6, 1), date(2026, 2, 1)))
    windows = [(p["RecallDateStart"], p["RecallDateEnd"]) for p in calls]
    assert windows == [
        (date(2024, 6, 1), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), date(2026, 2, 1)),
    ]
