"""Graph topology for a recall check.

    START -> [perceive <-> retake] -> identify -> retrieve -> verify -> [arbitrate] -> advise -> END

perceive runs only when a photo is given. retake runs when the photo was unusable and someone can
answer: it interrupts the graph until a new photo or a description arrives, so it needs a
checkpointer. arbitrate runs only when an arbitrator is configured and the rules left a candidate
undetermined (ADR-0003). Nodes are plain functions taking the state and returning a partial
update, injected so the topology can be tested on its own.
"""

from collections.abc import Callable
from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph

from recall_lens.agents.state import UNDETERMINED, CheckState

Node = Callable[[CheckState], dict]


@dataclass(frozen=True)
class Nodes:
    perceive: Node
    identify: Node
    retrieve: Node
    verify: Node
    advise: Node
    arbitrate: Node | None = None  # an LLM step; absent unless explicitly enabled
    retake: Node | None = None  # a human step; absent in batch runs such as evaluations


def build(nodes: Nodes, checkpointer=None):
    graph = StateGraph(CheckState)
    graph.add_node("perceive", nodes.perceive)
    graph.add_node("identify", nodes.identify)
    graph.add_node("retrieve", nodes.retrieve)
    graph.add_node("verify", nodes.verify)
    graph.add_node("advise", nodes.advise)
    if nodes.arbitrate:
        graph.add_node("arbitrate", nodes.arbitrate)
        graph.add_edge("arbitrate", "advise")
    if nodes.retake:
        graph.add_node("retake", nodes.retake)

    def start(state: CheckState) -> str:
        return "perceive" if state.get("photo") else "identify"

    def after_perceive(state: CheckState) -> str:
        return "retake" if nodes.retake and state.get("photo_error") else "identify"

    def after_retake(state: CheckState) -> str:
        return "perceive" if state.get("photo") else "identify"

    def after_verify(state: CheckState) -> str:
        undecided = any(v["verdict"] == UNDETERMINED for v in state.get("verdicts", []))
        return "arbitrate" if nodes.arbitrate and undecided else "advise"

    graph.add_conditional_edges(START, start, ["perceive", "identify"])
    if nodes.retake:
        graph.add_conditional_edges("perceive", after_perceive, ["retake", "identify"])
        graph.add_conditional_edges("retake", after_retake, ["perceive", "identify"])
    else:
        graph.add_edge("perceive", "identify")
    graph.add_edge("identify", "retrieve")
    graph.add_edge("retrieve", "verify")
    targets = ["advise", "arbitrate"] if nodes.arbitrate else ["advise"]
    graph.add_conditional_edges("verify", after_verify, targets)
    graph.add_edge("advise", END)
    return graph.compile(checkpointer=checkpointer)
