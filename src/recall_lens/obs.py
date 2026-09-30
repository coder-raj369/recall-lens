"""Tracing: an OpenTelemetry span for every graph step.

Spans are appended as JSON lines to RECALL_LENS_TRACES (default .traces/spans.jsonl). Setting the
standard OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_EXPORTER_OTLP_HEADERS sends them to any
OpenTelemetry backend instead: for Langfuse, https://cloud.langfuse.com/api/public/otel with
Authorization=Basic <base64 of public_key:secret_key>. Until setup() runs, spans cost nothing.
"""

import os
from pathlib import Path

from langgraph.errors import GraphInterrupt
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

tracer = trace.get_tracer("recall_lens")


def setup() -> None:
    """Export spans over OTLP when an endpoint is configured, else to a local file."""
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    if isinstance(trace.get_tracer_provider(), TracerProvider):
        return  # already configured
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter()
    else:
        path = Path(os.environ.get("RECALL_LENS_TRACES", ".traces/spans.jsonl"))
        path.parent.mkdir(parents=True, exist_ok=True)
        exporter = ConsoleSpanExporter(
            out=path.open("a"), formatter=lambda span: span.to_json(indent=None) + "\n"
        )
    provider = TracerProvider(resource=Resource.create({"service.name": "recall-lens"}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def traced(name: str, node):
    """The graph node inside a span named after it, recording what it produced."""

    def run(state, config):  # LangGraph passes the run's config to a parameter of this name
        with tracer.start_as_current_span(
            f"recall_lens.{name}", record_exception=False, set_status_on_exception=False
        ) as span:
            if check := config.get("configurable", {}).get("thread_id"):
                span.set_attribute("session.id", check)  # groups a check's steps in Langfuse
            try:
                update = node(state) or {}
            except GraphInterrupt:  # a pause for the person, not a failure
                span.set_attribute("recall_lens.paused", True)
                raise
            except Exception as error:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR))
                raise
            for key, value in update.items():
                if isinstance(value, list):
                    span.set_attribute(f"recall_lens.{key}", len(value))
            if answer := update.get("answer"):
                span.set_attribute("recall_lens.verdict", answer["verdict"])
            return update

    return run
