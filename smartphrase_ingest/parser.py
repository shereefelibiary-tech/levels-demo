# smartphrase_ingest/parser.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List


# ----------------------------
# Public result object
# ----------------------------
@dataclass
class ParseReport:
    extracted: Dict[str, Any]
    warnings: List[str]
    conflicts: List[str]


# ----------------------------
# Small helpers
# ----------------------------
def _to_float(x: str) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None


def _first_float(pattern: str, text: str) -> Optional[float]:
    m = re.search(pattern, text, flags=re.I)
    if not m:
        return None
    return _to_float(m.group(1))


def _first_int(pattern: str, text: str) -> Optional[int]:
    m = re.search(pattern, text, flags=re.I)
    if not m:
        return None
    try:
        return int(float(m.group(1)))
    except Exception:
        return None


# ----------------------------
# Extractors
# ----------------------------
def extract_sex(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (sex, warning)
      sex: "M" | "F" | None
    """
    if not raw or not raw.strip():
        return None, "Sex not detected (empty text)"

    t = raw.lower()
    hits: list[str] = []

    # 1) Explicit: Sex: Male, Gender=f
    explicit = re.findall(r"\b(sex|gender)\s*[:=]\s*(male|female|m|f|man|woman)\b", t)
    for _, val in explicit:
        hits.append(val)

    # 2) Compressed: 57M / 63F and M57
    hits += re.findall(r"\b\d{1,3}\s*([mf])\b", t)
    hits += re.findall(r"\b([mf])\s*\d{1,3}\b", t)

    # 3) Free text words
    if re.search(r"\b(male|man)\b", t):
        hits.append("male")
    if re.search(r"\b(female|woman)\b", t):
        hits.append("female")

    norm: list[str] = []
    for h in hits:
        if h in ("m", "male", "man"):
            norm.append("M")
        elif h in ("f", "female", "woman"):
            norm.append("F")

    if not norm:
        return None, "Sex not detected"
    if "M" in norm and "F" in norm:
        return None, "Sex conflict detected (both male and female found)"

    return ("M" if "M" in norm else "F"), None


def extract_age(raw: str) -> Tuple[Optional[int], Optional[str]]:
    if not raw or not raw.strip():
        return None, "Age not detected (empty text)"

    t = raw

    age = _first_int(r"\bage\s*[:=]\s*(\d{1,3})\b", t)
    if age is None:
        age = _first_int(r"\b(\d{1,3})\s*(yo|y/o|yr|yrs|year|years)\b", t)
    if age is None:
        t2 = t.replace("–", "-").replace("—", "-")
        age = _first_int(r"\b(\d{1,3})\s*-\s*year\s*-\s*old\b", t2)
    if age is None:
        t2 = t.replace("–", "-").replace("—", "-")
        age = _first_int(r"\b(\d{1,3})\s*-\s*year\s*old\b", t2)
    if age is None:
        age = _first_int(r"\b(\d{1,3})\s*(m|f)\b", t)  # 57M / 63F

    if age is None:
        return None, "Age not detected"
    if age < 18 or age > 100:
        return age, "Age looks unusual — please verify"
    return age, None


def extract_bp(raw: str) -> Optional[Tuple[int, int]]:
    m = re.search(r"\b(?:bp\s*)?(\d{2,3})\s*/\s*(\d{2,3})\b", raw, flags=re.I)
    if not m:
        return None
    try:
        return int(m.group(1)), int(m.group(2))
    except Exception:
        return None


def extract_bool_flags(raw: str) -> Dict[str, Optional[bool]]:
    """
    Returns:
      diabetes, smoker, former_smoker
    """
    t = raw.lower()

    diabetes: Optional[bool] = None
    if re.search(r"\b(no diabetes|not diabetic|denies diabetes)\b", t):
        diabetes = False
    if re.search(r"\b(diabetes|t2dm|type 2 diabetes|type ii diabetes)\b", t):
        diabetes = True

    smoker: Optional[bool] = None
    former_smoker: Optional[bool] = None

    if re.search(r"\b(never smoker|non-smoker|nonsmoker|never smoked)\b", t):
        smoker = False
        former_smoker = False
    if re.search(r"\b(former smoker|ex-smoker|quit smoking)\b", t):
        smoker = False
        former_smoker = True
    if re.search(r"\b(current smoker|smoker|smokes)\b", t):
        if not re.search(r"\b(non-smoker|nonsmoker)\b", t):
            smoker = True
            former_smoker = False

    return {"diabetes": diabetes, "smoker": smoker, "former_smoker": former_smoker}


def extract_labs(raw: str) -> Dict[str, Optional[float]]:
    t = raw
    return {
        "tc": _first_float(r"\b(?:total\s*cholesterol|total\s*chol|tc|cholesterol|chol)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "ldl": _first_float(r"\bldl\s*(?:chol(?:esterol)?)?\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "hdl": _first_float(r"\bhdl\s*(?:chol(?:esterol)?)?\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "tg": _first_float(r"\b(?:triglycerides|trigs|tgs|tg)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "apob": _first_float(r"\b(?:apo\s*b|apob)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "lpa": _first_float(r"\b(?:lp\(a\)|lpa|lipoprotein\s*\(a\))\s*[:=]?\s*(\d{1,6}(?:\.\d+)?)\b", t),
        "a1c": _first_float(r"\b(?:a1c|hba1c|hb\s*a1c)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\s*%?\b", t),
        # ASCVD % risk (if present)
        "ascvd": _first_float(r"\bascvd\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\s*%?\b", t),
        "cac": _first_float(r"\b(?:cac|coronary\s*artery\s*calcium|calcium\s*score)\s*(?:score)?\s*[:=]?\s*(\d{1,6}(?:\.\d+)?)\b", t),
    }


def extract_lpa_unit(raw: str) -> Optional[str]:
    """
    Returns 'nmol/L' or 'mg/dL' if explicitly mentioned.
    """
    t = raw.lower()
    # Look near Lp(a) or in general text
    if re.search(r"\b(nmol\/l|nmol\s*\/\s*l)\b", t):
        return "nmol/L"
    if re.search(r"\b(mg\/dl|mg\s*\/\s*dl)\b", t):
        # only trust mg/dL if Lp(a) is mentioned somewhere to avoid generic mg/dL in lipid panel
        if re.search(r"\b(lp\(a\)|lpa|lipoprotein\s*\(a\))\b", t):
            return "mg/dL"
    return None


def extract_bp_treated(raw: str) -> Optional[bool]:
    """
    Attempts to determine if patient is on BP meds / treated HTN.
    """
    t = raw.lower()
    # explicit negations first
    if re.search(r"\b(not on bp meds|no bp meds|no antihypertensive|not taking antihypertensives)\b", t):
        return False
    if re.search(r"\b(on bp meds|bp treated|treated bp|on antihypertensive|taking antihypertensives|on htn meds)\b", t):
        return True
    return None


def extract_race_african_american(raw: str) -> Optional[bool]:
    """
    Returns True if text indicates African American/Black, False if explicitly non-AA,
    None if not mentioned.
    """
    t = raw.lower()

    # Explicit non-AA statements
    if re.search(r"\b(non[-\s]?black|not black|non[-\s]?african american|not african american)\b", t):
        return False

    # Positive
    if re.search(r"\b(african american|black)\b", t):
        return True

    # Shorthand "AA" is too ambiguous medically; only accept if anchored
    if re.search(r"\brace\s*[:=]\s*aa\b", t) or re.search(r"\bethnicity\s*[:=]\s*aa\b", t):
        return True

    return None


# ----------------------------
# Main parse functions
# ----------------------------
def parse_ascvd_block_with_report(raw: str) -> ParseReport:
    """
    Preferred API: returns extracted fields + warnings/conflicts.
    """
    extracted: Dict[str, Any] = {}
    warnings: list[str] = []
    conflicts: list[str] = []

    sex, sex_warn = extract_sex(raw)
    age, age_warn = extract_age(raw)

    extracted["sex"] = sex
    extracted["age"] = age

    if sex_warn:
        if "conflict" in sex_warn.lower():
            conflicts.append(sex_warn)
        else:
            warnings.append(sex_warn)
    if age_warn:
        warnings.append(age_warn)

    bp = extract_bp(raw)
    if bp:
        extracted["sbp"], extracted["dbp"] = bp
    else:
        extracted["sbp"], extracted["dbp"] = None, None
        warnings.append("BP not detected")

    flags = extract_bool_flags(raw)
    extracted.update(flags)

    labs = extract_labs(raw)
    extracted.update(labs)

    # Add these extra signals (used by UI adapter)
    extracted["bpTreated"] = extract_bp_treated(raw)
    extracted["africanAmerican"] = extract_race_african_american(raw)
    extracted["lpa_unit"] = extract_lpa_unit(raw)

    # Diabetes override: A1c >= 6.5 forces diabetes = True
    if labs.get("a1c") is not None and labs["a1c"] >= 6.5:
        if extracted.get("diabetes") is False:
            conflicts.append("Diabetes conflict: text says no diabetes, but A1c ≥ 6.5%")
        extracted["diabetes"] = True

    # Missing-data warnings for key fields
    for key, label in [
        ("ldl", "LDL"),
        ("apob", "ApoB"),
        ("lpa", "Lp(a)"),
        ("cac", "CAC"),
        ("ascvd", "ASCVD 10-year risk"),
        ("a1c", "A1c"),
    ]:
        if extracted.get(key) is None:
            warnings.append(f"{label} not detected")

    return ParseReport(extracted=extracted, warnings=warnings, conflicts=conflicts)


def parse_ascvd_block(raw: str) -> Dict[str, Any]:
    """
    Backward-compatible API used by other callers.
    Returns extracted dict only (no warnings/conflicts).
    """
    return parse_ascvd_block_with_report(raw).extracted


# ----------------------------
# UI adapter (THIS is what your app.py expects)
# ----------------------------
def parse_smartphrase(raw: str) -> Dict[str, Any]:
    """
    Returns a dict shaped to your existing UI expectations.

    Keys used by your UI:
      age, sex, sbp,
      tc, hdl, ldl, apob, lpa, lpa_unit,
      cac, smoker, diabetes, bpTreated, africanAmerican,
      ascvd_10y (percent, if present)
    """
    rep = parse_ascvd_block_with_report(raw)
    x = rep.extracted

    out: Dict[str, Any] = {}

    # direct mappings
    for k in ("age", "sex", "sbp", "tc", "hdl", "ldl", "apob", "lpa", "lpa_unit", "cac", "smoker", "diabetes", "bpTreated", "africanAmerican"):
        if x.get(k) is not None:
            out[k] = x.get(k)

    # UI expects ascvd_10y (not ascvd)
    if x.get("ascvd") is not None:
        out["ascvd_10y"] = x["ascvd"]

    # Keep former_smoker available for future, but not required by your current UI
    if x.get("former_smoker") is not None:
        out["former_smoker"] = x["former_smoker"]

    return out

