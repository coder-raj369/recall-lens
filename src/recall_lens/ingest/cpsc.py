"""CPSC consumer product recalls from the SaferProducts.gov REST API."""

import re
from collections.abc import Iterator
from datetime import date

from recall_lens.ingest.http import get_json
from recall_lens.ingest.models import Recall, identifier

API_URL = "https://www.saferproducts.gov/RestWebServices/Recall"

# "Acme Recalls Space Heaters ..." / "Acme Expands Recall of ..." -> "Acme"
_FIRM_IN_TITLE = re.compile(r"^(.+?) (?:Recalls|Expands Recall|Announces Recall)\b")


def fetch(since: date, until: date | None = None) -> Iterator[Recall]:
    """Yield recalls published between since and until, one calendar year per request."""
    until = until or date.today()
    for year in range(since.year, until.year + 1):
        start = max(since, date(year, 1, 1))
        end = min(until, date(year, 12, 31))
        params = {"format": "json", "RecallDateStart": start, "RecallDateEnd": end}
        for record in get_json(API_URL, params):
            yield normalize(record)


def _join(items: list[dict], key: str = "Name") -> str | None:
    return "\n".join(i[key].strip() for i in items if i.get(key, "").strip()) or None


def normalize(record: dict) -> Recall:
    title = record["Title"].strip()
    ids = {identifier("upc", u.get("UPC")) for u in record.get("ProductUPCs") or []}
    ids |= {identifier("model", p.get("Model")) for p in record.get("Products") or []}
    if firm := _FIRM_IN_TITLE.match(title):
        ids.add(identifier("brand", firm.group(1)))
    return Recall(
        agency="cpsc",
        source_id=str(record["RecallNumber"]),
        title=title,
        description=(record.get("Description") or "").strip() or None,
        hazard=_join(record.get("Hazards") or []),
        remedy=_join(record.get("Remedies") or []),
        product_type="consumer_product",
        recall_date=date.fromisoformat(record["RecallDate"][:10]),
        source_url=record.get("URL"),
        raw=record,
        identifiers=frozenset(ids - {None}),
    )
