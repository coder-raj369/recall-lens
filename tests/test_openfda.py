import json
import urllib.error
from datetime import date
from pathlib import Path

from recall_lens.ingest import openfda

RECORDS = json.loads((Path(__file__).parent / "fixtures" / "openfda.json").read_text())


def test_normalizes_food_recall():
    recall = openfda.normalize(RECORDS["food"], "food")
    assert recall.agency == "fda"
    assert recall.source_id == "H-1331-2026"
    assert recall.product_type == "food"
    assert recall.recall_date == date(2026, 8, 1)
    assert recall.hazard.startswith("Class I: ")
    assert "Codes: BATCH NO: 130 EF" in recall.description
    assert recall.source_url.endswith("Event=99684")
    assert ("brand", "EURO FOODS GROUP USA NJ INC") in recall.identifiers


def test_uses_openfda_brand_upc_and_ndc_when_present():
    record = RECORDS["drug"]
    recall = openfda.normalize(record, "drug")
    kinds = {kind for kind, _ in recall.identifiers}
    assert {"brand", "upc", "ndc"} <= kinds
    assert ("brand", record["openfda"]["brand_name"][0].upper()) in recall.identifiers


def test_missing_recall_number_gets_stable_fallback_id():
    for placeholder in ("", "N/A"):
        record = RECORDS["food"] | {"recall_number": placeholder}
        first = openfda.normalize(record, "food").source_id
        assert first.startswith("EVENT-99684-")
        assert openfda.normalize(record, "food").source_id == first


def test_long_product_descriptions_are_truncated_for_titles():
    recall = openfda.normalize(RECORDS["device"], "device")
    assert len(recall.title) <= 201


def test_paginates_until_total_and_treats_404_as_empty(monkeypatch):
    pages = {0: 1000, 1000: 1000, 2000: 500}

    def fake_get_json(url, params):
        if "device" in url:
            raise urllib.error.HTTPError(url, 404, "No matches", None, None)
        n = pages[params["skip"]]
        return {"meta": {"results": {"total": 2500}}, "results": [RECORDS["food"]] * n}

    monkeypatch.setattr(openfda, "get_json", fake_get_json)
    monkeypatch.setattr(openfda, "CATEGORIES", ("food", "device"))
    recalls = list(openfda.fetch(date(2026, 1, 1), date(2026, 6, 30)))
    assert len(recalls) == 2500
