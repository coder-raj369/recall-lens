import pytest

pytest.importorskip("PIL")

from recall_lens.perception import recalls  # noqa: E402
from recall_lens.perception.read import Reading  # noqa: E402


def test_query_adds_barcode_product_and_vin_vehicle(monkeypatch):
    reading = Reading(
        texts=("RAW CHEDDAR", "LOT 5"),
        identifiers=frozenset({("upc", "0850011234567"), ("vin", "1HGCM82633A004352")}),
        codes=frozenset({"0850011234567", "1HGCM82633A004352"}),
    )
    monkeypatch.setattr(
        recalls.barcode, "lookup", lambda upc: {"name": "Cheddar", "brands": ["Raw Farm"]}
    )
    monkeypatch.setattr(
        recalls.vin, "decode", lambda v: {"make": "HONDA", "model": "Accord", "year": "2003"}
    )
    query = recalls.build_query(reading, focused=False)
    assert query.startswith("Raw Farm Cheddar 2003 HONDA Accord RAW CHEDDAR")
    assert recalls.build_query(reading, lookups=False, focused=False) == "RAW CHEDDAR LOT 5"
    # Focused: codes and the whole-photo text, not the region text ("LOT 5").
    focused = recalls.build_query(reading, lookups=False)
    assert focused == "0850011234567 1HGCM82633A004352 RAW CHEDDAR"


def test_unreadable_photo_returns_no_hits(monkeypatch):
    empty = Reading(texts=("",), identifiers=frozenset(), codes=frozenset())
    monkeypatch.setattr(recalls, "read", lambda image, use_detection: empty)
    monkeypatch.setattr(recalls, "release_models", lambda: None)
    result = recalls.find_recalls(conn=None, image=None)
    assert result.hits == [] and result.query == ""
