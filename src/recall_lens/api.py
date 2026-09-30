"""HTTP API: run recall checks and stream their progress as server-sent events.

    POST /checks                   {"query": "...", "photo": "<base64 image>"}
    POST /checks/{id}/resume       the same fields, answering a paused check's question

Each response is an event stream: `check` (the check id), one `progress` per graph step, then
`question` (the check paused, e.g. for a retake), `answer` or `error`. Photos are written to
private temporary files and deleted when the request ends; they are never stored.

Run with `uvicorn recall_lens.api:app`. Claude arbitration stays off unless
RECALL_LENS_ARBITRATE=1, because every call is billed.
"""

import logging
import os
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langgraph.types import Command
from pydantic import Base64Bytes, BaseModel, Field

from recall_lens import obs
from recall_lens.agents import nodes
from recall_lens.agents.graph import Nodes, build, postgres_checkpointer

log = logging.getLogger(__name__)


class CheckInput(BaseModel):
    query: str = Field("", max_length=2_000)
    photo: Annotated[Base64Bytes, Field(max_length=10_000_000)] | None = None


def arbitrator(services: nodes.Services):
    """Claude arbitration, only when RECALL_LENS_ARBITRATE=1."""
    if os.environ.get("RECALL_LENS_ARBITRATE") != "1":
        return None
    import anthropic

    from recall_lens.agents.arbitrate import arbitrate

    return arbitrate(services, anthropic.Anthropic())


def default_graph(stack: ExitStack):
    """The production graph on DATABASE_URL, with checkpoints so paused checks can resume."""
    url = os.environ["DATABASE_URL"]
    obs.setup()
    # ponytail: one connection shared by all requests; pool it once checks run in parallel.
    services = nodes.Services(conn=stack.enter_context(psycopg.connect(url, autocommit=True)))
    graph_nodes = Nodes(
        perceive=nodes.perceive(services),
        identify=nodes.identify(services),
        retrieve=nodes.retrieve(services),
        verify=nodes.verify(services),
        advise=nodes.advise(services),
        arbitrate=arbitrator(services),
        retake=nodes.retake,
    )
    return build(graph_nodes, checkpointer=stack.enter_context(postgres_checkpointer(url)))


def _config(check_id: str) -> dict:
    return {"configurable": {"thread_id": check_id}}


def _save(photo: bytes | None) -> str | None:
    if not photo:
        return None
    fd, path = tempfile.mkstemp(prefix="recall-lens-")  # readable by this user only
    with os.fdopen(fd, "wb") as file:
        file.write(photo)
    return path


def _stream(graph, payload, check_id: str, photo: str | None) -> Iterator[ServerSentEvent]:
    config = _config(check_id)
    try:
        yield ServerSentEvent(event="check", data={"id": check_id})
        for step in graph.stream(payload, config, stream_mode="updates"):
            for node, update in step.items():
                if node == "__interrupt__":
                    yield ServerSentEvent(event="question", data=update[0].value)
                else:
                    yield ServerSentEvent(event="progress", data={"node": node, "update": update})
        state = graph.get_state(config)
        if not state.next:
            yield ServerSentEvent(event="answer", data=state.values["answer"])
    except Exception:
        log.exception("check %s failed", check_id)
        yield ServerSentEvent(event="error", data={"message": "The check failed; please retry."})
    finally:
        if photo:
            Path(photo).unlink(missing_ok=True)


def paused_check(check_id: str, request: Request) -> str:
    state = request.app.state.graph.get_state(_config(check_id))
    if not state.values:
        raise HTTPException(404, "No such check.")
    if not state.interrupts:
        raise HTTPException(409, "This check is not waiting for an answer.")
    return check_id


def create_app(graph=None) -> FastAPI:
    """The API around `graph`, or around the production graph when none is given."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with ExitStack() as stack:
            app.state.graph = graph if graph is not None else default_graph(stack)
            yield

    app = FastAPI(title="RecallLens", lifespan=lifespan)

    @app.post("/checks", response_class=EventSourceResponse)
    def start(body: CheckInput) -> Iterator[ServerSentEvent]:
        photo = _save(body.photo)
        payload = {"query": body.query, "photo": photo}
        yield from _stream(app.state.graph, payload, str(uuid.uuid4()), photo)

    @app.post("/checks/{check_id}/resume", response_class=EventSourceResponse)
    def resume(
        body: CheckInput, check_id: Annotated[str, Depends(paused_check)]
    ) -> Iterator[ServerSentEvent]:
        photo = _save(body.photo)
        answer = Command(resume={"photo": photo, "query": body.query})
        yield from _stream(app.state.graph, answer, check_id, photo)

    return app


app = create_app()
