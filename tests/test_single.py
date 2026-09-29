"""Single-agent baseline on a mocked HTTP transport: the real SDK, no network, nothing billed."""

import json
from datetime import date

import pytest

anthropic = pytest.importorskip("anthropic")

import httpx2  # noqa: E402  (installed with anthropic)

from recall_lens.agents import single  # noqa: E402
from recall_lens.agents.state import AFFECTED, NEEDS_INFO  # noqa: E402
from recall_lens.agents.verify import parse_scope  # noqa: E402
from recall_lens.retrieval.search import Hit  # noqa: E402

ANTACID = parse_scope("CAREone Antacid", "CAREone Antacid\nCodes: Lot #: 1276118", [])


def client(responses, requests):
    def handler(request):
        requests.append(json.loads(request.content))
        return responses.pop(0)

    transport = httpx2.MockTransport(handler)
    return anthropic.Anthropic(
        api_key="test", max_retries=0, http_client=anthropic.DefaultHttpxClient(transport=transport)
    )


def message(content, stop_reason):
    return httpx2.Response(
        200,
        json={"id": "msg_test", "type": "message", "role": "assistant", "model": single.MODEL,
              "content": content, "stop_reason": stop_reason, "stop_sequence": None,
              "usage": {"input_tokens": 1, "output_tokens": 1}},
    )  # fmt: skip


def test_claude_searches_reads_notices_and_answers(monkeypatch):
    monkeypatch.setattr(single, "load_scope", lambda conn, recall_id: ANTACID)
    searched = []

    def search(conn, query, limit):
        searched.append(query)
        return [Hit(7, "fda", "D-0565-2026", "CAREone Antacid", date(2026, 5, 28), None)]

    answer = {"recall": "fda:D-0565-2026", "quote": "Lot #: 1276118", "verdict": "affected",
              "reason": "Lot 1276118 is listed."}  # fmt: skip
    responses = [
        message([{"type": "tool_use", "id": "t1", "name": "search_recalls",
                  "input": {"query": "CAREone antacid 1276118"}}], "tool_use"),
        message([{"type": "text", "text": json.dumps(answer)}], "end_turn"),
    ]  # fmt: skip
    requests = []
    result = single.check(client(responses, requests), None, "CAREone antacid lot 1276118", search)

    assert result == (AFFECTED, "fda:D-0565-2026", "Lot 1276118 is listed.")
    assert searched == ["CAREone antacid 1276118"]
    first, second = requests
    assert first["model"] == "claude-opus-5-5" and first["tools"][0]["name"] == "search_recalls"
    assert first["fallbacks"] == "default" and first["output_config"]["effort"] == "high"
    tool_result = second["messages"][-1]["content"][0]
    assert tool_result["tool_use_id"] == "t1" and "Lot #: 1276118" in tool_result["content"]


def test_refusals_and_endless_searching_abstain():
    refusal = [message([], "refusal")]
    assert single.check(client(refusal, []), None, "x")[0] == NEEDS_INFO
    searching = [
        message([{"type": "tool_use", "id": f"t{i}", "name": "search_recalls",
                  "input": {"query": "x"}}], "tool_use")
        for i in range(2)
    ]  # fmt: skip
    verdict, _, reason = single.check(
        client(searching, []), None, "x", search=lambda *a, **k: [], max_searches=1
    )
    assert verdict == NEEDS_INFO and "incomplete" in reason
