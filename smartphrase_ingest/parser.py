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
    """
    Returns (SBP, DBP). DBP may be 0 if not available.
    Supports:
      - Systolic blood pressure: 128
      - Systolic BP: 128
      - SBP: 128
      - BP 128/78
      - Any 128/78
    """
    t = raw

    # Explicit systolic-only variants
    m = re.search(r"\b(?:systolic\s+blood\s+pressure|systolic\s*bp|sbp)\s*[:=]?\s*(\d{2,3})\b", t, flags=re.I)
    if m:
        try:
            sbp = int(m.group(1))
            if 50 <= sbp <= 300:
                return sbp, 0
        except Exception:
            pass

    # BP 128/78
    m = re.search(r"\bBP\b[^\d]{0,10}(\d{2,3})\s*/\s*(\d{2,3})\b", t, flags=re.I)
    if m:
        try:
            sbp, dbp = int(m.group(1)), int(m.group(2))
            if 50 <= sbp <= 300 and 30 <= dbp <= 200:
                return sbp, dbp
        except Exception:
            pass

    # Any 128/78
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


def extract_diabetes_flag(raw: str) -> Optional[bool]:
    """
    Stronger diabetes parsing:
      - Diabetes: No / Yes
      - Diabetic: No / Yes
      - Common negations
      - Then keywords like T2DM
    """
    t = raw.lower()

    # explicit fields (highest priority)
    m = re.search(r"\b(diabetes|diabetic)\b\s*[:=]\s*(yes|no|true|false)\b", t)
    if m:
        v = m.group(2)
        return True if v in ("yes", "true") else False

    # standard negations
    if re.search(r"\b(no diabetes|not diabetic|denies diabetes)\b", t):
        return False

    # keyword positives
    if re.search(r"\b(diabetes|t2dm|type 2 diabetes|type ii diabetes)\b", t):
        return True

    return None


def extract_smoking_flags(raw: str) -> Dict[str, Optional[bool]]:
    """
    Smoking parsing with better negation handling.
    """
    t = raw.lower()
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
        or re.search(r"\bsmoker\s*[:=]\s*(yes|true)\b", t)
    ):
        smoker = True
        former_smoker = False

    # also allow "Smoking: No/Yes"
    m = re.search(r"\bsmoking\b\s*[:=]\s*(yes|no|true|false)\b", t)
    if m:
        v = m.group(1)
        smoker = True if v in ("yes", "true") else False
        former_smoker = False if smoker else former_smoker

    return {"smoker": smoker, "former_smoker": former_smoker}


def extract_bool_flags(raw: str) -> Dict[str, Optional[bool]]:
    """
    Boolean flags: diabetes, smoker, former_smoker
    """
    diabetes = extract_diabetes_flag(raw)
    smoke = extract_smoking_flags(raw)
    return {"diabetes": diabetes, **smoke}


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
    # support "BP treated: No/Yes"
    m = re.search(r"\bbp\s*treated\s*[:=]\s*(yes|no|true|false)\b", t)
    if m:
        v = m.group(1)
        return True if v in ("yes","true") else False
    return None


def extract_race_african_american(raw: str) -> Optional[bool]:
    """
    Returns True if patient is African American/Black, False if explicitly not,
    otherwise None.

    Precedence:
      1) Explicit Arnett-style boolean field: "Is Non-Hispanic African American: Yes/No"
      2) Explicit demographics line: "Race/Ethnicity: White (non-Hispanic)" etc
      3) Explicit negations (not black / non-black / not African American)
      4) Generic keyword presence as last resort
    """
    t = raw.lower()

    # 1) Explicit field (MOST IMPORTANT) — must be checked before keyword presence
    m = re.search(
        r"\bis\s*non-?hispanic\s*african\s*american\s*:\s*(yes|no|true|false)\b",
        t,
    )
    if m:
        v = m.group(1)
        return True if v in ("yes", "true") else False

    # 2) Demographics "Race/Ethnicity:" line
    m = re.search(r"\brace\s*/\s*ethnicity\s*:\s*([^\n\r]+)", t)
    if m:
        line = m.group(1)
        # map common cases
        if re.search(r"\bwhite\b", line):
            return False
        if re.search(r"\b(black|african american)\b", line):
            return True
        # if it says "non-hispanic african american: no" elsewhere, we'd have caught it above
        # for other races/ethnicities, leave unknown so we don't misclassify
        return None

    # 3) Explicit negations
    if re.search(r"\b(non[-\s]?black|not black|non[-\s]?african american|not african american)\b", t):
        return False

    # 4) Generic keyword presence (LAST RESORT only)
    if re.search(r"\brace\s*[:=]\s*aa\b", t) or re.search(r"\bethnicity\s*[:=]\s*aa\b", t):
        return True
    if re.search(r"\b(african american|black)\b", t):
        return True

    return None



# ----------------------------
# Family history
# ----------------------------
def extract_fhx(raw: str) -> Tuple[Optional[bool], Optional[str]]:
    """
    Returns (fhx_bool, fhx_text)
    fhx_text is a normalized descriptor the UI can map to a dropdown choice.
    """
    if not raw or not raw.strip():
        return None, None

    t = raw.lower()

    # explicit negative
    if re.search(r"\b(family history|famhx)\b\s*[:=]\s*(none|no|negative)\b", t):
        return False, "None / Unknown"

    # broad string in your test case: "Family history: Father with premature ASCVD <55"
    if re.search(r"\bfather\b.*\b(premature|<\s*55)\b", t):
        return True, "Father with premature ASCVD (MI/stroke/PCI/CABG/PAD) <55"
    if re.search(r"\bmother\b.*\b(premature|<\s*65)\b", t):
        return True, "Mother with premature ASCVD (MI/stroke/PCI/CABG/PAD) <65"
    if re.search(r"\bsibling\b.*\bpremature\b", t):
        return True, "Sibling with premature ASCVD"
    if re.search(r"\bmultiple\b.*\b(first[- ]degree)\b", t):
        return True, "Multiple first-degree relatives"
    if re.search(r"\bfamily history\b.*\bpremature\b", t):
        return True, "Other premature relative"

    return None, None


# ----------------------------
# CAC "not done" detection
# ----------------------------
def extract_cac_not_done(raw: str) -> bool:
    t = raw.lower()
    # any of these implies absence
    return bool(re.search(r"\b(cac|calcium|agatston)\b.*\b(not\s*done|not\s*performed|unknown|n/?a|none)\b", t))


# ----------------------------
# PREVENT helpers: BMI, eGFR, lipid-lowering therapy
# ----------------------------
def extract_bmi(raw: str) -> Optional[float]:
    t = raw.lower()

    # 1) Standard "BMI: 27.4" or "Body mass index: 27.4"
    v = _first_float(r"\b(?:bmi|body\s*mass\s*index)\s*[:=]?\s*(\d{1,2}(?:\.\d+)?)\b", t)
    if v is not None:
        return v

    # 2) Epic narrative: "Body mass index is 38.74 kg/m²."
    v = _first_float(r"\bbody\s*mass\s*index\s+is\s+(\d{1,2}(?:\.\d+)?)\b", t)
    if v is not None:
        return v

    # 3) Epic narrative: "Estimated body mass index is 38.74 kg/m² ..."
    v = _first_float(r"\bestimated\s+body\s*mass\s*index\s+is\s+(\d{1,2}(?:\.\d+)?)\b", t)
    if v is not None:
        return v

    return None



def extract_egfr_with_reason(raw: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Returns (egfr_value, reason_if_missing_or_unreliable)

    Handles:
      - "eGFR: 72" / "estimated GFR 72"
      - Epic unavailability text:
          "eGFR cannot be calculated ( ... older than the maximum 180 days allowed.)"
          "Computed eGFR Cre unavailable..."
    """
    t = raw.lower()

    # 1) Numeric eGFR present (best case)
    v = _first_float(r"\b(?:egfr|estimated\s*gfr)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\b", t)
    if v is None:
        v = _first_float(r"\b(?:gfr)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\b", t)

    if v is not None:
        # Optional sanity guard
        if v < 5 or v > 200:
            return v, "egfr_value_out_of_range_verify"
        return v, None

    # 2) Explicit unavailability reasons (Epic-style)
    # Older than allowable lookback
    if re.search(r"\begfr\b.*\bcannot\s+be\s+calculated\b.*\bolder\b.*\b180\s+days\b", t):
        return None, "egfr_unavailable_older_than_180d"

    # Generic "unavailable" / "not found" phrasing
    if re.search(r"\b(computed\s+egfr|egfr)\b.*\bunavailable\b", t):
        return None, "egfr_unavailable"

    if re.search(r"\begfr\b.*\bno\s+results\s+found\b", t):
        return None, "egfr_not_found"

    # Some systems say "did not fit some other criterion"
    if re.search(r"\begfr\b.*\bdid\s+not\s+fit\b.*\bcriterion\b", t):
        return None, "egfr_unavailable_criteria_not_met"

    # If creatinine clearance is mentioned as not calculable, it often correlates with missing creatinine
    if re.search(r"\bcrcl\b.*\bcannot\s+be\s+calculated\b", t):
        return None, "egfr_unavailable_related_missing_creatinine"

    return None, None


def extract_egfr(raw: str) -> Optional[float]:
    # Backward compatible wrapper so existing callers still work
    v, _reason = extract_egfr_with_reason(raw)
    return v



def extract_lipid_lowering(raw: str) -> Optional[bool]:
    t = raw.lower()

    if re.search(r"\b(not on|no)\s+(a\s+)?(statin|lipid[-\s]?lowering|cholesterol\s+meds)\b", t):
        return False

    if re.search(r"\bon\s+(a\s+)?statin\b", t) or re.search(r"\bstatin\s*(use|therapy)\s*:\s*(yes|true)\b", t):
        return True

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

    # support "On lipid lowering: No/Yes"
    m = re.search(r"\b(on\s+lipid\s*lowering|lipid\s*lowering)\s*[:=]\s*(yes|no|true|false)\b", t)
    if m:
        v = m.group(2)
        return True if v in ("yes","true") else False

    return None


def extract_labs(raw: str) -> Dict[str, Optional[float]]:
    t = raw.lower()  # Normalize case early
    # Broader TC detection: chol, cholesterol, total chol/tc, etc.
    tc = _first_float(
        r"\b(?:total\s*(?:chol(?:esterol)?|tc)|chol(?:esterol)?|tc)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b",
        t
    )
    ldl = _first_float(r"\bldl(?:\s*-\s*c|\s*c|-c)?\s*(?:chol(?:esterol)?)?\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t)
    hdl = _first_float(r"\bhdl(?:\s*-\s*c|\s*c|-c)?\s*(?:chol(?:esterol)?)?\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t)
    tg = _first_float(r"\b(?:triglycerides|trigs|tgs|tg)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t)
    apob = _first_float(r"\b(?:apo\s*b|apob)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t)
    lpa = _first_float(r"\b(?:lp\(a\)|lpa|lipoprotein\s*\(a\))\s*[:=]?\s*(\d{1,6}(?:\.\d+)?)\b", t)
    
    # A1c: table format or inline
    a1c_table = _first_float(
        r"hemoglobin\s*a1c[\s\S]{0,300}?\b\d{1,2}/\d{1,2}/\d{2,4}\s+(\d{1,2}(?:\.\d+)?)\b",
        t,
    )
    a1c_inline = _first_float(r"\b(?:a1c|hba1c|hb\s*a1c)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\s*%?\b", t)
    
    # ASCVD 10y risk
    ascvd = _first_float(r"\bascvd\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\s*%?\b", t)
    
    # CAC score
    cac = _first_float(r"\b(?:cac|coronary\s*artery\s*calcium|calcium\s*score)\s*(?:score)?\s*[:=]?\s*(\d{1,6}(?:\.\d+)?)\b", t)

    return {
        "tc": tc,
        "ldl": ldl,
        "hdl": hdl,
        "tg": tg,
        "apob": apob,
        "lpa": lpa,
        "a1c": a1c_table if a1c_table is not None else a1c_inline,
        "ascvd": ascvd,
        "cac": cac,
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

    # Family history
    fhx_bool, fhx_text = extract_fhx(raw)
    extracted["fhx"] = fhx_bool
    extracted["fhx_text"] = fhx_text

    # CAC not-done logic
    cac_nd = extract_cac_not_done(raw)
    extracted["cac_not_done"] = cac_nd
    if cac_nd:
        # Prefer explicit "not done" over any spurious CAC number matches
        extracted["cac"] = None

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
        ("a1c", "A1c"),
        ("bmi", "BMI (PREVENT)"),
        ("egfr", "eGFR (PREVENT)"),
    ]:
        if extracted.get(key) is None:
            warnings.append(f"{label} not detected")

    # Only warn about CAC if it wasn't explicitly not done
    if extracted.get("cac") is None and not extracted.get("cac_not_done", False):
        warnings.append("CAC not detected")

    return ParseReport(extracted=extracted, warnings=warnings, conflicts=conflicts)


def parse_ascvd_block(raw: str) -> Dict[str, Any]:
    return parse_ascvd_block_with_report(raw).extracted


def parse_smartphrase(raw: str) -> Dict[str, Any]:
    """
    UI adapter: returns exactly what your app expects.
    (Additive keys: fhx, fhx_text, cac_not_done)
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
        "bmi", "egfr", "lipidLowering",
        # new additive keys:
        "fhx", "fhx_text", "cac_not_done",
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

