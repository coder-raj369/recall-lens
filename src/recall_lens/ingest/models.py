"""Normalized recall record produced by every agency connector."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date

AGENCIES = frozenset({"cpsc", "fda", "fsis", "nhtsa"})
IDENTIFIER_KINDS = frozenset({"upc", "model", "lot", "vin", "brand", "year"})

Identifier = tuple[str, str]


def identifier(kind: str, value: str | None) -> Identifier | None:
    """Canonicalize an identifier so the same code always compares equal.

    UPCs keep digits only; everything else is upper-cased with whitespace collapsed.
    Returns None for empty or unusable values.
    """
    if kind not in IDENTIFIER_KINDS:
        raise ValueError(f"unknown identifier kind: {kind}")
    if not value:
        return None
    if kind == "upc":
        value = re.sub(r"\D", "", value)
        return (kind, value) if 8 <= len(value) <= 14 else None
    value = " ".join(value.split()).upper()
    return (kind, value) if value else None


@dataclass(frozen=True)
class Recall:
    agency: str
    source_id: str
    title: str
    recall_date: date | None
    raw: dict
    description: str | None = None
    hazard: str | None = None
    remedy: str | None = None
    product_type: str | None = None
    source_url: str | None = None
    identifiers: frozenset[Identifier] = field(default_factory=frozenset)

    def __post_init__(self):
        if self.agency not in AGENCIES:
            raise ValueError(f"unknown agency: {self.agency}")
        if not self.source_id or not self.title:
            raise ValueError("source_id and title are required")
        if bad := {k for k, _ in self.identifiers} - IDENTIFIER_KINDS:
            raise ValueError(f"unknown identifier kinds: {sorted(bad)}")

    @property
    def content_hash(self) -> str:
        """Stable digest of the normalized record, including the raw payload.

        Changes when the agency edits a recall or when normalization logic changes,
        so the upsert can skip rows that are genuinely unchanged.
        """
        data = asdict(self)
        data["identifiers"] = sorted(self.identifiers)
        encoded = json.dumps(data, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()
