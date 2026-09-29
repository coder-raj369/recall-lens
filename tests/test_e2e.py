"""End-to-end metrics: which answers count as safe, unsafe, abstaining and correctly cited."""

from recall_lens.evals import e2e


def result(i, expected, predicted, cited=None):
    return {"id": str(i), "type": "t", "expected": expected, "predicted": predicted,
            "cited": cited, "seconds": 1.0}  # fmt: skip


def test_metrics_separate_missed_recalls_from_abstentions_and_false_alarms():
    cases = {str(i): {"target": "fda:A", "relevant": ["fda:A", "fda:B"]} for i in range(8)}
    results = [
        result(0, "affected", "affected", "fda:A"),
        result(1, "affected", "affected", "fda:B"),  # a relevant sibling: lenient only
        result(2, "affected", "no_match"),  # missed: the costliest error
        result(3, "affected", "needs_info"),  # asked instead: not a miss
        result(4, "needs_info", "not_affected"),  # told safe while it may not be: unsafe
        result(5, "not_affected", "no_match"),  # any negative answer is right
        result(6, "no_recall", "affected", "fda:A"),  # false alarm
        result(7, "no_recall", "no_match"),
    ]
    m = e2e.metrics(results, cases)
    assert m["false_negative"] == 1 / 4
    assert m["unsafe"] == 2 / 5
    assert m["false_alarm"] == 1 / 3
    assert m["abstention"] == 1 / 8
    assert m["accuracy"] == 4 / 8
    assert (m["cited"], m["cited_strict"]) == (1.0, 0.5)
