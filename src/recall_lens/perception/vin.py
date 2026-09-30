"""Find vehicle identification numbers in OCR text and decode them with NHTSA vPIC."""

import http.client
import re

from recall_lens.ingest.http import get_json

VPIC_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}"
# Transliteration of letters to values for the check digit (49 CFR 565.15).
_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"
_LETTER_VALUES = (1, 2, 3, 4, 5, 6, 7, 8, 1, 2, 3, 4, 5, 7, 9, 2, 3, 4, 5, 6, 7, 8, 9)
_VALUES = {str(d): d for d in range(10)} | dict(zip(_LETTERS, _LETTER_VALUES, strict=True))
_WEIGHTS = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)
# 17 characters, allowing the single spaces OCR inserts ("L0SSCHL 17MT120129").
_CANDIDATE = re.compile(r"(?<![A-Z0-9])[A-Z0-9](?:[A-Z0-9]| (?=[A-Z0-9])){16,19}(?![A-Z0-9])")
_OCR_FIXES = str.maketrans(
    "IOQ", "100"
)  # VINs never contain I, O or Q; OCR confuses them with 1 and 0


def is_valid(vin: str) -> bool:
    """17 characters from the VIN alphabet with a correct check digit (position 9)."""
    if len(vin) != 17 or any(c not in _VALUES for c in vin):
        return False
    remainder = sum(_VALUES[c] * w for c, w in zip(vin, _WEIGHTS, strict=True)) % 11
    return vin[8] == ("X" if remainder == 10 else str(remainder))


def find(text: str) -> set[str]:
    """Valid VINs in text, after repairing OCR's I/O/Q confusions."""
    found = set()
    for match in _CANDIDATE.finditer(text.upper()):
        vin = match.group().replace(" ", "").translate(_OCR_FIXES)
        if is_valid(vin):
            found.add(vin)
    return found


def decode(vin: str) -> dict:
    """Make, model and model year from vPIC; empty values when NHTSA has no record or is down.

    A person is waiting, so one quick retry, and an outage only loses the vehicle's name.
    """
    try:
        reply = get_json(VPIC_URL.format(vin=vin), {"format": "json"}, retries=1, timeout=5)
        result = reply["Results"][0]
    except (OSError, http.client.HTTPException, ValueError, KeyError, IndexError):
        result = {}
    return {
        "make": result.get("Make") or None,
        "model": result.get("Model") or None,
        "year": result.get("ModelYear") or None,
    }
