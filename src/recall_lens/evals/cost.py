"""Estimated cost of Claude arbitration per check, from the 300 recorded end-to-end cases.

Usage: python -m recall_lens.evals.cost    (needs the `llm` group; sends nothing)

Rules-only checks make no model calls. With arbitration on, a check calls Claude once when a
candidate is left undetermined and no recall covers the unit yet, sending the prompt built here.
Tokens are estimated at four characters each, because exact counts need an API key, and output
length at high effort with adaptive thinking is a range, not a measurement.
"""

import gzip
import json
import statistics

import anthropic

from recall_lens.agents import arbitrate, nodes
from recall_lens.agents.graph import needs_arbitration
from recall_lens.agents.state import UNDETERMINED
from recall_lens.agents.verify import parse_scope
from recall_lens.evals import replay

PRICE = {"input": 4.0, "output": 20.0}  # Claude Opus 5.5, dollars per million tokens
OUTPUT_TOKENS = (1_000, 4_000)  # thinking plus the JSON answer: an assumed range
CHARS_PER_TOKEN = 4


def main() -> None:
    with gzip.open(replay.FIXTURE, "rt") as f:
        data = json.load(f)
    scopes = {key: parse_scope(*inputs) for key, inputs in data["recalls"].items()}
    schema = json.dumps(anthropic.transform_schema(arbitrate.Judgments))
    calls = []
    for case in data["cases"]:
        state = case["state"]
        chosen = [scopes[str(c["recall_id"])] for c in state["candidates"]]
        verdicts = nodes.judge(state["candidates"], chosen, nodes.facts(state))
        notices = [arbitrate.notice(s) for s, v in zip(chosen, verdicts, strict=True)
                   if v["verdict"] == UNDETERMINED]  # fmt: skip
        if needs_arbitration(verdicts):
            text = arbitrate.SYSTEM + arbitrate.prompt(state, notices) + schema
            calls.append(len(text) / CHARS_PER_TOKEN)
    share = len(calls) / len(data["cases"])
    low, high = (
        statistics.mean(calls) * PRICE["input"] / 1e6 + out * PRICE["output"] / 1e6
        for out in OUTPUT_TOKENS
    )
    print(f"Checks that would call Claude: {len(calls)}/{len(data['cases'])} ({share:.0%})")
    print(f"Input per call: {statistics.median(calls):,.0f} tokens median, "
          f"{statistics.quantiles(calls, n=20)[-1]:,.0f} p95 (estimated)")  # fmt: skip
    print(f"Cost per call: ${low:.3f} to ${high:.3f}")
    print(f"Cost per 1,000 checks: ${share * low * 1000:,.0f} to ${share * high * 1000:,.0f}")


if __name__ == "__main__":
    main()
