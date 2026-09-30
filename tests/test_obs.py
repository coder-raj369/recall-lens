"""Every graph step becomes a span that says what it produced, grouped by check."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from recall_lens.agents import nodes as agent_nodes
from recall_lens.agents.graph import Nodes, build
from recall_lens.agents.state import AFFECTED

SPANS = InMemorySpanExporter()


def setup_module():
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        trace.set_tracer_provider(TracerProvider())
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(SPANS))


def graph(perceive=lambda state: {"photo_error": None}, identify=lambda state: {}):
    nodes = Nodes(
        perceive=perceive,
        identify=identify,
        retrieve=lambda state: {"candidates": [{"source_id": "1"}, {"source_id": "2"}]},
        verify=lambda state: {"verdicts": [{"verdict": AFFECTED}]},
        advise=lambda state: {"answer": {"verdict": AFFECTED}},
        retake=agent_nodes.retake,
    )
    return build(nodes, checkpointer=InMemorySaver())


def test_each_step_is_a_span_with_what_it_produced():
    SPANS.clear()
    graph().invoke({"query": "lot 1"}, {"configurable": {"thread_id": "check-1"}})
    spans = {span.name: span for span in SPANS.get_finished_spans()}
    assert list(spans) == [f"recall_lens.{n}" for n in ("identify", "retrieve", "verify", "advise")]
    assert spans["recall_lens.retrieve"].attributes["recall_lens.candidates"] == 2
    assert spans["recall_lens.advise"].attributes["recall_lens.verdict"] == AFFECTED
    assert {span.attributes["session.id"] for span in spans.values()} == {"check-1"}


def test_failures_are_errors_but_a_pause_for_a_retake_is_not():
    SPANS.clear()
    unreadable = graph(perceive=lambda state: {"photo_error": "No text could be read."})
    config = {"configurable": {"thread_id": "check-2"}}
    unreadable.invoke({"query": "", "photo": "blurry.jpg"}, config)
    (paused,) = [s for s in SPANS.get_finished_spans() if s.name == "recall_lens.retake"]
    assert paused.attributes["recall_lens.paused"] and paused.status.status_code != StatusCode.ERROR
    unreadable.invoke(Command(resume={"query": "Acme heater"}), config)

    def broken(state):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        graph(identify=broken).invoke({"query": "x"}, {"configurable": {"thread_id": "check-3"}})
    (failed,) = [s for s in SPANS.get_finished_spans() if s.name == "recall_lens.identify"
                 and s.attributes.get("session.id") == "check-3"]  # fmt: skip
    assert failed.status.status_code == StatusCode.ERROR
