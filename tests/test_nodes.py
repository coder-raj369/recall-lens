import pytest

from recall_lens.agents import nodes
from recall_lens.agents.state import AFFECTED, NEEDS_INFO, NO_MATCH, NOT_AFFECTED, UNDETERMINED
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


def test_perceive_reports_photos_it_cannot_use(monkeypatch):
    pytest.importorskip("PIL")
    import recall_lens.perception as perception

    monkeypatch.setattr(perception, "release_models", lambda: None)

    def missing(photo):
        raise FileNotFoundError(photo)

    blank = Reading(texts=("",), identifiers=frozenset(), codes=frozenset())
    for read, error in [(missing, "could not be opened"), (lambda photo: blank, "No text")]:
        update = nodes.perceive(nodes.Services(read_photo=read))({"photo": "label.jpg"})
        assert list(update) == ["photo_error"] and error in update["photo_error"]


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


def candidate(i, recall_id=None):
    return {"recall_id": recall_id or i, "agency": "cpsc", "source_id": str(i),
            "title": f"Recall {i}", "source_url": f"https://cpsc.gov/{i}"}  # fmt: skip


def verdict(i, value, confidence=None, reason="Model X-1 is listed in this recall.", evidence=None):
    return {"source_id": str(i), "agency": "cpsc", "verdict": value, "reason": reason,
            "evidence": evidence, "method": "rules" if confidence is None else "llm",
            "confidence": confidence}  # fmt: skip


@pytest.mark.parametrize(
    ("decided", "expected", "cited"),
    [
        ([(NOT_AFFECTED, None), (UNDETERMINED, None), (AFFECTED, None)], AFFECTED, ["3"]),
        ([(NOT_AFFECTED, None), (NEEDS_INFO, None)], NEEDS_INFO, ["2"]),
        ([(NOT_AFFECTED, None), (NOT_AFFECTED, None)], NOT_AFFECTED, ["1", "2"]),
        ([(UNDETERMINED, None), (UNDETERMINED, None)], NO_MATCH, []),
        # Unsure LLM verdicts abstain: never "not affected", nor "unrelated", on a guess.
        ([(NOT_AFFECTED, 0.6)], NEEDS_INFO, ["1"]),
        ([(UNDETERMINED, 0.5)], NEEDS_INFO, ["1"]),
        ([(UNDETERMINED, 0.95), (AFFECTED, 0.9)], AFFECTED, ["2"]),
    ],
)
def test_decide_prefers_any_sign_of_a_recall_and_abstains_when_unsure(decided, expected, cited):
    candidates = [candidate(i) for i in range(1, len(decided) + 1)]
    verdicts = [verdict(i, v, c) for i, (v, c) in enumerate(decided, 1)]
    final, recalls = nodes.decide(candidates, verdicts, threshold=0.8)
    assert final == expected and [r["source_id"] for r in recalls] == cited


def test_advise_cites_the_recall_with_its_hazard_and_remedy(conn):
    from datetime import date

    from recall_lens.ingest import store
    from recall_lens.ingest.models import Recall

    store.upsert(
        conn,
        Recall(agency="cpsc", source_id="1", title="Recall 1", recall_date=date(2026, 6, 4),
               raw={}, hazard="The heater can overheat.", remedy="Stop using it; get a refund."),
    )  # fmt: skip
    (recall_id,) = conn.execute("SELECT id FROM recalls").fetchone()
    services = nodes.Services(conn=conn)
    state = {
        "candidates": [candidate(1, recall_id)],
        "verdicts": [verdict(1, AFFECTED, evidence="Model X-1 heaters")],
    }
    answer = nodes.advise(services)(state)["answer"]
    assert answer["verdict"] == AFFECTED and answer["recalls"][0]["source_id"] == "1"
    assert answer["message"].splitlines() == [
        "Your product is covered by a recall.",
        "CPSC recall 1: Recall 1",
        "Model X-1 is listed in this recall.",
        'The notice says: "Model X-1 heaters"',
        "Hazard: The heater can overheat.",
        "Remedy: Stop using it; get a refund.",
        "https://cpsc.gov/1",
    ]
    unread = nodes.advise(services)({**state, "photo_error": "The photo could not be opened."})
    assert (
        "The photo could not be opened. This answer uses your description only."
        in (unread["answer"]["message"])
    )
    state["verdicts"] = [verdict(1, UNDETERMINED, reason="Nothing ties it.")]
    assert nodes.advise(services)(state)["answer"] == {
        "verdict": NO_MATCH,
        "message": "No recall we found matches your product.\n"
        "Compared with the closest recall; others are not ruled out.",
        "recalls": [],
    }
