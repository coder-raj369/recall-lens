"""The evaluation gate: replay verification on recorded candidates for all 300 end-to-end cases.

    python -m recall_lens.evals.replay record    # needs the corpus database, bge-m3, cached photos
    python -m recall_lens.evals.replay check     # needs nothing: fails if the rules got worse
    python -m recall_lens.evals.replay update    # accept the current results as the baseline

record runs perception, identification and retrieval for every case and saves what verification
sees: the person's facts, the candidate recalls and each candidate's scope inputs. check replays
verification and the final decision on that fixture, exactly as the graph runs them, so it
measures the rules and advice code in seconds without a database or models; retrieval has its
own evaluation. It fails when a split has more missed recalls or unsafe answers, or fewer right
answers, than the committed baseline.
"""

import argparse
import gzip
import json
import os
import sys

from recall_lens.agents import nodes
from recall_lens.agents.verify import parse_scope
from recall_lens.evals import e2e

FIXTURES = e2e.DATASETS.parent / "fixtures"
FIXTURE = FIXTURES / "e2e_replay.json.gz"
BASELINE = FIXTURES / "e2e_gate.json"
SPLITS = ("dev", "test", "holdout")
STATE = ("text", "identifiers", "codes", "photo_error", "candidates")


def record() -> None:
    import psycopg

    cases, recalls = [], {}
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        services = nodes.Services(conn=conn, read_photo=e2e.photo_reader())
        steps = [nodes.identify(services), nodes.retrieve(services)]
        for split in SPLITS:
            for case in e2e.load_split(split):
                state = {"query": case["query"], "photo": case["photo"]}
                if case["photo"]:
                    state |= nodes.perceive(services)(state)
                for step in steps:
                    state |= step(state)
                for c in state["candidates"]:
                    key = str(c["recall_id"])
                    recalls.setdefault(key, nodes.scope_inputs(conn, c["recall_id"]))
                cases.append({"split": split, **case, "state": {k: state.get(k) for k in STATE}})
    FIXTURES.mkdir(exist_ok=True)
    with gzip.open(FIXTURE, "wt") as f:
        json.dump({"cases": cases, "recalls": recalls}, f)


def replay() -> tuple[dict[str, list[dict]], dict[str, dict]]:
    """Each split's answers from verification and decision alone, and the cases by id."""
    with gzip.open(FIXTURE, "rt") as f:
        data = json.load(f)
    scopes = {key: parse_scope(*inputs) for key, inputs in data["recalls"].items()}
    results: dict[str, list[dict]] = {split: [] for split in SPLITS}
    for case in data["cases"]:
        state = case["state"]
        candidates = state["candidates"]
        chosen = [scopes[str(c["recall_id"])] for c in candidates]
        verdicts = nodes.judge(candidates, chosen, nodes.facts(state))
        verdict, recalls = nodes.decide(
            candidates, verdicts, nodes.Services.threshold, state["photo_error"]
        )
        top = recalls[0] if recalls else None
        results[case["split"]].append(
            {"id": case["id"], "type": case["type"], "expected": case["expected"],
             "predicted": verdict, "cited": top and f"{top['agency']}:{top['source_id']}",
             "seconds": 0.0}
        )  # fmt: skip
    return results, {case["id"]: case for case in data["cases"]}


def counts(rows: list[dict]) -> dict[str, int]:
    def cls(value):
        return e2e.CLASS[value]

    return {
        "cases": len(rows),
        "right": sum(cls(r["predicted"]) == cls(r["expected"]) for r in rows),
        "missed": sum(r["expected"] == "affected" and cls(r["predicted"]) == e2e.NEGATIVE
                      for r in rows),
        "unsafe": sum(cls(r["expected"]) != e2e.NEGATIVE and cls(r["predicted"]) == e2e.NEGATIVE
                      for r in rows),
    }  # fmt: skip


def current() -> dict[str, dict[str, int]]:
    results, _ = replay()
    return {split: counts(rows) for split, rows in results.items()}


def regressions(now: dict[str, dict[str, int]], base: dict[str, dict[str, int]]) -> list[str]:
    """Splits with more missed recalls or unsafe answers, or fewer right answers."""
    worse = [
        f"{split}: {key} {base[split][key]} -> {now[split][key]}"
        for split in SPLITS
        for key in ("missed", "unsafe")
        if now[split][key] > base[split][key]
    ]
    return worse + [
        f"{split}: right answers {base[split]['right']} -> {now[split]['right']}"
        for split in SPLITS
        if now[split]["right"] < base[split]["right"]
    ]


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m recall_lens.evals.replay")
    parser.add_argument("command", choices=["record", "check", "update"])
    command = parser.parse_args().command
    if command == "record":
        record()
        return 0
    now = current()
    if command == "update":
        BASELINE.write_text(json.dumps(now, indent=2) + "\n")
    worse = regressions(now, json.loads(BASELINE.read_text()))
    for split, c in now.items():
        print(f"{split}: {c['right']}/{c['cases']} right, {c['missed']} missed recalls, "
              f"{c['unsafe']} unsafe answers")  # fmt: skip
    print("\n".join(worse) or "No regressions.")
    return 1 if worse else 0


if __name__ == "__main__":
    sys.exit(main())
