"""The API streams graph progress as server-sent events; the graph here is made of fakes."""

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from recall_lens import api
from recall_lens.agents import nodes as agent_nodes
from recall_lens.agents.graph import Nodes, build
from recall_lens.agents.state import AFFECTED


def fake_graph(photos, identify=lambda state: {"codes": ["1276118"]}):
    """A graph that can read only a photo containing b"sharp"."""

    def perceive(state):
        photos.append(state["photo"])
        readable = Path(state["photo"]).read_bytes() == b"sharp"
        return {"photo_error": None if readable else "No text could be read from the photo."}

    nodes = Nodes(
        perceive=perceive,
        identify=identify,
        retrieve=lambda state: {"candidates": []},
        verify=lambda state: {"verdicts": []},
        advise=lambda state: {"answer": {"verdict": AFFECTED, "message": "Recalled."}},
        retake=agent_nodes.retake,
    )
    return build(nodes, checkpointer=InMemorySaver())


def events(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    parsed = []
    for block in response.text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if line[:1] != ":")
        parsed.append((fields["event"], json.loads(fields["data"])))
    return parsed


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_a_text_check_streams_each_step_then_the_answer():
    with TestClient(api.create_app(fake_graph([]))) as client:
        stream = events(client.post("/checks", json={"query": "lot 1276118"}))
    assert [event for event, _ in stream] == ["check", *["progress"] * 4, "answer"]
    assert [data["node"] for event, data in stream if event == "progress"] == [
        "identify",
        "retrieve",
        "verify",
        "advise",
    ]
    assert stream[1][1]["update"] == {"codes": ["1276118"]}
    assert stream[-1][1] == {"verdict": AFFECTED, "message": "Recalled."}


def test_an_unreadable_photo_asks_for_another_and_photos_are_not_kept():
    photos = []
    with TestClient(api.create_app(fake_graph(photos))) as client:
        first = events(client.post("/checks", json={"photo": b64(b"blurry")}))
        assert [event for event, _ in first] == ["check", "progress", "question"]
        assert first[-1][1]["reason"] == "No text could be read from the photo."
        check_id = first[0][1]["id"]

        second = events(client.post(f"/checks/{check_id}/resume", json={"photo": b64(b"sharp")}))
        steps = [data["node"] for event, data in second if event == "progress"]
        assert steps == ["retake", "perceive", "identify", "retrieve", "verify", "advise"]
        assert second[-1][0] == "answer"
        assert client.post(f"/checks/{check_id}/resume", json={}).status_code == 409
    assert len(photos) == 2 and not any(Path(photo).exists() for photo in photos)


def test_bad_requests_are_refused_before_streaming():
    with TestClient(api.create_app(fake_graph([]))) as client:
        assert client.post("/checks/unknown/resume", json={}).status_code == 404
        assert client.post("/checks", json={"photo": "not base64!"}).status_code == 422
        assert client.post("/checks", json={"query": "x" * 2_001}).status_code == 422


def test_a_failing_step_ends_the_stream_with_an_error_that_hides_internals():
    def identify(state):
        raise RuntimeError("password=hunter2")

    with TestClient(api.create_app(fake_graph([], identify))) as client:
        response = client.post("/checks", json={"query": "heater"})
    assert [event for event, _ in events(response)] == ["check", "error"]
    assert "hunter2" not in response.text


def test_claude_arbitration_is_off_unless_explicitly_enabled(monkeypatch):
    monkeypatch.delenv("RECALL_LENS_ARBITRATE", raising=False)
    assert api.arbitrator(agent_nodes.Services()) is None
    pytest.importorskip("anthropic")
    monkeypatch.setenv("RECALL_LENS_ARBITRATE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    assert callable(api.arbitrator(agent_nodes.Services()))  # built, not called: nothing billed


def test_each_worker_thread_gets_its_own_database_connection(database_url):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    connections, together = api.ThreadConnections(database_url), threading.Barrier(4)

    def backend(_):
        together.wait()  # four threads at once, as under concurrent checks
        return connections.execute("SELECT pg_backend_pid()").fetchone()[0]

    with ThreadPoolExecutor(4) as pool:
        backends = set(pool.map(backend, range(4)))
    assert len(backends) == len(connections.opened) == 4
    connections.close()
    assert all(conn.closed for conn in connections.opened)
