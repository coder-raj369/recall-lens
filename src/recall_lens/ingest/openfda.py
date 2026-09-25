"""FDA food, drug and device recalls from the openFDA enforcement report endpoints."""

import hashlib
import urllib.error
from collections.abc import Iterator
from datetime import date, datetime

from recall_lens.ingest.http import get_json
from recall_lens.ingest.models import Recall, identifier

API_URL = "https://api.fda.gov/{category}/enforcement.json"
CATEGORIES = ("food", "drug", "device")
PAGE_SIZE = 1000
MAX_SKIP = 25_000  # openFDA refuses deeper pagination; yearly windows stay far below it
EVENT_URL = "https://www.accessdata.fda.gov/scripts/ires/index.cfm?Event={event_id}"


def fetch(since: date, until: date | None = None) -> Iterator[Recall]:
    """Yield enforcement reports published between since and until, by category and year."""
    until = until or date.today()
    for category in CATEGORIES:
        for year in range(since.year, until.year + 1):
            start = max(since, date(year, 1, 1))
            end = min(until, date(year, 12, 31))
            window = f"report_date:[{start:%Y%m%d} TO {end:%Y%m%d}]"
            for record in _paginate(API_URL.format(category=category), window):
                yield normalize(record, category)


def _paginate(url: str, search: str) -> Iterator[dict]:
    skip = 0
    while True:
        params = {
            "search": search,
            "sort": "recall_number.exact:asc",
            "limit": PAGE_SIZE,
            "skip": skip,
        }
        try:
            page = get_json(url, params)
        except urllib.error.HTTPError as error:
            if error.code == 404:  # openFDA signals "no matches" with 404
                return
            raise
        yield from page["results"]
        skip += PAGE_SIZE
        total = page["meta"]["results"]["total"]
        if skip >= total:
            return
        if skip > MAX_SKIP:
            raise RuntimeError(f"{total} results for {search!r} exceed openFDA pagination")


def _date(value: str | None) -> date | None:
    return datetime.strptime(value, "%Y%m%d").date() if value else None


def _truncate(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _source_id(record: dict, product: str) -> str:
    # A few published reports have an empty or "N/A" recall_number; derive a stable key instead.
    number = (record.get("recall_number") or "").strip()
    if number and number.upper() not in {"N/A", "NA"}:
        return number
    digest = hashlib.sha1(product.encode()).hexdigest()[:8]
    return f"EVENT-{record['event_id']}-{digest}"


def normalize(record: dict, category: str) -> Recall:
    product = " ".join(record["product_description"].split())
    codes = " ".join(filter(None, [record.get("code_info"), record.get("more_code_info")]))
    description = "\n".join(
        f"{label}: {value}"
        for label, value in [
            ("Product", product),
            ("Codes", codes),
            ("Quantity", record.get("product_quantity")),
            ("Distribution", record.get("distribution_pattern")),
        ]
        if value
    )
    openfda = record.get("openfda") or {}
    brands = openfda.get("brand_name") or [record.get("recalling_firm")]
    ids = {identifier("brand", b) for b in brands}
    ids |= {identifier("upc", u) for u in openfda.get("upc", [])}
    ids |= {identifier("ndc", n) for n in openfda.get("package_ndc", [])}
    return Recall(
        agency="fda",
        source_id=_source_id(record, product),
        title=_truncate(product),
        description=description,
        hazard=f"{record['classification']}: {record['reason_for_recall'].strip()}",
        remedy=None,  # enforcement reports do not include consumer remedies
        product_type=category,
        recall_date=_date(record.get("recall_initiation_date")) or _date(record["report_date"]),
        source_url=EVENT_URL.format(event_id=record["event_id"]),
        raw=record,
        identifiers=frozenset(ids - {None}),
    )
