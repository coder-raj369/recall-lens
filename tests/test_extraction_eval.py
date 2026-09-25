import pytest

from recall_lens.evals.extraction import load, prf, score


def test_brand_matching_ignores_suffixes_and_allows_containment():
    counts = score(
        {("brand", "SOMERSET THERAPEUTICS"), ("brand", "ACME")},
        {("brand", "SOMERSET THERAPEUTICS, LLC"), ("brand", "JOY")},
    )
    assert (counts["brand", "tp"], counts["brand", "fp"], counts["brand", "fn"]) == (1, 1, 1)


def test_codes_match_exactly_and_prf_is_micro_averaged():
    counts = score({("lot", "A1"), ("lot", "A2"), ("upc", "012345678905")}, {("lot", "A1")})
    assert (counts["lot", "tp"], counts["lot", "fp"], counts["upc", "fp"]) == (1, 1, 1)
    precision, recall, f1 = prf(counts, ["lot", "upc"])
    assert (round(precision, 2), recall, round(f1, 2)) == (0.33, 1.0, 0.5)


@pytest.mark.parametrize(("split", "size"), [("dev", 100), ("test", 60)])
def test_splits_load_with_canonical_gold_and_do_not_overlap(split, size):
    records = load(split)
    assert len(records) == size
    assert {r["agency"] for r in records} == {"fda", "cpsc", "nhtsa"}
    other = load("test" if split == "dev" else "dev")
    assert not {r["source_id"] for r in records} & {r["source_id"] for r in other}
