# smartphrase_ingest/parser.py
import re
from typing import Dict, Any


def parse_number(text: str):
    if not text:
        return None
    m = re.search(r"-?\d+(\.\d+)?", text.replace(",", ""))
    return float(m.group()) if m else None


def parse_yes_no(text: str):
    if not text:
        return None
    t = text.strip().lower()
    if t.startswith("yes"):
        return True
    if t.startswith("no"):
        return False
    return None


def get_line_value(text: str, label: str):
    pattern = rf"^\s*{label}\s*:\s*(.+)$"
    m = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else None


def parse_ascvd_block(text: str) -> Dict[str, Any]:
    out = {
        "ascvd_10y": None,
        "age": None,
        "sex": None,
        "sbp": None,
        "diabetes": None,
        "smoker": None,
        "total_chol": None,
        "hdl": None,
    }

    m = re.search(r"is:\s*([0-9]+(\.[0-9]+)?)\s*%", text, re.I)
    if m:
        out["ascvd_10y"] = float(m.group(1))

    out["age"] = parse_number(get_line_value(text, "Age"))
    out["sex"] = get_line_value(text, "Clinically relevant sex")
    out["sbp"] = parse_number(get_line_value(text, "Systolic Blood Pressure"))
    out["diabetes"] = parse_yes_no(get_line_value(text, "Diabetic"))
    out["smoker"] = parse_yes_no(get_line_value(text, "Tobacco smoker"))
    out["total_chol"] = parse_number(get_line_value(text, "Total Cholesterol"))
    out["hdl"] = parse_number(get_line_value(text, "HDL Cholesterol"))

    return out

