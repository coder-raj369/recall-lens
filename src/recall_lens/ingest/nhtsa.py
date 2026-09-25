"""NHTSA vehicle and equipment recalls from the bulk recall flat file.

The Recalls API only answers per make/model/year, so the corpus is built from the published
flat file (one row per campaign x component x vehicle) and grouped into one Recall per campaign.
Field layout: https://static.nhtsa.gov/odi/ffdd/rcl/RCL.txt
"""

import csv
import io
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import date, datetime

from recall_lens.ingest.http import fetch as http_fetch
from recall_lens.ingest.models import Recall, identifier

FLAT_FILE_URL = "https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_POST_2010.zip"
FIRST_YEAR = 2010  # the post-2010 file holds records created from 2010 onward
RECALL_URL = "https://www.nhtsa.gov/recalls?nhtsaId={campaign}"
MAX_AFFECTED_LISTED = 50

FIELDS = [
    "RECORD_ID", "CAMPNO", "MAKETXT", "MODELTXT", "YEARTXT", "MFGCAMPNO", "COMPNAME", "MFGNAME",
    "BGMAN", "ENDMAN", "RCLTYPECD", "POTAFF", "ODATE", "INFLUENCED_BY", "MFGTXT", "RCDATE",
    "DATEA", "RPNO", "FMVSS", "DESC_DEFECT", "CONEQUENCE_DEFECT", "CORRECTIVE_ACTION", "NOTES",
    "RCL_CMPT_ID", "MFR_COMP_NAME", "MFR_COMP_DESC", "MFR_COMP_PTNO", "DO_NOT_DRIVE",
    "PARK_OUTSIDE",
]  # fmt: skip
PRODUCT_TYPES = {"V": "vehicle", "E": "equipment", "C": "child_restraint", "T": "tire"}
UNKNOWN_YEAR = "9999"


def fetch(since: date, until: date | None = None) -> Iterator[Recall]:
    """Yield campaigns whose defect report was received between since and until."""
    if since.year < FIRST_YEAR:
        raise ValueError(f"the NHTSA flat file used here starts in {FIRST_YEAR}")
    archive = zipfile.ZipFile(io.BytesIO(http_fetch(FLAT_FILE_URL, timeout=300)))
    with archive.open(archive.namelist()[0]) as raw:
        yield from parse(io.TextIOWrapper(raw, encoding="utf-8"), since, until or date.today())


def parse(lines: Iterable[str], since: date, until: date) -> Iterator[Recall]:
    start, end = f"{since:%Y%m%d}", f"{until:%Y%m%d}"
    campaigns: dict[str, list[dict]] = defaultdict(list)
    for values in csv.reader(lines, delimiter="\t", quoting=csv.QUOTE_NONE):
        row = dict(zip(FIELDS, values, strict=True))
        if start <= row["RCDATE"] <= end:
            campaigns[row["CAMPNO"]].append(row)
    for rows in campaigns.values():
        yield normalize(rows)


def _affected(rows: list[dict]) -> list[str]:
    years: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        years[(row["MAKETXT"], row["MODELTXT"])].add(row["YEARTXT"])
    return [
        f"{make} {model} ({', '.join(sorted(ys - {UNKNOWN_YEAR})) or 'all years'})"
        for (make, model), ys in sorted(years.items())
    ]


def normalize(rows: list[dict]) -> Recall:
    """Collapse one campaign's rows into a Recall."""
    first = rows[0]
    affected = _affected(rows)
    listed = affected[:MAX_AFFECTED_LISTED]
    if len(affected) > len(listed):
        listed.append(f"and {len(affected) - len(listed)} more")

    ids = set()
    for row in rows:
        ids |= {identifier("brand", row["MAKETXT"]), identifier("model", row["MODELTXT"])}
        ids.add(identifier("model", row["MFR_COMP_PTNO"]))
        if row["YEARTXT"] != UNKNOWN_YEAR:
            ids.add(identifier("year", row["YEARTXT"]))

    hazard = first["CONEQUENCE_DEFECT"].strip()
    if first["DO_NOT_DRIVE"] == "Yes":
        hazard = f"DO NOT DRIVE advisory. {hazard}"
    elif first["PARK_OUTSIDE"] == "Yes":
        hazard = f"PARK OUTSIDE advisory. {hazard}"

    campaign_fields = {
        k: v for k, v in first.items() if k not in {"MAKETXT", "MODELTXT", "YEARTXT"}
    }
    return Recall(
        agency="nhtsa",
        source_id=first["CAMPNO"],
        title=f"{first['MFGNAME']} recall: {first['COMPNAME'].title()}",
        description="\n".join(
            filter(None, [first["DESC_DEFECT"].strip(), "Affected: " + "; ".join(listed)])
        ),
        hazard=hazard or None,
        remedy=first["CORRECTIVE_ACTION"].strip() or None,
        product_type=PRODUCT_TYPES.get(first["RCLTYPECD"], "vehicle"),
        recall_date=datetime.strptime(first["RCDATE"], "%Y%m%d").date(),
        source_url=RECALL_URL.format(campaign=first["CAMPNO"]),
        raw=campaign_fields | {"affected": affected},
        identifiers=frozenset(ids - {None}),
    )
