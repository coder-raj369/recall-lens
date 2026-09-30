"""Load test for the running API: checks per second and latency percentiles.

Usage: python -m recall_lens.evals.load [--url http://127.0.0.1:8000] [--concurrency 1 4 8]
                                       [--checks 60] [--traces .traces/spans.jsonl]

Sends the text queries of the end-to-end sets (photo reading is measured separately, in Phase 3)
to POST /checks, reading each event stream to its answer. For every concurrency level it reports
checks per second and p50/p95 time to the first event and to the answer, then the time spent in
each graph step, taken from the API's local trace spans.
"""

import argparse
import itertools
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import httpx

from recall_lens.evals import e2e


def check(client: httpx.Client, query: str) -> tuple[float, float, bool]:
    """(seconds to the first event, seconds to the answer, whether an answer came)."""
    start, first, event, answered = time.perf_counter(), None, "", False
    with client.stream("POST", "/checks", json={"query": query}) as response:
        for line in response.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
                first = first or time.perf_counter() - start
            answered = answered or event == "answer"
    return first or 0.0, time.perf_counter() - start, answered


def percentiles(values: list[float]) -> str:
    p95 = statistics.quantiles(values, n=20)[-1] if len(values) > 1 else values[0]
    return f"{statistics.median(values):.2f} / {p95:.2f}"


def step_times(path: Path, since: float) -> dict[str, list[float]]:
    steps: dict[str, list[float]] = {}
    for line in path.read_text().splitlines() if path.exists() else []:
        span = json.loads(line)
        start = datetime.fromisoformat(span["start_time"]).timestamp()
        if start >= since and span["name"].startswith("recall_lens."):
            end = datetime.fromisoformat(span["end_time"]).timestamp()
            steps.setdefault(span["name"].removeprefix("recall_lens."), []).append(end - start)
    return steps


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m recall_lens.evals.load")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 4, 8])
    parser.add_argument("--checks", type=int, default=60, help="checks per concurrency level")
    parser.add_argument("--traces", type=Path, default=Path(".traces/spans.jsonl"))
    args = parser.parse_args()
    queries = [c["query"] for s in ("dev", "test", "holdout") for c in e2e.load_split(s)
               if c["query"] and not c["photo"]]  # fmt: skip
    began = time.time()
    print("| Concurrency | Checks/s | First event p50 / p95 s | Answer p50 / p95 s | Errors |")
    print("|---|---|---|---|---|")
    with httpx.Client(base_url=args.url, timeout=300) as client:
        check(client, queries[0])  # load the embedding model before measuring
        for level in args.concurrency:
            batch = list(itertools.islice(itertools.cycle(queries), args.checks))
            start = time.perf_counter()
            with ThreadPoolExecutor(level) as pool:
                results = list(pool.map(lambda q: check(client, q), batch))
            elapsed = time.perf_counter() - start
            firsts, totals, answered = zip(*results, strict=True)
            print(f"| {level} | {len(batch) / elapsed:.1f} | {percentiles(list(firsts))}"
                  f" | {percentiles(list(totals))} | {answered.count(False)} |")  # fmt: skip
    time.sleep(6)  # the API exports spans in batches every few seconds
    print("\n| Step | Spans | p50 / p95 s |\n|---|---|---|")
    for name, durations in step_times(args.traces, began).items():
        print(f"| {name} | {len(durations)} | {percentiles(durations)} |")


if __name__ == "__main__":
    main()
