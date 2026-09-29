"""Node implementations for the recall-check graph (see agents.graph for the topology)."""

from collections.abc import Callable
from dataclasses import dataclass

import psycopg

from recall_lens.agents import verify as rules_verifier
from recall_lens.agents.state import AFFECTED, NEEDS_INFO, NO_MATCH, NOT_AFFECTED, CheckState
from recall_lens.extract import rules
from recall_lens.perception import vin
from recall_lens.perception.read import Reading, normalize
from recall_lens.retrieval import search as retrieval


def _read_photo(photo: str) -> Reading:
    from recall_lens.perception.image import load
    from recall_lens.perception.read import read

    return read(load(photo))


@dataclass
class Services:
    """What the nodes need from the outside world; tests swap these for fakes."""

    conn: psycopg.Connection | None = None
    read_photo: Callable[[str], Reading] = _read_photo
    search: Callable[..., list[retrieval.Hit]] = retrieval.search
    lookups: bool = True  # resolve barcodes (Open Food Facts) and VINs (NHTSA vPIC)
    candidates: int = 5  # recalls checked per request
    threshold: float = 0.8  # LLM verdicts below this confidence abstain; tune on the dev split


def perceive(services: Services):
    def run(state: CheckState) -> dict:
        from recall_lens.perception import release_models
        from recall_lens.perception.recalls import build_query

        reading = services.read_photo(state["photo"])
        photo_query = build_query(reading, lookups=services.lookups)
        release_models()  # retrieval loads bge-m3 next; together they overflow 8 GB
        return {
            "photo_text": normalize(reading.text),
            "photo_query": photo_query,
            "identifiers": sorted([k, v] for k, v in reading.identifiers),
            "codes": sorted(reading.codes),
        }

    return run


def identify(services: Services):
    def run(state: CheckState) -> dict:
        query = state.get("query", "")
        vins = vin.find(query)
        identifiers = {tuple(pair) for pair in state.get("identifiers", [])}
        identifiers |= rules.extract(query) | {("vin", v) for v in vins}
        search = [query, state.get("photo_query", "")]
        if services.lookups:
            for v in sorted(vins):
                vehicle = vin.decode(v)
                search.append(
                    " ".join(filter(None, [vehicle["year"], vehicle["make"], vehicle["model"]]))
                )
        return {
            "identifiers": sorted([k, v] for k, v in identifiers),
            "codes": sorted(set(state.get("codes", [])) | rules.codes(query) | vins),
            "search_text": " ".join(" ".join(filter(None, search)).split()),
            "text": "\n".join(filter(None, [query, state.get("photo_text", "")])),
        }

    return run


def retrieve(services: Services):
    def run(state: CheckState) -> dict:
        text, codes = state.get("search_text", ""), state.get("codes", [])
        if not text and not codes:
            return {"candidates": []}
        hits = services.search(services.conn, text, limit=services.candidates, extra_codes=codes)
        candidates = [
            {"recall_id": h.recall_id, "agency": h.agency, "source_id": h.source_id,
             "title": h.title, "source_url": h.source_url}
            for h in hits
        ]  # fmt: skip
        return {"candidates": candidates}

    return run


SCOPE_CHARS = 20_000  # scope wording is near the start; some FDA reports run to megabytes


def load_scope(conn: psycopg.Connection, recall_id: int) -> rules_verifier.Scope:
    title, text, affected = conn.execute(
        "SELECT title, concat_ws(E'\\n', title, left(description, %s)), raw->'affected'"
        " FROM recalls WHERE id = %s",
        (SCOPE_CHARS, recall_id),
    ).fetchone()
    identifiers = conn.execute(
        "SELECT kind, value FROM recall_identifiers WHERE recall_id = %s", (recall_id,)
    ).fetchall()
    return rules_verifier.parse_scope(title, text, identifiers, affected or ())


def facts(state: CheckState) -> rules_verifier.Facts:
    pairs = [tuple(pair) for pair in state.get("identifiers", [])]
    typed: dict[str, set[str]] = {}
    for kind, value in pairs:
        if kind != "brand":
            typed.setdefault(kind, set()).add(value)
    return rules_verifier.Facts(
        codes=frozenset(state.get("codes", [])) | {v for k, v in pairs if k != "brand"},
        typed={kind: frozenset(values) for kind, values in typed.items()},
        text=state.get("text", ""),
        brands=frozenset(v for k, v in pairs if k == "brand"),
    )


def verify(services: Services):
    def run(state: CheckState) -> dict:
        known = facts(state)
        verdicts = []
        for candidate in state.get("candidates", []):
            scope = load_scope(services.conn, candidate["recall_id"])
            verdict, reason, evidence = rules_verifier.verify(scope, known)
            verdicts.append(
                {"source_id": candidate["source_id"], "agency": candidate["agency"],
                 "verdict": verdict, "reason": reason, "evidence": evidence, "method": "rules",
                 "confidence": None}
            )  # fmt: skip
        return {"verdicts": verdicts}

    return run


# A missed recall is the costliest error, so any sign of one outranks a clean result.
PRIORITY = (AFFECTED, NEEDS_INFO, NOT_AFFECTED)
HEADLINES = {
    AFFECTED: "Your product is covered by a recall.",
    NEEDS_INFO: "A recall may cover your product; one more detail would settle it.",
    NOT_AFFECTED: "A recall covers this product, but not your unit.",
    NO_MATCH: "No recall we found matches your product.",
}


def decide(candidates: list, verdicts: list, threshold: float) -> tuple[str, list[dict]]:
    """The final verdict and the recalls behind it, in search rank (ADR-0003).

    LLM verdicts below the confidence threshold become requests for more information.
    """
    cited = []
    for candidate, v in zip(candidates, verdicts, strict=True):
        if v["confidence"] is not None and v["confidence"] < threshold:
            reason = f"Not sure enough to decide ({v['confidence']:.0%}). {v['reason']}"
            v = {**v, "verdict": NEEDS_INFO, "reason": reason}
        cited.append({**candidate, **v})
    for verdict in PRIORITY:
        if recalls := [c for c in cited if c["verdict"] == verdict]:
            return verdict, recalls
    return NO_MATCH, []


def advise(services: Services):
    def run(state: CheckState) -> dict:
        candidates = state.get("candidates", [])
        verdict, recalls = decide(candidates, state.get("verdicts", []), services.threshold)
        lines = [HEADLINES[verdict]]
        if recalls:
            top = recalls[0]
            lines += [f"{top['agency'].upper()} recall {top['source_id']}: {top['title']}"]
            lines += [top["reason"], top["evidence"] and f'The notice says: "{top["evidence"]}"']
            if verdict == AFFECTED:
                hazard, remedy = services.conn.execute(
                    "SELECT hazard, remedy FROM recalls WHERE id = %s", (top["recall_id"],)
                ).fetchone()
                lines += [hazard and f"Hazard: {hazard}", remedy and f"Remedy: {remedy}"]
            lines += [top["source_url"]]
        if candidates and verdict in (NOT_AFFECTED, NO_MATCH):
            n = len(candidates)
            closest = f"the {n} closest recalls" if n > 1 else "the closest recall"
            lines += [f"Compared with {closest}; others are not ruled out."]
        message = "\n".join(filter(None, lines))
        return {"answer": {"verdict": verdict, "message": message, "recalls": recalls}}

    return run
