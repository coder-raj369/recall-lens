"""Find recalls for a product photo: read it, enrich the query, then search."""

from dataclasses import dataclass

import psycopg
from PIL import Image

from recall_lens.perception import barcode, release_models, vin
from recall_lens.perception.read import Reading, normalize, read
from recall_lens.retrieval.search import Hit, search

MAX_QUERY_CHARS = 1_500  # label text beyond this adds noise, not signal
FOCUSED_CHARS = 300


@dataclass(frozen=True)
class PhotoResult:
    reading: Reading
    query: str
    hits: list[Hit]


def build_query(reading: Reading, lookups: bool = True, focused: bool = True) -> str:
    """Search text for a photo reading.

    Focused queries keep what identifies the product: barcode and VIN lookups, brands, codes and
    the whole-photo text (large print names the product), capped at FOCUSED_CHARS. Text read
    from label regions is mostly small print (addresses, warnings) and contributes codes only.
    Unfocused queries use all the text that was read.
    """
    parts = []
    if lookups:
        for kind, value in sorted(reading.identifiers):
            if kind == "upc" and (product := barcode.lookup(value)):
                parts += [*product["brands"], product["name"] or ""]
            elif kind == "vin":
                vehicle = vin.decode(value)
                parts.append(
                    " ".join(filter(None, [vehicle["year"], vehicle["make"], vehicle["model"]]))
                )
    if focused:
        parts += [v for k, v in sorted(reading.identifiers) if k == "brand"]
        parts += sorted(reading.codes)
        parts.append(normalize(reading.texts[0])[:FOCUSED_CHARS])
    else:
        parts.append(normalize(reading.text))
    return " ".join(" ".join(parts).split())[:MAX_QUERY_CHARS]


def find_recalls(
    conn: psycopg.Connection,
    image: Image.Image,
    limit: int = 10,
    use_detection: bool = True,
    lookups: bool = True,
    focused: bool = True,
    **search_options,
) -> PhotoResult:
    reading = read(image, use_detection=use_detection)
    query = build_query(reading, lookups, focused)
    release_models()  # search loads bge-m3 next
    if not query and not reading.codes:
        return PhotoResult(reading, query, [])
    hits = search(conn, query, limit=limit, extra_codes=reading.codes, **search_options)
    return PhotoResult(reading, query, hits)
