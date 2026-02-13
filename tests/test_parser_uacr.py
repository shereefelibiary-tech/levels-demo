from smartphrase_ingest.parser import extract_uacr, extract_uacr_with_reason


def test_extract_uacr_with_less_than_comparator():
    value, warning = extract_uacr("Urine albumin/creatinine ratio: <5 mg/g")
    assert value == 5.0
    assert warning == "UACR reported as < value; numeric floor captured"


def test_extract_uacr_with_greater_than_comparator():
    value, warning = extract_uacr("ACR > 300")
    assert value == 300.0
    assert warning == "UACR reported as > value; numeric threshold captured"


def test_extract_uacr_with_reason_maps_lt_warning_code():
    value, reason = extract_uacr_with_reason("UACR <5")
    assert value == 5.0
    assert reason == "uacr_lt_threshold_captured"
