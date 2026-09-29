from langgraph.checkpoint.memory import InMemorySaver

from recall_lens.agents.graph import Nodes, build
from recall_lens.agents.state import AFFECTED, UNDETERMINED


def recording_nodes(verdict, arbitrate=True):
    visited = []

    def node(name, update=None):
        def run(state):
            visited.append(name)
            return update or {}

        return run

    verdicts = [{"source_id": "1", "agency": "cpsc", "verdict": verdict, "reason": "",
                 "evidence": None, "method": "rules"}]  # fmt: skip
    nodes = Nodes(
        perceive=node("perceive"),
        identify=node("identify"),
        retrieve=node("retrieve"),
        verify=node("verify", {"verdicts": verdicts}),
        advise=node("advise", {"answer": {"verdict": verdict}}),
        arbitrate=node("arbitrate") if arbitrate else None,
    )
    return nodes, visited


def run(nodes, state):
    graph = build(nodes, checkpointer=InMemorySaver())
    return graph.invoke(state, {"configurable": {"thread_id": "t"}})


def test_text_check_skips_perception_and_arbitration_when_rules_decide():
    nodes, visited = recording_nodes(AFFECTED)
    result = run(nodes, {"query": "lot 1276118"})
    assert visited == ["identify", "retrieve", "verify", "advise"]
    assert result["answer"] == {"verdict": AFFECTED}


def test_photo_check_perceives_and_undecided_cases_are_arbitrated():
    nodes, visited = recording_nodes(UNDETERMINED)
    run(nodes, {"query": "", "photo": "label.jpg"})
    assert visited == ["perceive", "identify", "retrieve", "verify", "arbitrate", "advise"]


def test_without_an_arbitrator_undecided_cases_go_straight_to_advice():
    nodes, visited = recording_nodes(UNDETERMINED, arbitrate=False)
    run(nodes, {"query": "space heater"})
    assert visited == ["identify", "retrieve", "verify", "advise"]
