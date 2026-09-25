from datetime import date

import pytest

from recall_lens.extract.enrich import enrich
from recall_lens.extract.model import _clean
from recall_lens.ingest.models import Recall


def test_clean_strips_labels_and_requires_digits_for_codes():
    assert _clean("model", "Model H-1") == ("model", "H-1")
    assert _clean("upc", "UPC code 7 84762 03730 3") == ("upc", "784762037303")
    assert _clean("lot", "BATCH NO") is None
    assert _clean("brand", "Crown Farms") == ("brand", "CROWN FARMS")


def test_enrich_merges_rule_identifiers_with_agency_identifiers():
    recall = Recall(
        agency="cpsc",
        source_id="26467",
        title="Favoto Recalls Bike Helmets",
        description="This recall involves Favoto Model H-1 bike helmets.",
        recall_date=date(2026, 1, 1),
        raw={},
        identifiers=frozenset({("brand", "FAVOTO")}),
    )
    assert enrich(recall, use_model=False).identifiers == {("brand", "FAVOTO"), ("model", "H-1")}


def test_model_finds_unlabeled_brand_and_models():
    pytest.importorskip("gliner")
    from recall_lens.extract.model import extract

    text = "This recall involves Matrix Retail models T30 and TF30 treadmills."
    found = extract(text)
    assert {("brand", "MATRIX RETAIL"), ("model", "T30"), ("model", "TF30")} <= found
