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


def test_retrieve_passes_codes_and_returns_plain_candidates(conn):
    from datetime import date
    from functools import partial

    from recall_lens.ingest import store
    from recall_lens.ingest.models import Recall

    recall = Recall(
        agency="cpsc", source_id="26532", title="Vornado Recalls Tower Heaters",
        hazard="Fire hazard", recall_date=date(2026, 6, 4), raw={},
        identifiers=frozenset({("model", "SRTH-1")}),
    )  # fmt: skip
    store.upsert(conn, recall)
    conn.commit()
    no_vectors = partial(nodes.retrieval.search, use_dense=False)
    services = nodes.Services(conn=conn, search=no_vectors)
    update = nodes.retrieve(services)({"search_text": "unrelated words", "codes": ["SRTH-1"]})
    assert [c["source_id"] for c in update["candidates"]] == ["26532"]
    assert set(update["candidates"][0]) == {
        "recall_id",
        "agency",
        "source_id",
        "title",
        "source_url",
    }
    assert nodes.retrieve(services)({"search_text": "", "codes": []}) == {"candidates": []}


def test_verify_checks_each_candidate_against_its_stored_scope(conn):
    from datetime import date

    from recall_lens.agents.state import AFFECTED, NOT_AFFECTED
    from recall_lens.ingest import store
    from recall_lens.ingest.models import Recall

    antacid = Recall(
        agency="fda",
        source_id="D-0565-2026",
        title="CAREone Calcium Antacid 96 tablets",
        description="Codes: Lot #: 1276118, 1276119, expires: JAN 2029.",
        recall_date=date(2026, 5, 28),
        raw={},
        identifiers=frozenset({("lot", "1276118"), ("lot", "1276119"), ("brand", "CAREONE")}),
    )
    transit = Recall(
        agency="nhtsa",
        source_id="26V061000",
        title="Ford Motor Company recall: Frame",
        description="Ford is recalling certain 2023-2024 Transit vehicles.",
        recall_date=date(2026, 2, 3),
        raw={"affected": ["FORD TRANSIT (2023, 2024)"]},
        identifiers=frozenset({("brand", "FORD"), ("model", "TRANSIT")}),
    )
    store.upsert(conn, antacid)
    store.upsert(conn, transit)
    ids = dict(conn.execute("SELECT source_id, id FROM recalls").fetchall())
    candidates = [
        {"recall_id": ids["D-0565-2026"], "agency": "fda", "source_id": "D-0565-2026", "title": "",
         "source_url": None},
        {"recall_id": ids["26V061000"], "agency": "nhtsa", "source_id": "26V061000", "title": "",
         "source_url": None},
    ]  # fmt: skip
    state = {
        "candidates": candidates,
        "identifiers": [["lot", "1276125"]],
        "codes": ["1276125"],
        "text": "CAREone antacid, lot # 1276125. Also my 2024 Ford Transit.",
    }
    verdicts = nodes.verify(nodes.Services(conn=conn))(state)["verdicts"]
    assert [v["verdict"] for v in verdicts] == [NOT_AFFECTED, AFFECTED]
    assert verdicts[0]["method"] == "rules" and "1276125" in verdicts[0]["reason"]
