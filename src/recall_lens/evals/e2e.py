"""End-to-end evaluation: final answers against the gold set, for the graph and its baselines.

Usage: python -m recall_lens.evals.e2e [--split dev|test] [--arms graph search_only ...] [--dump F]

Every arm runs the same graph (perception, identification, retrieval and advice) and differs only
in how candidates are verified, so the comparison isolates verification:

- graph: the production rules (ADR-0003), no LLM.
- search_only: every retrieved recall counts as a match, the plain retrieval-augmented answer.
- exact_match: a recall matches only when it lists a code the person gave; no scope reasoning.
- graph_claude: the rules plus Claude arbitration of undetermined candidates.
- single_agent: Claude alone with a search tool, no graph or rules (ADR-0002).

The two Claude arms are billed per call, so they run only with RECALL_LENS_ARBITRATE=1 and the
`llm` dependency group. Photos reuse the readings cached by `python -m recall_lens.evals.photos`,
so no vision model is loaded when the cache is present.
"""

import argparse
import json
import os
import statistics
import time
from pathlib import Path

import psycopg

from recall_lens.agents import nodes
from recall_lens.agents.graph import Nodes, build
from recall_lens.agents.state import (
    AFFECTED,
    NEEDS_INFO,
    NO_MATCH,
    NOT_AFFECTED,
    UNDETERMINED,
    CheckState,
)

DATASETS = Path(__file__).resolve().parents[3] / "evals" / "datasets"
ARMS = {
    "graph": "graph (rules)",
    "search_only": "search only",
    "exact_match": "exact code match",
    "graph_claude": "graph + Claude arbitration",
    "single_agent": "single agent (Claude)",
}
CLAUDE_ARMS = ("graph_claude", "single_agent")
# Outcome classes: what the person is told to do.
POSITIVE, NEGATIVE, ABSTAIN = "recalled", "not recalled", "ask"
CLASS = {
    AFFECTED: POSITIVE,
    NOT_AFFECTED: NEGATIVE,
    NO_MATCH: NEGATIVE,
    "no_recall": NEGATIVE,
    NEEDS_INFO: ABSTAIN,
}


def load_split(split: str) -> list[dict]:
    path = DATASETS / f"e2e_{split}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def photo_reader():
    """Read photos by photo-set id: cached Phase 3 readings when present, else the models."""
    from recall_lens.evals import photos  # needs the ml group

    records, cached = {}, {}
    for split in ("dev", "test"):
        split_records = photos.load_split(split)
        records |= {r["id"]: r for r in split_records}
        path = photos.CACHE.parent / f"readings_{split}.json"
        if path.exists():
            saved = json.loads(path.read_text())["readings"]["whole photo + regions"]
            cached |= {
                r["id"]: photos._reading(s) for r, s in zip(split_records, saved, strict=True)
            }

    def read_photo(photo_id: str):
        if photo_id in cached:
            return cached[photo_id]
        from recall_lens.perception.read import read

        return read(photos.photo(records[photo_id]))

    return read_photo


def _verdicts(state: CheckState, decide) -> dict:
    return {
        "verdicts": [
            {"source_id": c["source_id"], "agency": c["agency"], "verdict": decide(c),
             "reason": "", "evidence": None, "method": "baseline", "confidence": None}
            for c in state.get("candidates", [])
        ]
    }  # fmt: skip


def search_only(services: nodes.Services):
    """Baseline verify node: whatever search returns is a match."""
    return lambda state: _verdicts(state, lambda candidate: AFFECTED)


def exact_match(services: nodes.Services):
    """Baseline verify node: a match only when the recall lists a code the person gave."""

    def run(state: CheckState) -> dict:
        given = {nodes.rules_verifier._key(c) for c in nodes.facts(state).codes}

        def decide(candidate):
            listed = services.conn.execute(
                "SELECT value FROM recall_identifiers WHERE recall_id = %s AND kind <> 'brand'",
                (candidate["recall_id"],),
            ).fetchall()
            hit = given & {nodes.rules_verifier._key(value) for (value,) in listed}
            return AFFECTED if hit else UNDETERMINED

        return _verdicts(state, decide)

    return run


def graphs(services: nodes.Services, arms: list[str]) -> dict:
    """One compiled graph per graph-shaped arm, sharing every node but verification."""
    shared = dict(
        perceive=nodes.perceive(services),
        identify=nodes.identify(services),
        retrieve=nodes.retrieve(services),
        advise=nodes.advise(services),
    )
    verifiers = {"graph": nodes.verify, "search_only": search_only, "exact_match": exact_match}
    built = {
        arm: build(Nodes(verify=verifiers[arm](services), **shared))
        for arm in arms
        if arm in verifiers
    }
    if "graph_claude" in arms:
        import anthropic

        from recall_lens.agents.arbitrate import arbitrate

        arbitrator = arbitrate(services, anthropic.Anthropic())
        built["graph_claude"] = build(
            Nodes(verify=nodes.verify(services), arbitrate=arbitrator, **shared)
        )
    return built


def run_case(graph, case: dict) -> dict:
    start = time.perf_counter()
    state = graph.invoke({"query": case["query"], "photo": case["photo"]})
    answer = state["answer"]
    top = answer["recalls"][0] if answer["recalls"] else None
    return {
        "id": case["id"],
        "type": case["type"],
        "expected": case["expected"],
        "predicted": answer["verdict"],
        "cited": top and f"{top['agency']}:{top['source_id']}",
        "reason": top and top["reason"],
        "seconds": time.perf_counter() - start,
    }


def run_single_agent(services: nodes.Services, case: dict, client) -> dict:
    """Claude alone, given the same perception and identification as the graph."""
    from recall_lens.agents import single

    start = time.perf_counter()
    state = {"query": case["query"], "photo": case["photo"]}
    if case["photo"]:
        state |= nodes.perceive(services)(state)
    state |= nodes.identify(services)(state)
    verdict, cited, reason = single.check(client, services.conn, state["text"])
    return {
        "id": case["id"],
        "type": case["type"],
        "expected": case["expected"],
        "predicted": verdict,
        "cited": cited,
        "reason": reason,
        "seconds": time.perf_counter() - start,
    }


def _rate(hits: int, n: int) -> float | None:
    return hits / n if n else None


def metrics(results: list[dict], cases: dict[str, dict]) -> dict:
    def got(r):
        return CLASS[r["predicted"]]

    def want(r):
        return CLASS[r["expected"]]

    affected = [r for r in results if r["expected"] == "affected"]
    risky = [r for r in results if want(r) != NEGATIVE]
    safe = [r for r in results if want(r) == NEGATIVE]
    found = [r for r in affected if got(r) == POSITIVE]
    target = sum(r["cited"] == cases[r["id"]]["target"] for r in found)
    seconds = [r["seconds"] for r in results]
    return {
        "n": len(results),
        "accuracy": _rate(sum(got(r) == want(r) for r in results), len(results)),
        "false_negative": _rate(sum(got(r) == NEGATIVE for r in affected), len(affected)),
        "unsafe": _rate(sum(got(r) == NEGATIVE for r in risky), len(risky)),
        "false_alarm": _rate(sum(got(r) == POSITIVE for r in safe), len(safe)),
        "abstention": _rate(sum(got(r) == ABSTAIN for r in results), len(results)),
        "cited": _rate(sum(r["cited"] in cases[r["id"]]["relevant"] for r in found), len(found)),
        "cited_strict": _rate(target, len(found)),
        "p50": statistics.median(seconds),
        "p95": statistics.quantiles(seconds, n=20)[-1] if len(seconds) > 1 else seconds[0],
    }  # fmt: skip


def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value:.0%}"


def report(split: str, cases: list[dict], results: dict[str, list[dict]], skipped: list[str]):
    by_id = {c["id"]: c for c in cases}
    lines = [
        f"### End to end, {split} split ({len(cases)} cases)",
        "",
        "| Arm | Accuracy | False negatives | Unsafe answers | False alarms | Abstentions"
        " | Right recall cited | p50 s | p95 s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, rows in results.items():
        m = metrics(rows, by_id)
        cited = f"{_pct(m['cited'])} ({_pct(m['cited_strict'])} strict)"
        lines.append(
            f"| {ARMS[arm]} | {_pct(m['accuracy'])} | {_pct(m['false_negative'])}"
            f" | {_pct(m['unsafe'])} | {_pct(m['false_alarm'])} | {_pct(m['abstention'])}"
            f" | {cited} | {m['p50']:.1f} | {m['p95']:.1f} |"
        )
    for arm in skipped:
        lines.append(f"| {ARMS[arm]} | not run (billed; $0 budget) |||||||| ")
    types = list(dict.fromkeys(c["type"] for c in cases))
    lines += ["", "Accuracy by case type:", ""]
    lines.append("| Type | Expected | " + " | ".join(ARMS[a] for a in results) + " |")
    lines.append("|---|---" + "|---" * len(results) + "|")
    for kind in types:
        of_type = [c for c in cases if c["type"] == kind]
        expected = "/".join(sorted({c["expected"] for c in of_type}))
        cells = [
            _pct(metrics([r for r in rows if r["type"] == kind], by_id)["accuracy"])
            for rows in results.values()
        ]
        lines.append(f"| {kind} ({len(of_type)}) | {expected} | " + " | ".join(cells) + " |")
    if "graph" in results:
        outcomes = [AFFECTED, NOT_AFFECTED, NO_MATCH, NEEDS_INFO]
        lines += ["", "Graph answers by expected outcome:", ""]
        lines.append("| Expected | " + " | ".join(outcomes) + " |")
        lines.append("|---" * (len(outcomes) + 1) + "|")
        for expected in ("affected", "not_affected", "needs_info", "no_recall"):
            rows = [r for r in results["graph"] if r["expected"] == expected]
            counts = [str(sum(r["predicted"] == o for r in rows)) for o in outcomes]
            lines.append(f"| {expected} ({len(rows)}) | " + " | ".join(counts) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m recall_lens.evals.e2e")
    parser.add_argument("--split", choices=["dev", "test"], default="test")
    parser.add_argument("--arms", nargs="+", choices=list(ARMS), default=list(ARMS))
    parser.add_argument("--dump", type=Path, help="write per-case answers as JSON lines")
    args = parser.parse_args()
    cases = load_split(args.split)
    enabled = os.environ.get("RECALL_LENS_ARBITRATE") == "1"
    skipped = [arm for arm in args.arms if arm in CLAUDE_ARMS and not enabled]
    arms = [arm for arm in args.arms if arm not in skipped]

    results: dict[str, list[dict]] = {}
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        services = nodes.Services(conn=conn, read_photo=photo_reader())
        built = graphs(services, arms)
        client = None
        if "single_agent" in arms:
            import anthropic

            client = anthropic.Anthropic()
        for arm in arms:
            if arm == "single_agent":
                results[arm] = [run_single_agent(services, case, client) for case in cases]
            else:
                results[arm] = [run_case(built[arm], case) for case in cases]
    if args.dump:
        rows = [{"arm": arm, **row} for arm, arm_rows in results.items() for row in arm_rows]
        args.dump.write_text("".join(json.dumps(row) + "\n" for row in rows))
    print(report(args.split, cases, results, skipped))


if __name__ == "__main__":
    main()
