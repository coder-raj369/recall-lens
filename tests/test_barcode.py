import urllib.error

import pytest

zxingcpp = pytest.importorskip("zxingcpp")
Image = pytest.importorskip("PIL.Image")

from recall_lens.perception import barcode  # noqa: E402


def ean13_photo(code, angle=0):
    symbol = zxingcpp.create_barcode(code, zxingcpp.BarcodeFormat.EAN13)
    bars = Image.fromarray(zxingcpp.write_barcode_to_image(symbol, scale=3)).convert("RGB")
    canvas = Image.new("RGB", (bars.width + 200, bars.height + 200), "white")
    canvas.paste(bars, (100, 100))
    return canvas.rotate(angle, expand=True, fillcolor="white")


def test_decodes_retail_barcodes_including_rotated():
    assert barcode.decode(ean13_photo("0036000291452")) == {"0036000291452"}
    assert barcode.decode(ean13_photo("4006381333931", angle=90)) == {"4006381333931"}
    assert barcode.decode(Image.new("RGB", (200, 200), "white")) == set()


def test_lookup_reads_name_and_brands(monkeypatch):
    payload = {
        "status": 1,
        "product": {"product_name": "Oyster Crackers", "brands": "Giant Eagle, "},
    }
    monkeypatch.setattr(barcode, "get_json", lambda url, params: payload)
    assert barcode.lookup("030034900371") == {"name": "Oyster Crackers", "brands": ["Giant Eagle"]}


def test_lookup_returns_none_for_unknown_products(monkeypatch):
    def not_found(url, params):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr(barcode, "get_json", not_found)
    assert barcode.lookup("000") is None
    monkeypatch.setattr(barcode, "get_json", lambda url, params: {"status": 0})
    assert barcode.lookup("000") is None
