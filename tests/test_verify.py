"""Verifier rules on scope wording taken from real CPSC, FDA and NHTSA notices."""

import pytest

from recall_lens.agents.state import AFFECTED, NEEDS_INFO, NOT_AFFECTED, UNDETERMINED
from recall_lens.agents.verify import Facts, parse_scope, verify
from recall_lens.extract import rules


def facts(text):
    """What the identify node would pass: all codes, labeled codes by kind, and the text."""
    typed = {}
    for kind, value in rules.extract(text):
        typed.setdefault(kind, set()).add(value)
    return Facts(
        codes=frozenset(rules.codes(text)),
        typed={k: frozenset(v) for k, v in typed.items()},
        text=text,
    )


ANTACID = parse_scope(
    "CAREone, EXTRA STRENGTH CALCIUM ANTACID, Calcium Carbonate 750 mg, 96 chewable Tablets",
    "Codes: Lot #: 1276118, 1276119, expires: JAN 2029.",
    [("lot", "1276118"), ("lot", "1276119"), ("brand", "CAREONE")],
)
DUMBBELLS = parse_scope(
    "Acme Recalls Adjustable Dumbbells Due to Impact Hazard",
    "This recall involves 5lbs dumbbells, model 8361, with serial numbers KK23288361 through "
    "KK23388361 and KK20760836 through KK21347836 only.",
    [("model", "8361"), ("brand", "ACME")],
)
KITS = parse_scope(
    "Medline Convenience Kits: 1) WMC I D PACK-LF",
    "Codes: UDI/DI 10888277680371 (each), All Lots",
    [("upc", "10888277680371"), ("brand", "MEDLINE")],
)
SALAD = parse_scope(
    "Kroger Garden Salad Kit, 12 oz bag",
    "Codes: Sell By Dates between 10/17/25 and 11/9/25",
    [("brand", "KROGER")],
)
BEANS = parse_scope(
    "Green Giant French Beans",
    "Codes: Best by dates:  12/2025 through 05/2027",
    [("brand", "GREEN GIANT")],
)
TRANSIT = parse_scope(
    "Ford Motor Company recall: Structure:Frame And Members",
    "Ford is recalling certain 2023-2024 Transit vehicles.",
    [("brand", "FORD"), ("model", "TRANSIT"), ("year", "2023"), ("year", "2024")],
    affected=["FORD TRANSIT (2023, 2024)"],
)
PEDALS = parse_scope(
    "Chrysler (FCA US, LLC) recall: Service Brakes, Hydraulic:Pedals And Linkages",
    "Chrysler is recalling certain MOPAR Brake Pedal Assemblies with part number 68607178AA.",
    [("brand", "MOPAR"), ("model", "68607178AA")],
    affected=["MOPAR BRAKE PEDAL ASSEMBLY (all years)"],
)
HUFFY = parse_scope(
    "Huffy Recalls Torex UTV Ride-On Toys Due to Fire Hazard",
    "The model numbers are 17249 and 17310 with date codes between 16919 and 11122.",
    [
        ("brand", "HUFFY"),
        ("model", "17249"),
        ("model", "17310"),
        ("lot", "16919"),
        ("lot", "11122"),
    ],
)
BED_RAILS = parse_scope(
    "ELENKER Portable Bed Rails Recalled Due to Risk of Serious Injury or Death",
    "Model HFK-5115 (SKU K90002C1) and Model HFK-5116 (SKU K90001C1) bed rails.",
    [("brand", "ELENKER"), ("model", "HFK-5115"), ("model", "HFK-5116"),
     ("model", "K90002C1"), ("model", "K90001C1")],
)  # fmt: skip
SAXAGLIPTIN = parse_scope(
    "Saxagliptin Tablets, USP, 2.5mg, Glenmark",
    "Codes: 30-Count Bottle Lots: 17241788, exp. date Sep-26 17241821, exp. date Sep-26 "
    "17241822, exp. date Sep-26",
    [("lot", "17241788"), ("lot", "17241822"), ("brand", "GLENMARK")],  # extraction missed one
)
SAUCE = parse_scope(
    "Lillie's Q Buffalo Wing Sauce",
    "Lillie's Q Buffalo Wing Sauce. Codes: Lot #002125, BEST BY: JAN/21/2026 Lot #002025",
    [("brand", "LILLIE"), ("lot", "002125"), ("lot", "002025")],
)
RANGER = parse_scope(
    "Polaris Industries Recalls Ranger XD 1500 Recreational Off-Road Vehicles",
    "This recall involves Polaris RANGER XD 1500 vehicles.",
    [("brand", "POLARIS")],
)
DEFENDER = parse_scope(
    "Jaguar Land Rover recall: Seats",
    "Land Rover is recalling certain Defender vehicles.",
    [("brand", "LAND ROVER"), ("brand", "NEW FLYER")],
    affected=["LAND ROVER DEFENDER (2020, 2021)", "NEW FLYER XE40 (2020)"],
)
FILTERS = parse_scope("Britax Recalls Car Seats", "Britax car seat recall.", [("brand", "BRITAX")])
KITS_LIST = parse_scope(
    "Medline Convenience Kits",
    "Medline Kits labeled as CH OPEN HEART, ADULT CARDIAC KIT, Etc. (see recall documents for a "
    "full list of products) Codes: Medline Kit Number/SKU DYNJ04879M, DYNJ04893I",
    [("brand", "MEDLINE"), ("model", "DYNJ04879M"), ("model", "DYNJ04893I")],
)
PUMP_UNIT = parse_scope(
    "Power Unit",
    "Codes: Lot Code: US Model No 107760; UDI-DI 05415067038258, "
    "For Lot Numbers, see Attachment F.",
    [("model", "107760"), ("upc", "05415067038258")],
)


@pytest.mark.parametrize(
    ("scope", "text", "expected"),
    [
        # Listed lots: the unit's own code decides.
        (ANTACID, "CAREone antacid, Lot # 1276118", AFFECTED),
        (ANTACID, "CAREone antacid, Lot # 1276125", NOT_AFFECTED),
        (ANTACID, "CAREone antacid", NEEDS_INFO),
        (ANTACID, "CAREone antacid 1276125", NEEDS_INFO),  # unlabeled digits could be anything
        # Serial ranges.
        (DUMBBELLS, "Acme dumbbell serial KK23300000", AFFECTED),
        (DUMBBELLS, "Acme dumbbell serial KK23400000", NOT_AFFECTED),
        (DUMBBELLS, "Acme dumbbells", NEEDS_INFO),
        # "All lots": every unit of the product, if it is the product.
        (KITS, "Medline pack kit", AFFECTED),
        (KITS, "Medline exam gloves", UNDETERMINED),
        # Date windows, by day and by month.
        (SALAD, "Kroger salad kit, sell by 10/20/25", AFFECTED),
        (SALAD, "Kroger salad kit, sell by 11/15/25", NOT_AFFECTED),
        (BEANS, "Green Giant beans best by 01/15/2026", AFFECTED),
        (BEANS, "Green Giant beans best by 06/01/2027", NOT_AFFECTED),
        # Vehicles: model and model year.
        (TRANSIT, "2024 Ford Transit", AFFECTED),
        (TRANSIT, "2022 Ford Transit", NOT_AFFECTED),
        (TRANSIT, "my Ford Transit", NEEDS_INFO),
        (TRANSIT, "2021 Ford Escape", NEEDS_INFO),
        (TRANSIT, "2021 Honda Civic", UNDETERMINED),
        # Equipment part numbers cover every unit of that part.
        (PEDALS, "Mopar brake pedal 68607178AA", AFFECTED),
        # Model lists.
        (BED_RAILS, "ELENKER bed rail model HFK-5116", AFFECTED),
        (BED_RAILS, "ELENKER bed rail HFK-5120", NOT_AFFECTED),
        (BED_RAILS, "a portable bed rail", UNDETERMINED),
        # Encoded or unreadable ranges: endpoints are not the whole list, so never "not affected".
        (HUFFY, "Huffy Torex ride-on model 17249 date code 20120", NEEDS_INFO),
        (HUFFY, "Huffy Torex ride-on model 17249 date code 16919", AFFECTED),
        # A code labeled as a model is not compared with lots; a short lot alone needs the brand.
        (ANTACID, "Huffy ride-on, model 1276118", UNDETERMINED),
        (parse_scope("Pump kit", "Lot 17249", [("lot", "17249")]), "ride-on toy 17249", NEEDS_INFO),
        # Code lists that continue in an attachment or elsewhere cannot rule a unit out.
        (KITS_LIST, "Medline kit number DYNJ04879M", AFFECTED),
        (KITS_LIST, "Medline kit number DYNJ09999Z", NEEDS_INFO),
        (PUMP_UNIT, "power unit model 107760, lot 22A0417", NEEDS_INFO),
        (DUMBBELLS, "Acme dumbbell serial KK23400000", NOT_AFFECTED),  # a complete list still can
        # A code the notice prints counts even when extraction missed it.
        (SAXAGLIPTIN, "Glenmark saxagliptin 2.5 mg, lot 17241821", AFFECTED),
        (SAXAGLIPTIN, "Glenmark saxagliptin 2.5 mg, lot 17241830", NOT_AFFECTED),
        (BED_RAILS, "ELENKER bed rail model HFK-5115", AFFECTED),
        # Brands survive punctuation and one OCR slip; vehicle makes can be several words.
        (SAUCE, "Lillie's Q buffalo wing sauce, lot 002125", AFFECTED),
        (RANGER, "RANGER | POLARS", AFFECTED),
        (DEFENDER, "2021 Land Rover Defender", AFFECTED),
        (DEFENDER, "2019 Land Rover Defender", NOT_AFFECTED),
        (DEFENDER, "my new Honda Civic", UNDETERMINED),  # "new" is not the make NEW FLYER
        (FILTERS, "Brita water filter pitcher", UNDETERMINED),  # short words need an exact match
    ],
)
def test_verdicts(scope, text, expected):
    verdict, reason, _ = verify(scope, facts(text))
    assert verdict == expected, reason


def test_evidence_quotes_the_notice():
    verdict, reason, evidence = verify(ANTACID, facts("CAREone Lot # 1276118"))
    assert verdict == AFFECTED and "1276118" in reason
    assert evidence == "Codes: Lot #: 1276118, 1276119, expires: JAN 2029."


def test_scope_parsing_ignores_lists_ndcs_years_and_qualified_all_lots():
    scope = parse_scope(
        "Pump",
        "Models 1234 and 5678, NDC 0517-9302-01, 2021 through 2023 model years. "
        "All lots manufactured through Oct 2024. All products are intended to be stored frozen.",
        [],
    )
    assert scope.ranges == () and not scope.all_units
    assert [(r.prefix, r.low, r.high) for r in DUMBBELLS.ranges] == [
        ("KK", 23288361, 23388361),
        ("KK", 20760836, 21347836),
    ]
    assert parse_scope("x", "Lot numbers between 200379 and 205050", []).ranges[0].high == 205050
    assert HUFFY.ranges == () and HUFFY.open_ranges == ("between 16919 and 11122",)
    ascending = parse_scope("x", "date codes between 11122 and 16919", [])
    assert ascending.ranges == () and ascending.open_ranges  # encoded, never read numerically
    assert KITS.all_units and parse_scope("x", "All lots within expiry", []).all_units
