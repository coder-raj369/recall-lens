from recall_lens.perception import vin


def test_check_digit_validation():
    assert vin.is_valid("1HGCM82633A004352")
    assert not vin.is_valid("1HGCM82643A004352")  # check digit wrong
    assert not vin.is_valid("1HGCM82633A00435")  # too short


def test_find_repairs_ocr_confusions_and_spaces():
    text = "Manufactured Date 12/2021 LOSSCHL 17MT120129 MADE IN CHINA"
    assert vin.find(text) == {"L0SSCHL17MT120129"}
    assert vin.find("Model TK110ATV-1 serial 20240101ABCDEFG1") == set()


def test_decode_reads_vpic_values(monkeypatch):
    payload = {"Results": [{"Make": "HONDA", "Model": "Accord", "ModelYear": "2003"}]}
    monkeypatch.setattr(vin, "get_json", lambda url, params: payload)
    assert vin.decode("1HGCM82633A004352") == {"make": "HONDA", "model": "Accord", "year": "2003"}
    monkeypatch.setattr(vin, "get_json", lambda url, params: {"Results": [{"Make": ""}]})
    assert vin.decode("L0SSCHL17MT120129") == {"make": None, "model": None, "year": None}
