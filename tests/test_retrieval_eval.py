import pytest

from recall_lens.evals.retrieval import first_hit, load, summarize


def test_first_hit_and_hit_rates():
    assert first_hit(["a", "b", "c"], {"c", "z"}) == 3
    assert first_hit(["a"], {"z"}) is None
    metrics = summarize([1, 3, None, 7])
    assert (metrics["R@1"], metrics["R@5"], metrics["R@10"]) == (0.25, 0.5, 0.75)
    assert metrics["MRR@10"] == pytest.approx((1 + 1 / 3 + 1 / 7) / 4)


@pytest.mark.parametrize(("split", "size"), [("dev", 50), ("test", 100)])
def test_splits_are_disjoint_and_targets_are_relevant(split, size):
    records = load(split)
    assert len(records) == size
    assert all(r["target"] in r["relevant"] for r in records)
    other = {r["id"] for r in load("test" if split == "dev" else "dev")}
    assert not other & {r["id"] for r in records}
