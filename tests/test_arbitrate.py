"""Claude arbitration against a mocked HTTP transport: the real SDK, no network, nothing billed."""

import json

import pytest

anthropic = pytest.importorskip("anthropic")

import httpx2  # noqa: E402  (installed with anthropic)

from recall_lens.agents import arbitrate  # noqa: E402
from recall_lens.agents.nodes import Services  # noqa: E402
from recall_lens.agents.state import AFFECTED, NEEDS_INFO, UNDETERMINED  # noqa: E402
from recall_lens.agents.verify import parse_scope  # noqa: E402

ANTACID = parse_scope("CAREone Antacid", "CAREone Antacid\nLot #: 1276118", [("lot", "1276118")])
RAILS = parse_scope(
    "ELENKER Portable Bed Rails Recalled Due to Risk of Serious Injury or Death",
    "ELENKER Portable Bed Rails\nModel HFK-5115 (SKU K90002C1) and Model HFK-5116 (SKU K90001C1).",
    [("brand", "ELENKER"), ("model", "HFK-5115"), ("model", "HFK-5116")],
)
GLOVES = parse_scope("Medline Convenience Kits", "Medline Convenience Kits\nAll Lots", [])


def client(handler):
    transport = httpx2.MockTransport(handler)
    return anthropic.Anthropic(
        api_key="test", max_retries=0, http_client=anthropic.DefaultHttpxClient(transport=transport)
    )


def message(content, stop_reason="end_turn"):
    return httpx2.Response(
        200,
        json={"id": "msg_test", "type": "message", "role": "assistant", "model": arbitrate.MODEL,
              "content": content, "stop_reason": stop_reason, "stop_sequence": None,
              "usage": {"input_tokens": 1, "output_tokens": 1}},
    )  # fmt: skip


def answer(*judgments):
    text = json.dumps({"judgments": list(judgments)})
    return message(
        [{"type": "thinking", "thinking": "", "signature": "s"}, {"type": "text", "text": text}]
    )


def test_only_undetermined_candidates_reach_claude_and_quotes_must_be_in_the_notice(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return answer(
            {"notice": 1, "quote": "Model HFK-5116 (SKU K90001C1)", "verdict": "needs_info",
             "reason": "Only ELENKER HFK-5115 and HFK-5116 rails are recalled.", "confidence": 0.8},
            {"notice": 2, "quote": "All Medline exam gloves", "verdict": "affected",
             "reason": "Medline gloves are recalled.", "confidence": 0.9},
        )  # fmt: skip

    scopes = {1: ANTACID, 2: RAILS, 3: GLOVES}
    decided = [AFFECTED, UNDETERMINED, UNDETERMINED]
    monkeypatch.setattr(arbitrate, "load_scope", lambda conn, recall_id: scopes[recall_id])
    state = {
        "text": "portable bed rail from Amazon, and a box of Medline exam gloves",
        "identifiers": [["brand", "MEDLINE"]],
        "candidates": [{"recall_id": i, "agency": "cpsc", "source_id": str(i), "title": "",
                        "source_url": None} for i in scopes],
        "verdicts": [{"source_id": str(i), "agency": "cpsc", "verdict": verdict, "reason": "rules",
                      "evidence": None, "method": "rules", "confidence": None}
                     for i, verdict in zip(scopes, decided, strict=True)],
    }  # fmt: skip
    verdicts = arbitrate.arbitrate(Services(), client(handler))(state)["verdicts"]

    assert verdicts[0] == state["verdicts"][0]  # rule decisions are final
    assert verdicts[1]["verdict"] == NEEDS_INFO and verdicts[1]["method"] == "llm"
    assert verdicts[1]["evidence"] == "Model HFK-5116 (SKU K90001C1)"
    assert verdicts[1]["confidence"] == 0.8
    assert verdicts[2]["verdict"] == UNDETERMINED and "quote" in verdicts[2]["reason"]

    (request,) = requests
    body = json.loads(request.content)
    assert body["model"] == "claude-opus-5-5" and body["max_tokens"] == 16000
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"]["effort"] == "high"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in request.headers["anthropic-beta"]
    prompt = body["messages"][0]["content"]
    assert prompt.count("<notice ") == 2 and "CAREone" not in prompt
    assert "brand: MEDLINE" in prompt


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (lambda: message([], stop_reason="refusal"), "declined"),
        (lambda: httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error",
                                                                          "message": "busy"}}),
         "unavailable"),
        (lambda: message([{"type": "text", "text": '{"judgments": [{"notice"'}], "max_tokens"),
         "incomplete"),
        (lambda: answer(), "did not judge"),
    ],
)  # fmt: skip
def test_unusable_answers_leave_the_candidate_undetermined(response, reason):
    notices = [arbitrate.notice(RAILS)]
    (result,) = arbitrate.judge(client(lambda request: response()), {"text": "bed rail"}, notices)
    assert result["verdict"] == UNDETERMINED and reason in result["reason"]
