from recall_lens.agents import nodes
from recall_lens.perception.read import Reading


def test_identify_merges_query_codes_with_photo_findings(monkeypatch):
    services = nodes.Services(lookups=True)
    monkeypatch.setattr(
        nodes.vin, "decode", lambda v: {"year": "2003", "make": "HONDA", "model": "Accord"}
    )
    state = {
        "query": "Is my Accord recalled? VIN 1HGCM82633A004352, lot # 5678",
        "photo_query": "ACME HEATER",
        "photo_text": "ACME HEATER Model SH-100",
        "identifiers": [["model", "SH-100"]],
        "codes": ["SH-100"],
    }
    update = nodes.identify(services)(state)
    assert ["vin", "1HGCM82633A004352"] in update["identifiers"]
    assert ["lot", "5678"] in update["identifiers"] and ["model", "SH-100"] in update["identifiers"]
    assert {"SH-100", "1HGCM82633A004352"} <= set(update["codes"])
    assert update["search_text"].endswith("ACME HEATER 2003 HONDA Accord")
    assert update["text"] == state["query"] + "\nACME HEATER Model SH-100"


def test_identify_works_without_lookups_or_photo():
    update = nodes.identify(nodes.Services(lookups=False))({"query": "space heater fire"})
    assert update == {"identifiers": [], "codes": [], "search_text": "space heater fire",
                      "text": "space heater fire"}  # fmt: skip


def test_perceive_reads_the_photo_and_builds_a_focused_query(monkeypatch):
    import pytest

    pytest.importorskip("PIL")
    import recall_lens.perception as perception

    monkeypatch.setattr(perception, "release_models", lambda: None)
    reading = Reading(
        texts=("Kichler Lighting LLC Model 43115BK", "29F2369A-108184"),
        identifiers=frozenset({("brand", "KICHLER LIGHTING LLC"), ("model", "43115BK")}),
        codes=frozenset({"43115BK", "29F2369A-108184"}),
    )
    services = nodes.Services(read_photo=lambda photo: reading, lookups=False)
    update = nodes.perceive(services)({"photo": "label.jpg"})
    assert update["identifiers"] == [["brand", "KICHLER LIGHTING LLC"], ["model", "43115BK"]]
    assert update["codes"] == ["29F2369A-108184", "43115BK"]
    assert update["photo_query"].startswith("KICHLER LIGHTING LLC 29F2369A-108184 43115BK")
