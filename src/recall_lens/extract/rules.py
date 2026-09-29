"""Rule-based identifier extraction for labeled codes ("Lot #: 123, 124", "UPC 0 12345 67890 5").

Rules only fire after an explicit label, which keeps precision high. Unlabeled mentions are left
to the model-based extractor. Ranges ("batches 1535 through 1545") yield their endpoints; range
semantics are applied by the verifier (ADR-0003).
"""

import re

from recall_lens.ingest.models import Identifier, identifier

MAX_TEXT = 50_000  # some FDA reports run to megabytes of lot codes; identifiers come early
MAX_PER_KIND = 1_000

_NUMBER_SUFFIX = r"(?:\s*(?:#|no\.?|nos\.?|numbers?|codes?))?"
_LABELS = {
    "lot": rf"lots?{_NUMBER_SUFFIX}|batch(?:es)?{_NUMBER_SUFFIX}|serial{_NUMBER_SUFFIX}",
    "model": (
        rf"models?{_NUMBER_SUFFIX}|ref\.?{_NUMBER_SUFFIX}|cat(?:alog)?\.?\s*(?:#|no\.?|numbers?)"
        r"|(?:part|material|item)\s*(?:#|no\.?|numbers?)"
    ),
    "upc": rf"upcs?{_NUMBER_SUFFIX}|gtins?|udi(?:-di)?|barcodes?",
}
_LABEL_RE = re.compile(
    r"\b(?:" + "|".join(f"(?P<{kind}>{pattern})" for kind, pattern in _LABELS.items()) + r")",
    re.IGNORECASE,
)
_SEPARATOR = re.compile(r"(?:[,;:&/()\-]|\band\b|\bor\b|\bthrough\b|\bthru\b|\bto\b|\s)+", re.I)
# Expiry dates and "a)" list markers interrupt code lists ("Lot #: 82886, exp 09/30/2026; 89646").
_SKIPPABLE = re.compile(
    r"(?:(?:exp(?:iry|ires|iration)?|bud|use\s+by|best\s+by)\.?(?:\s*date)?\s*[:.]?\s*"
    r"(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{1,2}[/.-]\d{4}|\d{4}[/.-]\d{1,2}(?:[/.-]\d{1,2})?"
    r"|[A-Z]{3}\s+\d{4}|\d{4}-[A-Z]{3})(?![\dA-Z])"
    r"|\b[a-z]\))",
    re.IGNORECASE,
)
_NUMERIC_RANGE = re.compile(r"^(\d+)-(\d+)$")
_CODE = re.compile(r"[A-Z0-9][A-Z0-9+\-._]*[A-Z0-9]|[0-9]", re.IGNORECASE)
_DIGIT_RUN = re.compile(r"\d[\d -]{6,18}\d")
_NDC = re.compile(r"(?<![\w-])\d{4,5}-\d{3,4}-\d{1,2}(?![\w-])")
# ponytail: bare years count as dates, so a lot literally numbered "2019" is missed.
_DATE_LIKE = re.compile(r"^\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?$|^\d{1,2}/\d{4}$|^(?:19|20)\d{2}$")
_LIST_MARKER = re.compile(r"\d{1,3}\)")  # "14) ..." enumerations in FDA kit listings


def _codes_after(text: str, start: int) -> list[str]:
    """Collect code-like tokens following a label, stopping at the first ordinary word."""
    codes, pos = [], start
    while pos < len(text):
        if sep := _SEPARATOR.match(text, pos) or _SKIPPABLE.match(text, pos):
            pos = sep.end()
            continue
        token = _CODE.match(text, pos)
        if not token or _LIST_MARKER.match(text, pos):
            break
        value = token.group()
        if not any(c.isdigit() for c in value) or _DATE_LIKE.match(value):
            break
        if (bounds := _NUMERIC_RANGE.match(value)) and len(bounds[1]) == len(bounds[2]):
            codes.extend(bounds.groups())  # "335314-335315" is a range, not one code
        else:
            codes.append(value)
        pos = token.end()
    return codes


def _upcs_after(text: str, start: int) -> list[str]:
    tail = re.match(
        r"[\s#:,()&]*(?:(?:and|or|codes?|numbers?)\b|[\d ,;()-]|\s)*", text[start:], re.I
    )
    return _DIGIT_RUN.findall(tail.group()) if tail else []


def extract(text: str | None) -> set[Identifier]:
    """Return canonical identifiers found after explicit labels in text."""
    if not text:
        return set()
    text = text[:MAX_TEXT]
    found: dict[str, list[str]] = {"lot": [], "model": [], "upc": []}
    for label in _LABEL_RE.finditer(text):
        kind = label.lastgroup
        values = (
            _upcs_after(text, label.end()) if kind == "upc" else _codes_after(text, label.end())
        )
        found[kind].extend(values)
    found["ndc"] = _NDC.findall(text)
    return {
        ident
        for kind, values in found.items()
        for value in values[:MAX_PER_KIND]
        if (ident := identifier(kind, value))
    }


MIN_BARE_CODE = 5  # unlabeled tokens shorter than this ("F1", "4x4") are too ambiguous
_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9+\-./_]*[A-Z0-9]", re.IGNORECASE)
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
# Phone numbers, ZIP+4 codes and address ordinals look like codes on labels and packaging.
_NOT_A_CODE = re.compile(
    r"^(?:\d{3}-\d{4}|\d{3}-\d{3}-\d{4}|\d{5}-\d{4}|\d+(?:ST|ND|RD|TH))$", re.I
)


def codes(text: str) -> set[str]:
    """Code values in free text: labeled codes plus bare code-like tokens, kind unknown.

    Used for search queries and photo text, where "CBR600RR" or a stamped "0863VE01" carries
    no label. Tokens shorter than five characters, without a digit, or that are years are skipped.
    """
    values = {value for _, value in extract(text)}
    labeled = " ".join(values)
    for token in _TOKEN.findall(text):
        if len(token) < MIN_BARE_CODE or not any(c.isdigit() for c in token):
            continue
        if _YEAR.match(token) or _NOT_A_CODE.match(token):
            continue
        if token.isdigit() and token in labeled:  # a digit group of a spaced, labeled UPC
            continue
        values.add(token.upper())
    return values
