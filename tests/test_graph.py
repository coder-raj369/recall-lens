from dataclasses import replace

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from recall_lens.agents import nodes as agent_nodes
from recall_lens.agents.graph import Nodes, build, postgres_checkpointer
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


def test_arbitration_is_skipped_once_a_recall_covers_the_unit():
    from recall_lens.agents.graph import needs_arbitration

    affected, undetermined = {"verdict": AFFECTED}, {"verdict": UNDETERMINED}
    assert needs_arbitration([undetermined])
    assert not needs_arbitration([affected, undetermined])  # the answer is already "affected"
    assert not needs_arbitration([affected])


def test_without_an_arbitrator_undecided_cases_go_straight_to_advice():
    nodes, visited = recording_nodes(UNDETERMINED, arbitrate=False)
    run(nodes, {"query": "space heater"})
    assert visited == ["identify", "retrieve", "verify", "advise"]


def photo_nodes(retake=True):
    """Recording nodes whose perception can read only sharp.jpg."""
    nodes, visited = recording_nodes(AFFECTED)

    def perceive(state):
        visited.append("perceive")
        unreadable = state["photo"] != "sharp.jpg"
        return {"photo_error": "No text could be read from the photo." if unreadable else None}

    return replace(nodes, perceive=perceive, retake=agent_nodes.retake if retake else None), visited


def test_unreadable_photo_pauses_for_a_retake_and_resumes_with_the_new_photo():
    nodes, visited = photo_nodes()
    graph = build(nodes, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t"}}
    paused = graph.invoke({"query": "", "photo": "blurry.jpg"}, config)
    (question,) = paused["__interrupt__"]
    assert question.value == {"question": agent_nodes.ASK,
                              "reason": "No text could be read from the photo."}  # fmt: skip
    assert visited == ["perceive"] and "answer" not in paused
    result = graph.invoke(Command(resume={"photo": "sharp.jpg"}), config)
    assert visited == ["perceive", "perceive", "identify", "retrieve", "verify", "advise"]
    assert result["answer"] == {"verdict": AFFECTED} and result["photo_error"] is None


def test_a_description_can_replace_the_retake():
    nodes, visited = photo_nodes()
    graph = build(nodes, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t"}}
    graph.invoke({"query": "is this recalled?", "photo": "blurry.jpg"}, config)
    result = graph.invoke(Command(resume={"query": "Acme SH-100 heater"}), config)
    assert visited == ["perceive", "identify", "retrieve", "verify", "advise"]
    assert result["query"] == "is this recalled? Acme SH-100 heater" and result["photo"] is None


def test_without_a_person_an_unreadable_photo_falls_back_to_the_description():
    nodes, visited = photo_nodes(retake=False)
    run(nodes, {"query": "Acme heater", "photo": "blurry.jpg"})
    assert visited == ["perceive", "identify", "retrieve", "verify", "advise"]


def test_a_paused_check_resumes_after_a_restart_from_postgres(database_url):
    nodes, visited = photo_nodes()
    config = {"configurable": {"thread_id": "check-1"}}
    with postgres_checkpointer(database_url) as saver:
        build(nodes, checkpointer=saver).invoke({"query": "", "photo": "blurry.jpg"}, config)
    with postgres_checkpointer(database_url) as saver:  # a new connection, as after a restart
        graph = build(nodes, checkpointer=saver)
        assert graph.get_state(config).next == ("retake",)
        result = graph.invoke(Command(resume={"photo": "sharp.jpg"}), config)
    assert result["answer"] == {"verdict": AFFECTED}
    assert visited == ["perceive", "perceive", "identify", "retrieve", "verify", "advise"]
