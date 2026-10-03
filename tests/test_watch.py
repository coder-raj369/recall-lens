"""The watchlist emails each recall that newly covers a watched product, once."""

from datetime import date
from functools import partial

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from recall_lens import api, watch
from recall_lens.agents import nodes
from recall_lens.agents.graph import Nodes, build
from recall_lens.agents.state import AFFECTED, NO_MATCH
from recall_lens.ingest import store
from recall_lens.ingest.models import Recall

ME = "me@example.com"
HEATER = {
    "search_text": "Vornado tower heater model SRTH-1",
    "text": "Vornado tower heater\nmodel SRTH-1",
    "identifiers": [["brand", "VORNADO"], ["model", "SRTH-1"]],
    "codes": ["SRTH-1"],
}


@pytest.fixture
def services(conn, monkeypatch):
    monkeypatch.setenv("RECALL_LENS_ALERT_RECIPIENTS", f"Me@Example.com, {ME}")
    monkeypatch.setenv("RECALL_LENS_URL", "https://recalls.example")
    return nodes.Services(conn=conn, search=partial(nodes.retrieval.search, use_dense=False))


def recall_the_heater(conn, source_id="26532"):
    recall = Recall(
        agency="cpsc", source_id=source_id, title="Vornado Recalls\nTower Heaters",
        description="This recall involves Vornado tower heaters, model SRTH-1.",
        hazard="Fire hazard", remedy="Refund", recall_date=date(2026, 6, 4), raw={},
        source_url=f"https://www.cpsc.gov/Recalls/{source_id}",
        identifiers=frozenset({("brand", "VORNADO"), ("model", "SRTH-1")}),
    )  # fmt: skip
    store.upsert(conn, recall)
    conn.execute("REFRESH MATERIALIZED VIEW lexeme_stats")
    conn.commit()


def test_a_watched_product_is_emailed_once_when_a_recall_covers_it(conn, services):
    sent = []
    token = watch.add(conn, {**HEATER, "answer": {"verdict": NO_MATCH, "recalls": []}}, ME)
    assert watch.alert(conn, services, send=lambda *email: sent.append(email)) == 0 and not sent

    recall_the_heater(conn)
    assert watch.alert(conn, services, send=lambda *email: sent.append(email)) == 0
    [(to, subject, body)] = sent
    assert (to, subject) == (ME, "Recall alert: Vornado Recalls Tower Heaters")
    assert "Your product is covered by a recall." in body and "Hazard: Fire hazard" in body
    assert "You asked RecallLens to watch: Vornado tower heater model SRTH-1" in body
    assert f"https://recalls.example/?stop={token}" in body

    assert watch.alert(conn, services, send=lambda *email: sent.append(email)) == 0
    assert len(sent) == 1  # told once


def test_a_recall_is_recorded_only_after_its_email_went_out(conn, services):
    def down(*email):
        raise OSError("the mail server is down")

    watch.add(conn, {**HEATER, "answer": {"verdict": NO_MATCH, "recalls": []}}, ME)
    recall_the_heater(conn)
    assert watch.alert(conn, services, send=down) == 1
    sent = []
    assert watch.alert(conn, services, send=lambda *email: sent.append(email)) == 0
    assert len(sent) == 1  # retried on the next run


def test_recalls_already_shown_and_unapproved_addresses_get_no_email(conn, services, monkeypatch):
    recall_the_heater(conn)
    recall_id = conn.execute("SELECT id FROM recalls").fetchone()[0]
    shown = {"verdict": AFFECTED, "recalls": [{"recall_id": recall_id}]}
    watch.add(conn, {**HEATER, "answer": shown}, ME)
    watch.add(conn, {**HEATER, "answer": {"verdict": NO_MATCH, "recalls": []}}, "old@example.com")
    sent = []
    assert watch.alert(conn, services, send=lambda *email: sent.append(email)) == 0 and not sent

    recall_the_heater(conn, source_id="26999")  # a second recall of the same model is news
    assert watch.alert(conn, services, send=lambda *email: sent.append(email)) == 0
    assert [to for to, _, _ in sent] == [ME]


def test_a_finished_check_can_be_watched_and_unwatched_by_its_token(conn, services):
    graph = build(
        Nodes(
            perceive=lambda state: {},
            identify=lambda state: HEATER,
            retrieve=lambda state: {"candidates": []},
            verify=lambda state: {"verdicts": []},
            advise=lambda state: {"answer": {"verdict": NO_MATCH, "message": "", "recalls": []}},
        ),
        checkpointer=InMemorySaver(),
    )
    with TestClient(api.create_app(graph, db=conn)) as client:
        stream = client.post("/checks", json={"query": "Vornado tower heater model SRTH-1"})
        check_id = stream.text.split('"id": "')[1].split('"')[0]

        watch_url = f"/checks/{check_id}/watch"
        assert client.post(watch_url, json={"email": "you@example.com"}).status_code == 403
        assert client.post("/checks/unknown/watch", json={"email": ME}).status_code == 404
        created = client.post(watch_url, json={"email": " Me@Example.com "})
        assert created.status_code == 201
        token = created.json()["token"]

        assert client.get(f"/watches/{token}").json() == {"product": HEATER["text"]}
        assert conn.execute("SELECT email, state FROM watch_items").fetchall() == [(ME, HEATER)]
        assert client.delete(f"/watches/{token}").status_code == 204
        assert client.get(f"/watches/{token}").status_code == 404
        assert client.delete(f"/watches/{token}").status_code == 404


def test_send_logs_in_over_starttls_with_the_configured_account(monkeypatch):
    calls = []

    class Server:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *error):
            pass

        def __getattr__(self, name):
            return lambda *args: calls.append((name, *args))

    monkeypatch.setattr(watch.smtplib, "SMTP", Server)
    for name, value in [("HOST", "smtp.example"), ("USER", "user"), ("PASSWORD", "secret")]:
        monkeypatch.setenv(f"SMTP_{name}", value)
    monkeypatch.setenv("SMTP_FROM", "RecallLens <alerts@example.com>")
    watch.send(ME, "Recall alert: heaters", "Your product is covered by a recall.")
    connect, starttls, login, (_, message) = calls
    assert (connect, starttls, login) == (
        ("connect", "smtp.example", 587),
        ("starttls",),
        ("login", "user", "secret"),
    )
    assert (message["To"], message["Subject"]) == (ME, "Recall alert: heaters")
    assert message["From"] == "RecallLens <alerts@example.com>"


def test_an_address_watches_a_bounded_number_of_products(conn, services, monkeypatch):
    monkeypatch.setattr(watch, "MAX_ITEMS", 1)
    state = {**HEATER, "answer": {"verdict": NO_MATCH, "recalls": []}}
    assert watch.add(conn, state, ME) and watch.add(conn, state, ME) is None
