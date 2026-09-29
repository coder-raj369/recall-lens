import pytest

pytest.importorskip("PIL")

from recall_lens.evals.photos import field_counts, load_split  # noqa: E402
from recall_lens.perception.read import Reading  # noqa: E402


def test_field_counts_ignore_upc_leading_zeros_and_match_brands_leniently():
    reading = Reading(
        texts=("",),
        identifiers=frozenset({("brand", "HUFFY CORPORATION"), ("upc", "0028914172491")}),
        codes=frozenset({"0028914172491", "17249", "8877"}),
    )
    gold = {"brand": ["Huffy"], "model": ["17249"], "upc": ["028914172491"]}
    counts = field_counts(reading, gold)
    assert (counts["brand", "tp"], counts["upc", "tp"], counts["model", "fn"]) == (1, 1, 1)
    assert (counts["codes", "tp"], counts["codes", "fp"]) == (2, 1)


@pytest.mark.parametrize(("split", "size"), [("dev", 50), ("test", 100)])
def test_photo_splits_load_and_do_not_overlap(split, size):
    records = load_split(split)
    assert len(records) == size
    assert all(r["target"] in r["relevant"] for r in records)
    other = {r["id"] for r in load_split("test" if split == "dev" else "dev")}
    assert not other & {r["id"] for r in records}
