"""Decide whether a specific unit falls inside a recall, with rules only (ADR-0003).

A recall's scope comes from its identifiers and wording: listed codes, code ranges ("serial numbers
KK23288361 through KK23388361"), date windows ("best by 12/2025 through 05/2027"), "all lots" and,
for vehicles, affected make/model/year lists. The user's facts are the codes, dates, years and text
they gave. The verifier says "not affected" only when the product is clearly the recalled one and
the unit is clearly outside the listed scope; anything else is "needs more information" or
"undetermined", because a false "not affected" is the costliest error.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import date

from recall_lens.agents.state import AFFECTED, NEEDS_INFO, NOT_AFFECTED, UNDETERMINED

UNIT_KINDS = ("lot", "upc", "ndc", "vin")  # identify units or package variants, not product lines
CODE_KINDS = ("model", *UNIT_KINDS)

_CODE = r"[A-Z]{0,6}\d{3,}"
# Hyphens and bare "and" are not range markers: "0517-9302" is one NDC, "1234 and 5678" a list.
_RANGE = re.compile(
    rf"(?<![A-Z0-9/])(?:({_CODE})\s+(?:through|thru|to)\s+({_CODE})"
    rf"|between\s+({_CODE})\s+(?:and|to)\s+({_CODE}))(?![A-Z0-9/])",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
# Any "X through Y" / "between X and Y" over codes: ranges we cannot read numerically still mean
# the listed endpoints are not the whole list.
_ANY_RANGE = re.compile(
    r"(?<![A-Z0-9/])(?:([A-Z0-9][A-Z0-9-]*\d[A-Z0-9-]*)\s+(?:through|thru)\s+([A-Z0-9][A-Z0-9-]*\d[A-Z0-9-]*)"
    r"|between\s+([A-Z0-9][A-Z0-9-]*\d[A-Z0-9-]*)\s+(?:and|to)\s+([A-Z0-9][A-Z0-9-]*\d[A-Z0-9-]*))"
    r"(?![A-Z0-9/])",
    re.IGNORECASE,
)
# Date and production codes are encoded (e.g. day-of-year + year: 16919 is day 169 of 2019), so a
# numeric reading of their ranges would be wrong.
_ENCODED = re.compile(r"date\s+codes?|production\s+codes?|manufactur\w*\s+codes?|julian", re.I)
_DATE = r"\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}/\d{4}"
_EXPIRY = r"best[- ]?by|use[- ]?by|sell[- ]?by|enjoy[- ]?by|exp(?:iry|iration)?(?:\s+dates?)?"
_PRODUCTION = r"manufactured|production|produced|packed(?:\s+on)?|mfg"
_WINDOW = re.compile(
    rf"(?P<label>{_EXPIRY}|{_PRODUCTION})\b[^.;\n]{{0,30}}?(?P<start>{_DATE})\s*"
    rf"(?:through|thru|to|and|-|–)\s*(?P<end>{_DATE})",
    re.IGNORECASE,
)
_USER_DATE = re.compile(
    rf"(?P<label>{_EXPIRY}|{_PRODUCTION})\b\s*(?:date)?\s*[:#-]?\s*(?P<date>{_DATE})", re.I
)
# Wording that says the notice's code list continues elsewhere ("For Lot Numbers, see Attachment
# F", "see recall documents for a full list"). An unlisted code then proves nothing. Some matches
# are about distribution lists instead, which costs an abstention, never a false "not affected".
_INCOMPLETE = re.compile(
    r"see\s+(?:the\s+)?(?:attach\w*|enclosed|recall\s+(?:documents?|report)|appendix)"
    r"|attachment\s+[A-Z0-9]\b|(?:full|complete)\s+list|not\s+limited\s+to|\b(?:and|&)\s+others\b",
    re.IGNORECASE,
)
# "All lots" with no date or distribution qualifier; "all lots within expiry" still means all.
_ALL_UNITS = re.compile(
    r"\ball\s+(?:lots|lot numbers|serial numbers|units|codes|sizes|batches|model numbers)\b"
    r"(?![^.;\n]{0,40}\b(?:manufactured|produced|distributed|between|through|before|after|from)\b)",
    re.IGNORECASE,
)
_GENERIC = {
    "INC", "LLC", "LTD", "CO", "CORP", "CORPORATION", "COMPANY", "LIMITED", "USA", "US", "THE",
    "AMERICA", "NORTH", "INTERNATIONAL", "GROUP", "BRANDS", "BRAND", "PRODUCTS", "FOODS",
}  # fmt: skip
_TITLE_NOISE = {
    "RECALL", "RECALLS", "RECALLED", "DUE", "RISK", "HAZARD", "HAZARDS", "SERIOUS", "INJURY",
    "DEATH", "FROM", "AND", "THE", "WITH", "FOR", "SOLD", "EXCLUSIVELY", "AMAZON", "WALMART",
    "VIOLATE", "VIOLATES", "VIOLATION", "MANDATORY", "STANDARD", "FEDERAL", "OF", "ON", "IN",
    "BY", "AT", "TO", "IMPORTED", "MANUFACTURED", "DISTRIBUTED", "CERTAIN", "SELECT", "FIRE",
    "BURN", "SHOCK", "CHOKING", "LACERATION", "FALL", "ENTRAPMENT", "SUFFOCATION", "POISONING",
    "TIP-OVER", "ELECTROCUTION", "DROWNING", "INGESTION", "STRANGULATION", "CRASH",
}  # fmt: skip
# Words of a question or a code label, not of a product: "Should I stop using my ... lot 123?"
_STOP = {
    "ANY", "ARE", "CAN", "DOES", "HAS", "HAVE", "HOW", "ITS", "NOT", "OPEN", "OUR", "PART",
    "SHOULD", "STILL", "STOP", "THIS", "THAT", "USING", "WAS", "WHAT", "WHICH", "YOUR", "MINE",
    "LOT", "BATCH", "SERIAL", "NUMBER", "MODEL", "CODE", "DATE", "BEST", "SELL", "USE", "EXP",
    "UPC", "NDC", "VIN", "SKU", "ITEM", "REF", "YEAR",
}  # fmt: skip
# Scope limited to some units without listing them in a form we can compare ("certain VINs of
# Model Year 2024 RANGER XD 1500"): the person has to check, so it never covers every unit.
_PARTIAL = re.compile(
    r"\b(?:certain|select|specific)\s+(?:[\w-]+\s+){0,2}?"
    r"(?:VINs?|units|serial|models?|lots?|batch(?:es)?|sizes|colors)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CodeRange:
    prefix: str
    low: int
    high: int
    width: int
    start: str  # the range's first code as printed, to quote the notice

    def contains(self, code: str) -> bool:
        m = re.fullmatch(r"([A-Z]*)(\d+)", code.upper())
        return (
            bool(m)
            and m[1] == self.prefix
            and len(m[2]) == self.width
            and self.low <= int(m[2]) <= self.high
        )


@dataclass(frozen=True)
class DateWindow:
    kind: str  # "expiry" or "production"
    start: date
    end: date


@dataclass(frozen=True)
class Vehicle:
    make: str
    model: str
    years: frozenset[int] | None  # None: all years


@dataclass(frozen=True)
class Scope:
    title: str
    text: str
    codes: dict[str, frozenset[str]] = field(default_factory=dict)
    brands: frozenset[str] = frozenset()
    ranges: tuple[CodeRange, ...] = ()
    windows: tuple[DateWindow, ...] = ()
    vehicles: tuple[Vehicle, ...] = ()
    all_units: bool = False
    open_ranges: tuple[str, ...] = ()  # range phrases that could not be read numerically
    incomplete: str | None = None  # wording that says the code list continues elsewhere
    partial: str | None = None  # wording that limits the recall to units it does not list


@dataclass(frozen=True)
class Facts:
    codes: frozenset[str]  # every code the user gave or the photo showed, canonical
    typed: dict[str, frozenset[str]]  # codes whose kind is known from a label ("Lot #: 123")
    text: str
    brands: frozenset[str] = frozenset()


def _kind(label: str) -> str:
    return "production" if re.match(_PRODUCTION, label, re.I) else "expiry"


def _parse_date(text: str, end: bool = False) -> date | None:
    parts = [int(p) for p in text.split("/")]
    try:
        if len(parts) == 2:  # month/year: a window covers the whole month
            month, year = parts
            day = calendar.monthrange(year, month)[1] if end else 1
            return date(year, month, day)
        month, day, year = parts
        return date(year + 2000 if year < 100 else year, month, day)
    except ValueError:
        return None


def parse_scope(title: str, text: str, identifiers: list[tuple[str, str]], affected=()) -> Scope:
    """Build a recall's scope from its text, stored identifiers and affected-vehicle list."""
    codes: dict[str, set[str]] = {}
    for kind, value in identifiers:
        codes.setdefault(kind, set()).add(value.upper())
    ranges, open_ranges = [], []
    for match in _ANY_RANGE.finditer(text):
        low, high = [g for g in match.groups() if g]
        a, b = (re.fullmatch(r"([A-Z]*)(\d+)", code.upper()) for code in (low, high))
        if a and b and _YEAR.fullmatch(a[2]) and _YEAR.fullmatch(b[2]) and not a[1]:
            continue  # model years, handled with vehicles
        encoded = _ENCODED.search(text[max(0, match.start() - 60) : match.start()])
        numeric = a and b and a[1] == b[1] and len(a[2]) == len(b[2]) and int(a[2]) < int(b[2])
        if numeric and not encoded and _RANGE.fullmatch(match.group()):
            ranges.append(CodeRange(a[1], int(a[2]), int(b[2]), len(a[2]), low))
        else:
            open_ranges.append(match.group())
    windows = []
    for m in _WINDOW.finditer(text):
        start, end = _parse_date(m["start"]), _parse_date(m["end"], end=True)
        if start and end and start <= end:
            windows.append(DateWindow(_kind(m["label"]), start, end))
    makes = sorted(codes.get("brand", ()), key=len, reverse=True)  # LAND ROVER before LAND
    vehicles = []
    for entry in affected:  # "LAND ROVER DEFENDER (2020, 2021)" or "MOPAR BRAKE PEDAL (all years)"
        m = re.fullmatch(r"(\S+ .+) \((.+)\)", entry)
        if m:
            name = m[1]
            make = next((b for b in makes if name.startswith(f"{b} ")), name.split(" ", 1)[0])
            years = frozenset(int(y) for y in re.findall(r"\d{4}", m[2])) or None
            vehicles.append(Vehicle(make, name[len(make) + 1 :], years))
    return Scope(
        title=title,
        text=text,
        codes={kind: frozenset(values) for kind, values in codes.items() if kind != "brand"},
        brands=frozenset(codes.get("brand", ())),
        ranges=tuple(ranges),
        windows=tuple(windows),
        vehicles=tuple(vehicles),
        all_units=bool(_ALL_UNITS.search(text)),
        open_ranges=tuple(open_ranges),
        incomplete=(m := _INCOMPLETE.search(text)) and m.group(),
        partial=(m := _PARTIAL.search(text)) and m.group(),
    )


def _key(code: str) -> str:
    return code.lstrip("0") if code.isdigit() else code.upper()


def _signature(code: str) -> str:
    return re.sub(r"[A-Z]", "A", re.sub(r"\d", "9", code.upper()))


def _sentence(text: str, needle: str) -> str | None:
    """The sentence of the notice that mentions needle, to quote as evidence."""
    for sentence in re.split(r"(?<=[.;])\s+|\n", text):
        if needle.upper() in sentence.upper():
            return sentence.strip()[:240]
    return None


def _words(text: str) -> set[str]:
    """Upper-cased words of three letters or more, crudely singular ("HEATERS" -> "HEATER").

    Letters inside codes are not words: "00000ZRAA6" and "HFK-5115" contribute nothing.
    """
    words = re.findall(r"(?<![A-Z0-9])[A-Z][A-Z'&-]{2,}(?![A-Z0-9])", text.upper())
    return {w[:-1] if w.endswith("S") and len(w) > 3 else w for w in words}


def _product_words(text: str, brand: str | None) -> set[str]:
    """What a text calls the product: its words without noise, question words or the brand."""
    return _words(text) - _TITLE_NOISE - _STOP - _words(brand or "")


def _one_edit(a: str, b: str) -> bool:
    """Whether a and b differ by at most one substitution, insertion or deletion."""
    if len(a) > len(b):
        a, b = b, a
    if len(b) - len(a) > 1:
        return False
    i = next((i for i, (x, y) in enumerate(zip(a, b, strict=False)) if x != y), len(a))
    return a[i + (len(a) == len(b)) :] == b[i + 1 :]


def _brand_match(scope: Scope, facts: Facts) -> str | None:
    """A brand of the recall the person named: all of it, or its first word when distinctive.

    Punctuation is ignored ("Lillie's" names LILLIE), and words of six letters or more survive
    one OCR slip ("POLARS" names POLARIS).
    """
    text = _plain(facts.text)
    words = [w for w in set(text.split()) if len(w) >= 6]
    for brand in sorted(scope.brands):
        tokens = [t for t in _plain(brand).split() if t not in _GENERIC]
        if not tokens:
            continue
        first = tokens[0]
        if f" {' '.join(tokens)} " in text or (len(first) >= 5 and f" {first} " in text):
            return brand
        if len(first) >= 6 and any(_one_edit(first, w) for w in words):
            return brand
        if any(first in other or other in brand for other in facts.brands):
            return brand
    return None


_ASKING = {"IS", "ARE", "DOES", "DO", "CAN", "SHOULD", "WHAT", "WHICH", "MY", "THE", "ANY", "I"}


def possible_match(scope: Scope, facts: Facts) -> bool:
    """A description with no brand the notice lacks, naming the product the recall is about.

    People capitalize brand names: a capitalized name the notice never mentions ("Hydro Flask",
    "Oatly") means the person has another product in mind.
    """
    names = {w.upper() for w in re.findall(r"\b[A-Z][\w'-]*", facts.text)} - _ASKING
    notice = _plain(f"{scope.title} {scope.text}")
    if any(_plain(name) not in notice for name in names):
        return False
    return bool(_product_words(facts.text, None) & _product_words(scope.title, None))


def _plain(text: str) -> str:
    return f" {' '.join(re.sub(r'[^A-Z0-9 ]', ' ', text.upper()).split())} "


def _vehicle_matches(scope: Scope, facts: Facts) -> list[Vehicle]:
    """Affected vehicles the user named; short or numeric model names ("1500") need the make."""
    text = _plain(facts.text)
    matches = []
    for v in scope.vehicles:
        model = _plain(v.model)
        distinctive = len(model.strip().replace(" ", "")) >= 4 and re.search(r"[A-Z]", model)
        if model in text and (distinctive or _plain(v.make) in text):
            matches.append(v)
    return matches


def _user_dates(facts: Facts) -> list[tuple[str, date]]:
    found = []
    for m in _USER_DATE.finditer(facts.text):
        if parsed := _parse_date(m["date"]):
            found.append((_kind(m["label"]), parsed))
    return found


def _mentioned(code: str, text: str) -> bool:
    """Whether the notice prints code as a whole token; extraction can miss list entries."""
    if len(code) < 5 or _YEAR.fullmatch(code):
        return False
    return re.search(rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])", text, re.I) is not None


def _distinctive(kind: str, code: str) -> bool:
    """Codes unlikely to match an unrelated recall by coincidence."""
    if kind in ("upc", "ndc", "vin"):
        return True
    return len(code) >= 8 if code.isdigit() else len(code) >= 6


def verify(scope: Scope, facts: Facts) -> tuple[str, str, str | None]:
    """Return (verdict, reason, evidence quoted from the notice)."""
    listed = {kind: {_key(v) for v in scope.codes.get(kind, ())} for kind in CODE_KINDS}
    typed = {_key(c) for values in facts.typed.values() for c in values}

    def usable(kind: str) -> dict[str, str]:
        """User codes that may be of this kind: labeled as it, or not labeled at all."""
        labeled = {_key(c) for c in facts.typed.get(kind, ())}
        return {_key(c): c for c in facts.codes if _key(c) in labeled or _key(c) not in typed}

    unit_scoped = bool(
        any(listed[k] for k in UNIT_KINDS)
        or scope.ranges
        or scope.windows
        or scope.open_ranges
        or scope.partial
    )

    def mentioned(codes) -> set[str]:
        return {_key(code) for code in codes if _mentioned(code, scope.text)}

    # A code printed in the notice counts even when extraction missed it, unless the notice
    # lists it as another kind; only a label makes a printed code the person's lot.
    unit_listed = set().union(*(listed[kind] for kind in UNIT_KINDS))
    model_hits = listed["model"] & set(usable("model"))
    model_hits |= mentioned(usable("model").values()) - unit_listed
    vehicle_years = any(v.years for v in scope.vehicles)
    brand = _brand_match(scope, facts)

    # 1. The unit's own code is listed or inside a listed range; or its model is listed and the
    #    recall covers every unit of that model (equipment part numbers included). A short code
    #    also needs the brand or model to match, or the match may be a coincidence.
    for kind in UNIT_KINDS:
        user = usable(kind)
        hits = listed[kind] & set(user)
        if kind == "lot":
            hits |= mentioned(facts.typed.get("lot", ())) & set(user)
        for key in sorted(hits):
            code, evidence = user[key], _sentence(scope.text, user[key])
            if _distinctive(kind, code) or brand or model_hits:
                return AFFECTED, f"{kind.upper()} {code} is listed in this recall.", evidence
            return (
                NEEDS_INFO,
                f"{kind.upper()} {code} appears in this recall; is it your product?",
                evidence,
            )
    for code in sorted(usable("lot").values()):
        for r in scope.ranges:
            if r.contains(code):
                reason = f"{code} falls inside a range this recall lists."
                return AFFECTED, reason, _sentence(scope.text, r.start)
    if model_hits and not unit_scoped and not vehicle_years:
        code = usable("model")[sorted(model_hits)[0]]
        return AFFECTED, f"Model {code} is listed in this recall.", _sentence(scope.text, code)

    # 2. Vehicles: the recall names affected models and model years.
    if vehicle_years:
        matched = _vehicle_matches(scope, facts)
        if not matched:
            makes = {v.make for v in scope.vehicles}
            if any(_plain(make) in _plain(facts.text) for make in makes):
                models = ", ".join(sorted({v.model.title() for v in scope.vehicles})[:5])
                return NEEDS_INFO, f"This recall covers {models}; which model is yours?", None
            return UNDETERMINED, "Your vehicle does not appear in this recall's list.", None
        model = matched[0].model.title()
        years = {int(y) for y in _YEAR.findall(facts.text)}
        if any(v.years is None for v in matched):
            return AFFECTED, f"This recall covers every {model}.", None
        if not years:
            return (
                NEEDS_INFO,
                f"This recall covers certain {model} model years; which year is yours?",
                None,
            )
        if any(years & v.years for v in matched):
            return AFFECTED, f"This recall covers your {model} model year.", None
        covered = ", ".join(map(str, sorted(set().union(*(v.years for v in matched)))))
        return NOT_AFFECTED, f"This recall covers {model} model years {covered}, not yours.", None

    # 3. Is this recall about the user's product at all?
    if not (model_hits or brand):
        return (
            UNDETERMINED,
            "Nothing you gave (brand, model or code) ties your product to this recall.",
            None,
        )
    named = _product_words(facts.text, brand)
    same_product = bool(named & _product_words(scope.title, brand))
    if scope.all_units or not (unit_scoped or listed["model"]):
        if model_hits or same_product:
            evidence = _sentence(scope.text, "all ") if scope.all_units else None
            return AFFECTED, "This recall covers every unit of this product.", evidence
        return (
            UNDETERMINED,
            f"This recall is for a {brand.title()} product, but not clearly yours.",
            None,
        )
    if not model_hits and named and not same_product:  # the brand's other products
        return UNDETERMINED, f"This recall is for a different {brand.title()} product.", None

    # 4. A unit-scoped recall of the user's product: compare the unit's date or code.
    for kind, when in _user_dates(facts):
        windows = [w for w in scope.windows if w.kind == kind]
        if windows:
            label = "production date" if kind == "production" else "date"
            if any(w.start <= when <= w.end for w in windows):
                return (
                    AFFECTED,
                    f"Your {label} {when:%m/%d/%Y} falls inside the recalled window.",
                    None,
                )
            return (
                NOT_AFFECTED,
                f"Your {label} {when:%m/%d/%Y} is outside the recalled window.",
                None,
            )
    if scope.open_ranges and (facts.typed.get("lot") or facts.codes):
        phrase = scope.open_ranges[0]
        reason = f'This recall covers a range of codes ("{phrase}") that must be checked by hand.'
        return NEEDS_INFO, reason, _sentence(scope.text, phrase)
    if scope.incomplete and facts.codes:
        phrase = scope.incomplete
        reason = f'This notice lists more codes elsewhere ("{phrase}"); check the full notice.'
        return NEEDS_INFO, reason, _sentence(scope.text, phrase)
    for kind in ("lot", "model", "upc", "ndc"):
        signatures = {_signature(v) for v in scope.codes.get(kind, ())}
        if kind == "lot":
            signatures |= {_signature(r.start) for r in scope.ranges}
        if not signatures:
            continue
        # A bare all-digit code could be a lot or a model; only a label settles its kind.
        inferred = {c for c in facts.codes if _signature(c) in signatures and not c.isdigit()}
        for code in sorted(facts.typed.get(kind, frozenset()) | inferred):
            if _key(code) not in listed[kind] and not _mentioned(code, scope.text):
                return (
                    NOT_AFFECTED,
                    f"{kind.upper()} {code} is not among the ones this recall lists.",
                    None,
                )
    wanted = (
        "VIN"
        if scope.partial and "VIN" in scope.partial.upper()
        else "lot or serial number"
        if listed["lot"] or scope.ranges
        else next(
            (
                k.upper() if k in ("upc", "ndc") else f"{k} number"
                for k in ("model", "upc", "ndc")
                if listed[k]
            ),
            "lot or date code",
        )
    )
    return (
        NEEDS_INFO,
        f"This recall covers specific units; what is the {wanted} on your product?",
        None,
    )
