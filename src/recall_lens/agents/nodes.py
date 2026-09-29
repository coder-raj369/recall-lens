"""Node implementations for the recall-check graph (see agents.graph for the topology)."""

from collections.abc import Callable
from dataclasses import dataclass

from recall_lens.agents.state import CheckState
from recall_lens.extract import rules
from recall_lens.perception import vin
from recall_lens.perception.read import Reading, normalize


def _read_photo(photo: str) -> Reading:
    from recall_lens.perception.image import load
    from recall_lens.perception.read import read

    return read(load(photo))


@dataclass
class Services:
    """What the nodes need from the outside world; tests swap these for fakes."""

    read_photo: Callable[[str], Reading] = _read_photo
    lookups: bool = True  # resolve barcodes (Open Food Facts) and VINs (NHTSA vPIC)


def perceive(services: Services):
    def run(state: CheckState) -> dict:
        from recall_lens.perception import release_models
        from recall_lens.perception.recalls import build_query

        reading = services.read_photo(state["photo"])
        photo_query = build_query(reading, lookups=services.lookups)
        release_models()  # retrieval loads bge-m3 next; together they overflow 8 GB
        return {
            "photo_text": normalize(reading.text),
            "photo_query": photo_query,
            "identifiers": sorted([k, v] for k, v in reading.identifiers),
            "codes": sorted(reading.codes),
        }

    return run


def identify(services: Services):
    def run(state: CheckState) -> dict:
        query = state.get("query", "")
        vins = vin.find(query)
        identifiers = {tuple(pair) for pair in state.get("identifiers", [])}
        identifiers |= rules.extract(query) | {("vin", v) for v in vins}
        search = [query, state.get("photo_query", "")]
        if services.lookups:
            for v in sorted(vins):
                vehicle = vin.decode(v)
                search.append(
                    " ".join(filter(None, [vehicle["year"], vehicle["make"], vehicle["model"]]))
                )
        return {
            "identifiers": sorted([k, v] for k, v in identifiers),
            "codes": sorted(set(state.get("codes", [])) | rules.codes(query) | vins),
            "search_text": " ".join(" ".join(filter(None, search)).split()),
            "text": "\n".join(filter(None, [query, state.get("photo_text", "")])),
        }

    return run
