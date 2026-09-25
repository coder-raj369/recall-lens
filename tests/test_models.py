from datetime import date

import pytest

from recall_lens.ingest.models import Recall, identifier


def make(**overrides):
    fields = {
        "agency": "cpsc",
        "source_id": "26789",
        "title": "Helmet recall",
        "recall_date": date(2026, 9, 24),
        "raw": {"RecallNumber": "26789"},
        "identifiers": frozenset({("model", "YD-001"), ("lot", "YD-260320")}),
    }
    return Recall(**(fields | overrides))


def test_identifier_canonicalization():
    assert identifier("upc", "0 12345-67890 5") == ("upc", "012345678905")
    assert identifier("upc", "12") is None
    assert identifier("lot", "  yd-260320 ") == ("lot", "YD-260320")
    assert identifier("model", "") is None
    with pytest.raises(ValueError):
        identifier("colour", "red")


def test_content_hash_ignores_identifier_order_but_tracks_changes():
    a = make()
    b = make(identifiers=frozenset({("lot", "YD-260320"), ("model", "YD-001")}))
    assert a.content_hash == b.content_hash
    assert make(hazard="Head injury").content_hash != a.content_hash
    assert make(raw={"RecallNumber": "26789", "edited": True}).content_hash != a.content_hash


def test_rejects_invalid_records():
    with pytest.raises(ValueError):
        make(agency="epa")
    with pytest.raises(ValueError):
        make(title="")
    with pytest.raises(ValueError):
        make(identifiers=frozenset({("sku", "1")}))
