import pytest

pytest.importorskip("PIL")

from recall_lens.perception import read as reader  # noqa: E402


def test_normalize_repairs_ocr_spacing():
    assert reader.normalize("Model No .: S-Y608") == "Model No.: S-Y608"
    assert reader.normalize("MODEL:T30 -F  S/N : TM729") == "MODEL:T30-F  S/N: TM729"
    assert reader.normalize("red - blue") == "red - blue"  # only spaced hyphens between codes


def test_read_combines_regions_and_extracts(monkeypatch):
    from recall_lens.perception import crop, detect, ocr

    texts = iter(["Product Name: Baby Swing\nModel No .: S-Y608", "0863VE01"])
    monkeypatch.setattr(ocr, "read_text", lambda image: next(texts))
    monkeypatch.setattr(detect, "detect", lambda image: [detect.Region((0, 0, 9, 9), "q", 0.5)])
    monkeypatch.setattr(crop, "crop", lambda image, box: image)
    reading = reader.read(object(), use_model=False)
    assert ("model", "S-Y608") in reading.identifiers
    assert reading.codes == {"S-Y608", "0863VE01"}
    assert len(reading.texts) == 2
