"""Watchlist: products re-checked after each ingestion, with an email when a recall covers one.

    python -m recall_lens.watch        # re-check every watched product and send the alerts

A watched product keeps what its check read (text, identifiers, codes), never the photo. Alerts
go out by SMTP (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM), and only to the
addresses in RECALL_LENS_ALERT_RECIPIENTS: an open form must not be able to email strangers.
Each email links to RECALL_LENS_URL, where its product can be removed.
"""

import logging
import os
import secrets
import smtplib
import sys
from collections.abc import Callable
from email.message import EmailMessage
from textwrap import shorten

import psycopg
from psycopg.types.json import Jsonb

from recall_lens.agents import nodes
from recall_lens.agents.state import AFFECTED

log = logging.getLogger(__name__)
KEPT = ("search_text", "text", "identifiers", "codes")  # what a re-check needs from the check
MAX_ITEMS = 50  # per address
FOOTER = (
    "RecallLens is an engineering project, not an official source. "
    "Confirm recalls with the agency or the manufacturer."
)


def recipients() -> set[str]:
    """Addresses that may be emailed; none unless configured."""
    listed = os.environ.get("RECALL_LENS_ALERT_RECIPIENTS", "").lower().split(",")
    return {address.strip() for address in listed} - {""}


def add(conn: psycopg.Connection, state: dict, email: str) -> str | None:
    """Watch the product of a finished check. Returns the token that shows and removes it,
    or None when the address already watches MAX_ITEMS products."""
    token = secrets.token_urlsafe(24)
    with conn.transaction():
        watched = conn.execute("SELECT count(*) FROM watch_items WHERE email = %s", (email,))
        if watched.fetchone()[0] >= MAX_ITEMS:
            return None
        item_id = conn.execute(
            "INSERT INTO watch_items (token, email, state) VALUES (%s, %s, %s) RETURNING id",
            (token, email, Jsonb({key: state.get(key) for key in KEPT})),
        ).fetchone()[0]
        answer = state["answer"]
        if answer["verdict"] == AFFECTED:  # recalls the person was just shown are not news
            conn.execute(
                "INSERT INTO watch_alerts (item_id, recall_id) SELECT %s, unnest(%s::bigint[])",
                (item_id, [recall["recall_id"] for recall in answer["recalls"]]),
            )
    return token


def product(conn: psycopg.Connection, token: str) -> str | None:
    """How the watched product was described, or None for an unknown token."""
    row = conn.execute(
        "SELECT left(state->>'text', 200) FROM watch_items WHERE token = %s", (token,)
    ).fetchone()
    return row and row[0]


def remove(conn: psycopg.Connection, token: str) -> bool:
    return conn.execute("DELETE FROM watch_items WHERE token = %s", (token,)).rowcount > 0


def send(to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = os.environ["SMTP_FROM"], to, subject
    message.set_content(body)
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)


def alert(conn: psycopg.Connection, services: nodes.Services, send: Callable = send) -> int:
    """Re-check every watched product and email each recall that newly covers one.

    Returns how many products could not be checked or emailed; those are retried next run,
    because a recall is recorded as told only after its email went out.
    """
    retrieve, verify, advise = (
        nodes.retrieve(services),
        nodes.verify(services),
        nodes.advise(services),
    )
    url = os.environ.get("RECALL_LENS_URL", "http://localhost:8000")
    allowed, failed = recipients(), 0
    items = conn.execute("SELECT id, token, email, state FROM watch_items ORDER BY id").fetchall()
    for item_id, token, email, state in items:
        if email not in allowed:
            continue  # approved when it was added, not any more
        try:
            state |= retrieve(state)
            state |= verify(state)
            told = {
                recall_id
                for (recall_id,) in conn.execute(
                    "SELECT recall_id FROM watch_alerts WHERE item_id = %s", (item_id,)
                )
            }
            while True:  # one email per recall, so each cites its own notice
                pairs = zip(state["candidates"], state["verdicts"], strict=True)
                news = [(c, v) for c, v in pairs if c["recall_id"] not in told]
                rest = {"candidates": [c for c, _ in news], "verdicts": [v for _, v in news]}
                answer = advise({**state, **rest})["answer"]
                if answer["verdict"] != AFFECTED:
                    break
                recall = answer["recalls"][0]
                body = (
                    f"You asked RecallLens to watch: {shorten(state['text'], 200)}\n\n"
                    f"{answer['message']}\n\n"
                    f"Stop watching this product: {url}/?stop={token}\n\n{FOOTER}\n"
                )
                send(email, f"Recall alert: {shorten(recall['title'], 90)}", body)
                conn.execute(
                    "INSERT INTO watch_alerts (item_id, recall_id) VALUES (%s, %s)",
                    (item_id, recall["recall_id"]),
                )
                conn.commit()
                told.add(recall["recall_id"])
        except Exception:  # one product failing must not silence the alerts of the others
            log.exception("watched product %s could not be checked or emailed", item_id)
            conn.rollback()
            failed += 1
    return failed


def main() -> int:
    for name in ("DATABASE_URL", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
        if not os.environ.get(name):
            sys.exit(f"{name} is not set")
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        failed = alert(conn, nodes.Services(conn=conn))
    return 1 if failed else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
