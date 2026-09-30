"""The evaluation gate: the rules must not get worse on the 300 recorded end-to-end cases.

When a change improves results, accept them with `python -m recall_lens.evals.replay update`;
when retrieval changes, re-record the fixture with `python -m recall_lens.evals.replay record`.
"""

import json

from recall_lens.evals import replay


def test_no_split_misses_more_recalls_gives_more_unsafe_answers_or_fewer_right_ones():
    now = replay.current()
    assert not replay.regressions(now, json.loads(replay.BASELINE.read_text())), now


def test_regressions_name_what_got_worse():
    base = {split: {"cases": 2, "right": 2, "missed": 0, "unsafe": 0} for split in replay.SPLITS}
    now = {**base, "test": {"cases": 2, "right": 1, "missed": 1, "unsafe": 1}}
    assert replay.regressions(now, base) == [
        "test: missed 0 -> 1",
        "test: unsafe 0 -> 1",
        "test: right answers 2 -> 1",
    ]
    assert replay.regressions(base, now) == []  # improvements pass
