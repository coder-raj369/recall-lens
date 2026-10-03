import pytest

from recall_lens.extract.rules import codes, extract

# Snippets taken from real CPSC and openFDA recall text.
CASES = [
    (
        "Lot Number: W+0925  Expiry Date: 09/2027",
        {("lot", "W+0925")},
    ),
    (
        "Lot #: 1276118, 1276119, expires: JAN 2029.",
        {("lot", "1276118"), ("lot", "1276119")},
    ),
    (
        "Model No. A2642; UDI: 04042761004084; All Lots.",
        {("model", "A2642"), ("upc", "04042761004084")},
    ),
    (
        "UDI-DI: 14560189210032; Lot Numbers: FX12404, FY12407, FY12406, FZ12408",
        {("upc", "14560189210032")}
        | {("lot", c) for c in ["FX12404", "FY12407", "FY12406", "FZ12408"]},
    ),
    (
        "This recall involves Matrix Retail models T30, TF30, T50, TF50, and T75 treadmills.",
        {("model", c) for c in ["T30", "TF30", "T50", "TF50", "T75"]},
    ),
    (
        "This recall involves Mangohood Direct-branded children's tower stools, model LT003.",
        {("model", "LT003")},
    ),
    (
        "The recall includes batch numbers 1535 through 1545 and 1200000 through 1202080.",
        {("lot", c) for c in ["1535", "1545", "1200000", "1202080"]},
    ),
    (
        "Lyle Style Mild Bloody Mary Mix, 32oz. glass bottle. UPC code 7 84762 03730 3.",
        {("upc", "784762037303")},
    ),
    (
        "Ophthalmic Solution, 10 mL per dropper bottle, NDC 71384-732-10",
        {("ndc", "71384-732-10")},
    ),
    (
        "all lots/serial numbers manufactured between 02/03/2025 and 02/23/2026",
        set(),
    ),
    (
        "Owners may contact the hotline at 1-888-327-4236.",
        set(),
    ),
    (
        "3L MAX BARRIER CVC BUNDLE, Model Number: ECVC5480; 14) UCLA - FINE NEEDLE BIOPSY",
        {("model", "ECVC5480")},
    ),
    (
        "UV800 Display Unit user interfaces, with part numbers 610-00060-080-51, 610-00060-080-50",
        {("model", "610-00060-080-51"), ("model", "610-00060-080-50")},
    ),
    (
        "NEXT EDGE 85HT Rental model 2016 2017",
        set(),
    ),
    (
        "Lot #:  82886, exp 09/30/2026; 89646, exp 05/31/2027",
        {("lot", "82886"), ("lot", "89646")},
    ),
    (
        "Lot: a) 1505122, 1505343, expires: 2027-04; b) 1505142",
        {("lot", "1505122"), ("lot", "1505343"), ("lot", "1505142")},
    ),
    (
        "LC+200-D: Lot-N4J030 (Exp.9/20/2026), N5D043(Exp.4/16/2027)",
        {("lot", "N4J030"), ("lot", "N5D043")},
    ),
    (
        "Codes: Lot: 335314-335315; Use by 07/13/2026",
        {("lot", "335314"), ("lot", "335315")},
    ),
    (
        "The model numbers are 17249 and 17310 with date codes between 16919 and 11122",
        {("model", "17249"), ("model", "17310"), ("lot", "16919"), ("lot", "11122")},
    ),
    (
        "subject to this recall have the following date codes: 1752VE01, 1782VE01, 0583VE01",
        {("lot", "1752VE01"), ("lot", "1782VE01"), ("lot", "0583VE01")},
    ),
    (
        "Serial Numbers: A2013401, A2013402. Expiration: 2031Dec17",
        {("lot", "A2013401"), ("lot", "A2013402")},
    ),
]


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_extracts_labeled_identifiers(text, expected):
    assert extract(text) == expected


def test_handles_empty_text():
    assert extract(None) == set()
    assert extract("") == set()


def test_codes_take_labeled_and_bare_codes_but_skip_years_and_short_tokens():
    assert codes("Lot #: 82886 buprenorphine") == {"82886"}
    assert codes("2023 Honda CBR600RR engine") == {"CBR600RR"}
    assert codes("upc 0 12345 67890 5") == {"012345678905"}
    assert codes("F1 4x4 truck") == set()
    assert codes("Tel +1 (818) 818-0538, Seatac WA 98188-9993, 3715 S 182ND St") == set()


def test_sizes_and_counts_are_not_codes():
    assert codes("Harppa 5-in-1 convertible high chair, model BHC001") == {"BHC001"}
    assert codes("Pyrex 2-cup measuring cup, 12-drawer dresser, 24-count pack") == set()
    assert codes("Honda 1500-HD and Vornado SH-100") == {"1500-HD", "SH-100"}
    assert extract("models of 5-in-1 high chairs") == set()
    assert extract("Is my 2022 Tesla Model 3 recalled?") == set()  # a name, not a model number
    assert extract("lot 24-A") == {("lot", "24-A")}  # a label still makes a short dashed code
