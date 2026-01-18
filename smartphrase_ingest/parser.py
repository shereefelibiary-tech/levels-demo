# smartphrase_ingest/parser.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List


@dataclass
class ParseReport:
    extracted: Dict[str, Any]
    warnings: List[str]
    conflicts: List[str]


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
    Supports:
      - Sex: Male / Gender=f
      - 57M / 63F / M57
      - "57 yo male"
      - "47 y/o M"
    """
    if not raw or not raw.strip():
        return None, "Sex not detected (empty text)"

    t = raw.lower()
    hits: list[str] = []

    explicit = re.findall(r"\b(sex|gender)\s*[:=]\s*(male|female|m|f|man|woman)\b", t)
    for _, val in explicit:
        hits.append(val)

    hits += re.findall(r"\b\d{1,3}\s*([mf])\b", t)
    hits += re.findall(r"\b([mf])\s*\d{1,3}\b", t)
    hits += re.findall(r"\b\d{1,3}\s*(?:yo|y/o|yr|yrs|year|years)\s*([mf])\b", t)

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
        age = _first_int(r"\b(\d{1,3})\s*(m|f)\b", t)

    if age is None:
        return None, "Age not detected"
    if age < 18 or age > 100:
        return age, "Age looks unusual — please verify"
    return age, None


def extract_bp(raw: str) -> Optional[Tuple[int, int]]:
    t = raw

    m = re.search(r"\bsystolic\s+blood\s+pressure\s*:\s*(\d{2,3})\b", t, flags=re.I)
    if m:
        try:
            sbp = int(m.group(1))
            return sbp, 0
        except Exception:
            pass

    m = re.search(r"\bBP\b[^\d]{0,10}(\d{2,3})\s*/\s*(\d{2,3})\b", t, flags=re.I)
    if m:
        try:
            sbp, dbp = int(m.group(1)), int(m.group(2))
            if 50 <= sbp <= 300 and 30 <= dbp <= 200:
                return sbp, dbp
        except Exception:
            pass

    for m in re.finditer(r"\b(\d{2,3})\s*/\s*(\d{2,3})\b", t):
        try:
            sbp, dbp = int(m.group(1)), int(m.group(2))
        except Exception:
            continue
        if sbp <= 31 and dbp <= 31:
            continue
        if 50 <= sbp <= 300 and 30 <= dbp <= 200:
            return sbp, dbp

    return None


def extract_bool_flags(raw: str) -> Dict[str, Optional[bool]]:
    """
    FIXES:
      - Diabetes negation should not be overwritten by generic 'diabetes' token.
      - Smoking: 'Tobacco smoker: No' and 'Smoking status: Never' should not set smoker=True.
    """
    t = raw.lower()

    diabetes: Optional[bool] = None
    if re.search(r"\b(no diabetes|not diabetic|denies diabetes)\b", t):
        diabetes = False
    elif re.search(r"\b(diabetes|t2dm|type 2 diabetes|type ii diabetes)\b", t):
        diabetes = True

    smoker: Optional[bool] = None
    former_smoker: Optional[bool] = None

    if re.search(r"\btobacco\s*smoker\s*:\s*(no|false)\b", t):
        smoker = False
        former_smoker = False
    elif re.search(r"\bsmoking\s*status\s*:\s*never\b", t):
        smoker = False
        former_smoker = False
    elif re.search(r"\b(never smoker|non-?smoker|nonsmoker|never smoked)\b", t):
        smoker = False
        former_smoker = False
    elif re.search(r"\b(former smoker|ex-smoker|quit smoking)\b", t):
        smoker = False
        former_smoker = True
    elif (
        re.search(r"\btobacco\s*smoker\s*:\s*(yes|true)\b", t)
        or re.search(r"\bcurrent smoker\b", t)
        or re.search(r"\bsmoking\s*status\s*:\s*every day\b", t)
        or re.search(r"\bsmoking\s*status\s*:\s*some days\b", t)
    ):
        smoker = True
        former_smoker = False

    return {"diabetes": diabetes, "smoker": smoker, "former_smoker": former_smoker}


def extract_lpa_unit(raw: str) -> Optional[str]:
    t = raw.lower()
    m = re.search(r"(lp\(a\)|lpa|lipoprotein\s*\(a\)).{0,30}", t)
    window = m.group(0) if m else t

    if re.search(r"\b(nmol\/l|nmol\s*\/\s*l)\b", window):
        return "nmol/L"
    if re.search(r"\b(mg\/dl|mg\s*\/\s*dl)\b", window):
        return "mg/dL"
    return None


def extract_bp_treated(raw: str) -> Optional[bool]:
    t = raw.lower()
    if re.search(r"\b(not on bp meds|no bp meds|no antihypertensive|not taking antihypertensives)\b", t):
        return False
    if re.search(r"\b(on bp meds|bp treated|treated bp|on antihypertensive|taking antihypertensives|on htn meds)\b", t):
        return True
    if re.search(r"\bis\s*bp\s*treated\s*:\s*(no|false)\b", t):
        return False
    if re.search(r"\bis\s*bp\s*treated\s*:\s*(yes|true)\b", t):
        return True
    return None


def extract_race_african_american(raw: str) -> Optional[bool]:
    t = raw.lower()
    if re.search(r"\b(non[-\s]?black|not black|non[-\s]?african american|not african american)\b", t):
        return False
    if re.search(r"\b(african american|black)\b", t):
        return True
    if re.search(r"\brace\s*[:=]\s*aa\b", t) or re.search(r"\bethnicity\s*[:=]\s*aa\b", t):
        return True
    if re.search(r"\bis\s*non-?hispanic\s*african\s*american\s*:\s*(yes|true)\b", t):
        return True
    if re.search(r"\bis\s*non-?hispanic\s*african\s*american\s*:\s*(no|false)\b", t):
        return False
    return None


# ----------------------------
# PREVENT helpers: BMI, eGFR, lipid-lowering therapy
# ----------------------------
def extract_bmi(raw: str) -> Optional[float]:
    """
    Attempts to capture BMI from common formats:
      - BMI: 28.4
      - Body Mass Index 28.4
      - "BMI 28.4"
    """
    t = raw
    return _first_float(r"\b(?:bmi|body\s*mass\s*index)\s*[:=]?\s*(\d{1,2}(?:\.\d+)?)\b", t)


def extract_egfr(raw: str) -> Optional[float]:
    """
    Attempts to capture eGFR from common formats:
      - eGFR: 72
      - EGFR 72
      - Estimated GFR 72
    """
    t = raw
    v = _first_float(r"\b(?:eGFR|egfr|estimated\s*gfr)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\b", t)
    if v is None:
        # Sometimes appears as "GFR 72"
        v = _first_float(r"\b(?:gfr)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\b", t)
    return v


def extract_lipid_lowering(raw: str) -> Optional[bool]:
    """
    Best-effort detection of lipid-lowering therapy use.

    Returns:
      True  -> clear evidence of statin/ezetimibe/PCSK9/etc or "on statin"
      False -> explicit negation like "not on statin"
      None  -> unknown
    """
    t = raw.lower()

    # explicit negation first
    if re.search(r"\b(not on|no)\s+(a\s+)?(statin|lipid[-\s]?lowering|cholesterol\s+meds)\b", t):
        return False

    # explicit yes
    if re.search(r"\bon\s+(a\s+)?statin\b", t) or re.search(r"\bstatin\s*(use|therapy)\s*:\s*(yes|true)\b", t):
        return True

    # med list hits (broad but still specific)
    meds = [
        r"atorvastatin", r"rosuvastatin", r"simvastatin", r"pravastatin", r"lovastatin",
        r"pitavastatin", r"fluvastatin",
        r"ezetimibe", r"zetia",
        r"evolocumab", r"repatha", r"alirocumab", r"praluent",
        r"inclisiran", r"leqvio",
        r"bempedoic", r"nexletol",
    ]
    if any(re.search(rf"\b{m}\b", t) for m in meds):
        return True

    return None


def extract_labs(raw: str) -> Dict[str, Optional[float]]:
    """
    FIXES:
      - A1c should be captured from Epic table format:
        "Hemoglobin A1C ... 01/05/2026  5.7 (H)"
      - LDL-C variants like "LDL-C: 128"
    """
    t = raw

    a1c_table = _first_float(
        r"hemoglobin\s*a1c[\s\S]{0,300}?\b\d{1,2}/\d{1,2}/\d{2,4}\s+(\d{1,2}(?:\.\d+)?)\b",
        t,
    )
    a1c_inline = _first_float(r"\b(?:a1c|hba1c|hb\s*a1c)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\s*%?\b", t)

    return {
        "tc": _first_float(r"\b(?:total\s*cholesterol|total\s*chol|tc|cholesterol|chol)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "ldl": _first_float(r"\bldl(?:\s*-\s*c|\s*c|-c)?\s*(?:chol(?:esterol)?)?\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "hdl": _first_float(r"\bhdl(?:\s*-\s*c|\s*c|-c)?\s*(?:chol(?:esterol)?)?\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "tg": _first_float(r"\b(?:triglycerides|trigs|tgs|tg)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "apob": _first_float(r"\b(?:apo\s*b|apob)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "lpa": _first_float(r"\b(?:lp\(a\)|lpa|lipoprotein\s*\(a\))\s*[:=]?\s*(\d{1,6}(?:\.\d+)?)\b", t),
        "a1c": a1c_table if a1c_table is not None else a1c_inline,
        "ascvd": _first_float(r"\bascvd\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\s*%?\b", t),
        "cac": _first_float(r"\b(?:cac|coronary\s*artery\s*calcium|calcium\s*score)\s*(?:score)?\s*[:=]?\s*(\d{1,6}(?:\.\d+)?)\b", t),
    }


# ----------------------------
# Main parse functions
# ----------------------------
def parse_ascvd_block_with_report(raw: str) -> ParseReport:
    extracted: Dict[str, Any] = {}
    warnings: list[str] = []
    conflicts: list[str] = []

    sex, sex_warn = extract_sex(raw)
    age, age_warn = extract_age(raw)

    extracted["sex"] = sex
    extracted["age"] = age

    if sex_warn:
        (conflicts if "conflict" in sex_warn.lower() else warnings).append(sex_warn)
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

    extracted["bpTreated"] = extract_bp_treated(raw)
    extracted["africanAmerican"] = extract_race_african_american(raw)
    extracted["lpa_unit"] = extract_lpa_unit(raw)

    # PREVENT-related
    extracted["bmi"] = extract_bmi(raw)
    extracted["egfr"] = extract_egfr(raw)
    extracted["lipidLowering"] = extract_lipid_lowering(raw)

    # Diabetes override: A1c >= 6.5 forces diabetes = True
    if labs.get("a1c") is not None and labs["a1c"] >= 6.5:
        if extracted.get("diabetes") is False:
            conflicts.append("Diabetes conflict: text says no diabetes, but A1c ≥ 6.5%")
        extracted["diabetes"] = True

    for key, label in [
        ("ldl", "LDL"),
        ("apob", "ApoB"),
        ("lpa", "Lp(a)"),
        ("lpa_unit", "Lp(a) unit"),
        ("cac", "CAC"),
        ("ascvd", "ASCVD 10-year risk"),
        ("a1c", "A1c"),
        # PREVENT
        ("bmi", "BMI (PREVENT)"),
        ("egfr", "eGFR (PREVENT)"),
    ]:
        if extracted.get(key) is None:
            warnings.append(f"{label} not detected")

    return ParseReport(extracted=extracted, warnings=warnings, conflicts=conflicts)


def parse_ascvd_block(raw: str) -> Dict[str, Any]:
    return parse_ascvd_block_with_report(raw).extracted


def parse_smartphrase(raw: str) -> Dict[str, Any]:
    """
    UI adapter: returns exactly what your app expects.
    """
    rep = parse_ascvd_block_with_report(raw)
    x = rep.extracted

    out: Dict[str, Any] = {}

    keys = (
        "age", "sex", "sbp",
        "tc", "hdl", "ldl",
        "apob", "lpa", "lpa_unit",
        "cac",
        "a1c",
        "smoker", "diabetes",
        "bpTreated", "africanAmerican",
        # PREVENT additions:
        "bmi", "egfr", "lipidLowering",
    )
    for k in keys:
        if x.get(k) is not None:
            out[k] = x.get(k)

    # UI expects ascvd_10y
    if x.get("ascvd") is not None:
        out["ascvd_10y"] = x["ascvd"]

    if x.get("former_smoker") is not None:
        out["former_smoker"] = x["former_smoker"]

    return out

