"""HTTP API: run recall checks and stream their progress as server-sent events.

    POST /checks                   {"query": "...", "photo": "<base64 image>"}
    POST /checks/{id}/resume       the same fields, answering a paused check's question
    POST /checks/{id}/watch        {"email": "..."}: email when a recall covers this product
    GET, DELETE /watches/{token}   show or remove a watched product (recall_lens.watch)
    GET  /                         the web client (recall_lens/web), an installable page

Each response is an event stream: `check` (the check id), one `progress` per graph step, then
`question` (the check paused, e.g. for a retake), `answer` or `error`. Photos are written to
private temporary files and deleted when the request ends; they are never stored.

Run with `uvicorn recall_lens.api:app`. Claude arbitration stays off unless
RECALL_LENS_ARBITRATE=1, because every call is billed.
"""

import logging
import os
import tempfile
import threading
import uuid
from collections.abc import Iterator
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command
from pydantic import Base64Bytes, BaseModel, Field

from recall_lens import obs, watch
from recall_lens.agents import nodes
from recall_lens.agents.graph import Nodes, build, postgres_checkpointer

log = logging.getLogger(__name__)
WEB = Path(__file__).parent / "web"


class CheckInput(BaseModel):
    query: str = Field("", max_length=2_000)
    photo: Annotated[Base64Bytes, Field(max_length=10_000_000)] | None = None


class WatchInput(BaseModel):
    email: str = Field(max_length=254)


def arbitrator(services: nodes.Services):
    """Claude arbitration, only when RECALL_LENS_ARBITRATE=1."""
    if os.environ.get("RECALL_LENS_ARBITRATE") != "1":
        return None
    import anthropic

    from recall_lens.agents.arbitrate import arbitrate

    return arbitrate(services, anthropic.Anthropic())


class ThreadConnections:
    """One database connection per worker thread, opened on first use.

    Concurrent checks cannot share a connection: retrieval runs its own transactions to tune the
    vector index per query, and interleaved they fail. Behaves like the thread's connection.
    """

    def __init__(self, url: str):
        self.url, self.local, self.opened = url, threading.local(), []

    def __getattr__(self, name: str):
        if not hasattr(self.local, "conn"):
            self.local.conn = psycopg.connect(self.url, autocommit=True)
            self.opened.append(self.local.conn)
        return getattr(self.local.conn, name)

    def close(self) -> None:
        for conn in self.opened:
            conn.close()


def default_graph(stack: ExitStack) -> tuple:
    """The production graph on DATABASE_URL, with checkpoints so paused checks can resume,
    and the database connections it runs on."""
    url = os.environ["DATABASE_URL"]
    obs.setup()
    connections = ThreadConnections(url)
    stack.callback(connections.close)
    services = nodes.Services(conn=connections)
    graph_nodes = Nodes(
        perceive=nodes.perceive(services),
        identify=nodes.identify(services),
        retrieve=nodes.retrieve(services),
        verify=nodes.verify(services),
        advise=nodes.advise(services),
        arbitrate=arbitrator(services),
        retake=nodes.retake,
    )
    graph = build(graph_nodes, checkpointer=stack.enter_context(postgres_checkpointer(url)))
    return graph, connections


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


def create_app(graph=None, db=None) -> FastAPI:
    """The API around `graph` and the database `db`, or around the production ones when no
    graph is given."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with ExitStack() as stack:
            app.state.graph, app.state.db = (graph, db) if graph else default_graph(stack)
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

    @app.post("/checks/{check_id}/watch", status_code=201)
    def watch_product(check_id: str, body: WatchInput) -> dict:
        state = app.state.graph.get_state(_config(check_id)).values
        if "answer" not in state:
            raise HTTPException(404, "No finished check with this id.")
        if not (state.get("search_text") or state.get("codes")):
            raise HTTPException(409, "This check read nothing that could be watched.")
        email = body.email.strip().lower()
        if email not in watch.recipients():
            raise HTTPException(403, "In this demo, alerts go only to approved addresses.")
        token = watch.add(app.state.db, state, email)
        if token is None:
            raise HTTPException(429, "This address already watches as many products as it may.")
        return {"token": token}

    @app.get("/watches/{token}")
    def watched(token: str) -> dict:
        product = watch.product(app.state.db, token)
        if product is None:
            raise HTTPException(404, "Nothing is watched under this link.")
        return {"product": product}

    @app.delete("/watches/{token}", status_code=204)
    def stop_watching(token: str) -> None:
        if not watch.remove(app.state.db, token):
            raise HTTPException(404, "Nothing is watched under this link.")

    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")  # after the API routes
    return app


app = create_app()
