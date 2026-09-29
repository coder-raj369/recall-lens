"""Decode retail barcodes with zxing-cpp and look products up in Open Food Facts.

Requires the optional `ml` dependency group (zxing-cpp, Pillow).
"""

import urllib.error

from PIL import Image

from recall_lens.ingest.http import get_json
from recall_lens.ingest.models import identifier

PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"


def decode(image: Image.Image) -> set[str]:
    """Canonical UPC/EAN values of retail barcodes found in the image."""
    import zxingcpp

    found = set()
    for result in zxingcpp.read_barcodes(image):  # tries rotations and inverted images itself
        if result.text.isdigit() and (ident := identifier("upc", result.text)):
            found.add(ident[1])  # retail codes are 8-14 digits; QR and Code 128 payloads are not
    return found


def lookup(upc: str) -> dict | None:
    """Product name and brands from Open Food Facts, or None if the product is unknown."""
    try:
        data = get_json(PRODUCT_URL.format(code=upc), {"fields": "product_name,brands"})
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    if data.get("status") != 1:
        return None
    product = data.get("product") or {}
    brands = [b.strip() for b in (product.get("brands") or "").split(",") if b.strip()]
    return {"name": (product.get("product_name") or "").strip() or None, "brands": brands}
