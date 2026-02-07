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

    Priority order:
      1) "Clinically relevant sex:" (Epic PCE block)
      2) Explicit "Sex:" / "Gender:" / "Biological sex:" / "Sex assigned at birth:"
      3) Compact forms: 57F, F57, "57 yo female", etc
      4) Generic keywords as last resort

    If both M and F appear, flags conflict only when high-signal evidence conflicts.
    """
    if not raw or not raw.strip():
        return None, "Sex not detected (empty text)"

    t = raw.lower()

    def _norm(val: str) -> Optional[str]:
        v = (val or "").strip().lower()
        if v in ("m", "male", "man"):
            return "M"
        if v in ("f", "female", "woman"):
            return "F"
        return None

    # 1) Highest priority: Epic-style field
    m = re.search(
        r"\bclinically\s+relevant\s+sex\s*:\s*(male|female|m|f|man|woman)\b",
        t,
        flags=re.I,
    )
    if m:
        sex = _norm(m.group(1))
        if sex:
            return sex, None

    # 2) High-signal explicit fields
    explicit_fields = [
        r"\bsex\s*assigned\s*at\s*birth\s*[:=]\s*(male|female|m|f|man|woman)\b",
        r"\bbiological\s+sex\s*[:=]\s*(male|female|m|f|man|woman)\b",
        r"\bsex\s*[:=]\s*(male|female|m|f|man|woman)\b",
        r"\bgender\s*[:=]\s*(male|female|m|f|man|woman)\b",
    ]
    for pat in explicit_fields:
        m = re.search(pat, t, flags=re.I)
        if m:
            sex = _norm(m.group(1))
            if sex:
                return sex, None

    # 3) Medium-signal compact forms
    hits: list[str] = []

    hits += re.findall(r"\b\d{1,3}\s*([mf])\b", t)
    hits += re.findall(r"\b([mf])\s*\d{1,3}\b", t)
    hits += re.findall(r"\b\d{1,3}\s*(?:yo|y/o|yr|yrs|year|years)\s*([mf])\b", t)
    hits += re.findall(r"\b\d{1,3}\s*(?:yo|y/o|yr|yrs|year|years)\s*(male|female)\b", t)

    norm: list[str] = []
    for h in hits:
        sex = _norm(h)
        if sex:
            norm.append(sex)

    if norm:
        if "M" in norm and "F" in norm:
            return None, "Sex conflict detected (multiple formats suggest both M and F)"
        return ("M" if "M" in norm else "F"), None

    # 4) Last resort keyword presence
    if re.search(r"\bfemale\b", t):
        return "F", None
    if re.search(r"\bmale\b", t):
        return "M", None

    return None, "Sex not detected"


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
    m = re.search(
        r"\b(?:systolic\s+blood\s+pressure|systolic\s*bp|sbp)\s*[:=]?\s*(\d{2,3})\b",
        t,
        flags=re.I,
    )
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


def extract_diabetes_meds(raw: str) -> Optional[str]:
    """
    Extracts the raw diabetes meds line from SmartPhrase if present:
      "Diabetes medications: ..."
    Returns the RHS string, or None.
    """
    if not raw:
        return None
    m = re.search(r"\bdiabetes\s+medications\b\s*:\s*([^\n\r]+)", raw, flags=re.I)
    if not m:
        return None
    val = m.group(1).strip()
    if not val or val in ("***", "@DIABETESMEDS@"):
        return None
    return val


def extract_diabetes_flag(raw: str) -> Optional[bool]:
    """
    Safer diabetes parsing (fixes false positives from A1c reference tables).

    Priority:
      1) Explicit fields: "Diabetes: Yes/No" or "Diabetic: Yes/No"
      2) Strong negations
      3) Strong positives ONLY (T2DM/DM2/Type 2 diabetes/Diabetes mellitus/ICD E10/E11)
         (NOTE: we intentionally do NOT treat generic word "diabetes" as positive,
          because A1c reference ranges often contain "Diabetes >6.4%" and would
          otherwise trigger false positives.)
    """
    t = (raw or "").lower()

    # 1) Explicit fields (highest priority)
    m = re.search(r"\b(diabetes|diabetic)\b\s*[:=]\s*(yes|no|true|false)\b", t)
    if m:
        v = m.group(2)
        return True if v in ("yes", "true") else False

    # 2) Standard negations
    if re.search(r"\b(no diabetes|not diabetic|denies diabetes|without diabetes|non[-\s]?diabetic)\b", t):
        return False

    # 3) Strong positives (diagnosis-like)
    if re.search(r"\b(t2dm|dm2|type\s*2\s*diabetes|type\s*ii\s*diabetes|diabetes\s+mellitus)\b", t):
        return True

    # ICD hints
    if re.search(r"\b(e10(\.\d+)?|e11(\.\d+)?)\b", t):
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
    m = re.search(r"(lp\(a\)|lpa|lipoprotein\s*\(a\)|lipoa)\b.{0,40}", t)
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
        return True if v in ("yes", "true") else False
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

    # 1) Explicit field (MOST IMPORTANT)
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
        if re.search(r"\bwhite\b", line):
            return False
        if re.search(r"\b(black|african american)\b", line):
            return True
        return None

    # 3) Explicit negations
    if re.search(r"\b(non[-\s]?black|not black|non[-\s]?african american|not african american)\b", t):
        return False

    # 4) Generic keyword presence (LAST RESORT)
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
    if re.search(r"\b(family history|famhx|fhx)\b\s*[:=]\s*(none|no|negative|denies)\b", t):
        return False, "None / Unknown"

    event = r"(mi|heart\s*attack|cad|coronary|ascvd|stroke|pci|cabg|pad)"

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

    # Father event with age "at 49" / "age 49" / "49 yo"
    m = re.search(rf"\bfather\b.*\b{event}\b.*\b(?:at|age)\s*([0-9]{{2}})\b", t)
    if not m:
        m = re.search(rf"\bfather\b.*\b{event}\b.*\b([0-9]{{2}})\s*(?:yo|y\.o\.|years\s*old)\b", t)
    if m:
        try:
            a = int(m.group(1))
        except Exception:
            a = None
        if a is not None and a < 55:
            return True, "Father with premature ASCVD (MI/stroke/PCI/CABG/PAD) <55"
        return True, "Family history of ASCVD (non-premature)"

    # Mother event with age
    m = re.search(rf"\bmother\b.*\b{event}\b.*\b(?:at|age)\s*([0-9]{{2}})\b", t)
    if not m:
        m = re.search(rf"\bmother\b.*\b{event}\b.*\b([0-9]{{2}})\s*(?:yo|y\.o\.|years\s*old)\b", t)
    if m:
        try:
            a = int(m.group(1))
        except Exception:
            a = None
        if a is not None and a < 65:
            return True, "Mother with premature ASCVD (MI/stroke/PCI/CABG/PAD) <65"
        return True, "Family history of ASCVD (non-premature)"

    return None, None


# ----------------------------
# CAC "not done" detection
# ----------------------------
def extract_cac_not_done(raw: str) -> bool:
    t = raw.lower()
    return bool(re.search(r"\b(cac|calcium|agatston)\b.*\b(not\s*done|not\s*performed|unknown|n/?a|none)\b", t))


# ----------------------------
# PREVENT helpers: BMI, eGFR, lipid-lowering therapy
# ----------------------------
def extract_height_cm(raw: str) -> Optional[float]:
    t = raw.lower()

    m = re.search(r"\bheight\s*[:=]?\s*([0-9]{2,3}(?:\.\d+)?)\s*cm\b", t, flags=re.I)
    if m:
        return _to_float(m.group(1))

    m = re.search(r"\b([4-7])\s*'\s*([0-9]{1,2})\s*(?:\"|in)?\b", t, flags=re.I)
    if m:
        try:
            ft = int(m.group(1))
            inch = int(m.group(2))
            total_in = ft * 12 + inch
            return round(total_in * 2.54, 1)
        except Exception:
            return None

    m = re.search(r"\bheight\s*[:=]?\s*([0-9]{2}(?:\.\d+)?)\s*(?:in|inch|inches)\b", t, flags=re.I)
    if m:
        v = _to_float(m.group(1))
        return None if v is None else round(v * 2.54, 1)

    return None


def extract_weight_kg(raw: str) -> Optional[float]:
    t = raw.lower()

    m = re.search(r"\bweight\s*[:=]?\s*([0-9]{2,3}(?:\.\d+)?)\s*kg\b", t, flags=re.I)
    if m:
        return _to_float(m.group(1))

    m = re.search(r"\bweight\s*[:=]?\s*([0-9]{2,3}(?:\.\d+)?)\s*lb\b", t, flags=re.I)
    if m:
        v = _to_float(m.group(1))
        return None if v is None else round(v * 0.45359237, 2)

    return None


def compute_bmi(height_cm: float, weight_kg: float) -> Optional[float]:
    if height_cm <= 0 or weight_kg <= 0:
        return None
    h_m = height_cm / 100.0
    bmi = weight_kg / (h_m * h_m)
    return round(bmi, 1)


def extract_bmi(raw: str) -> Optional[float]:
    t = raw.lower()

    # 1) Standard "BMI: 27.4" or "Body mass index: 27.4"
    v = _first_float(r"\b(?:bmi|body\s*mass\s*index)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\b", t)
    if v is not None:
        return v

    # 2) Epic narrative: "Body mass index is 38.74 kg/m²."
    v = _first_float(r"\bbody\s*mass\s*index\s+is\s+(\d{1,3}(?:\.\d+)?)\b", t)
    if v is not None:
        return v

    # 3) Epic narrative: "Estimated body mass index is 38.74 kg/m² ..."
    v = _first_float(r"\bestimated\s+body\s*mass\s*index\s+is\s+(\d{1,3}(?:\.\d+)?)\b", t)
    if v is not None:
        return v

    # 4) Compute from height/weight if present
    h = extract_height_cm(raw)
    w = extract_weight_kg(raw)
    if h is not None and w is not None:
        return compute_bmi(h, w)

    return None
def extract_uacr_with_reason(raw: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Returns (uacr_mg_g, reason_if_missing_or_unreliable)

    Accepts common formats:
      - "UACR: 85 mg/g"
      - "Urine albumin/creatinine ratio: 85"
      - "Albumin/Creatinine Ratio 85 mg/g"
      - "Microalb/Creat Ratio: 85"
      - "ACR: 85" (guarded to avoid random "CR")
    """
    t = raw.lower()

    # 1) Direct UACR / ACR labels
    v = _first_float(
        r"\b(?:uacr|urine\s+acr|albumin\/creatinine\s+ratio|albumin\s*\/\s*creatinine\s+ratio|"
        r"urine\s+albumin\/creatinine\s+ratio|microalb\/creat(?:inine)?\s*ratio|microalbumin\/creat(?:inine)?\s*ratio|"
        r"microalb(?:umin)?\s*\/\s*creat(?:inine)?\s*ratio)\b"
        r"\s*[:=]?\s*(\d{1,5}(?:\.\d+)?)\b",
        t,
    )

    # 2) Guarded "ACR" (avoid matching "Cr" or "Creatinine")
    if v is None:
        v = _first_float(r"\bacr\b\s*[:=]?\s*(\d{1,5}(?:\.\d+)?)\b", t)

    if v is not None:
        # sanity range (mg/g)
        if v < 0 or v > 10000:
            return v, "uacr_value_out_of_range_verify"
        return v, None

    # 3) Explicit “not available” / “no results”
    if re.search(r"\b(uacr|acr|albumin\/creatinine\s+ratio)\b.*\b(no\s+results\s+found|not\s+available|unavailable)\b", t):
        return None, "uacr_unavailable"

    return None, None


def extract_uacr(raw: str) -> Optional[float]:
    v, _reason = extract_uacr_with_reason(raw)
    return v


def extract_egfr_with_reason(raw: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Returns (egfr_value, reason_if_missing_or_unreliable)

    Handles:
      - "eGFR: 72" / "estimated GFR 72"
      - Epic numeric formats:
          "Estimated Glomerular Filtration Rate: 91.3 ..."
          "eGFR Cre: 91 ..."
      - Epic unavailability text:
          "eGFR cannot be calculated (... older than the maximum 180 days allowed.)"
          "Computed eGFR ... unavailable"
    """
    t = raw.lower()

    # 1) Numeric eGFR present (standard + Epic)
    v = _first_float(
        r"\b(?:egfr|e\s*gfr|estimated\s+gfr|estimated\s+glomerular\s+filtration\s+rate)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\b",
        t,
    )
    if v is None:
        v = _first_float(r"\bestimated\s+glomerular\s+filtration\s+rate\s*:\s*(\d{1,3}(?:\.\d+)?)\b", t)
    if v is None:
        v = _first_float(r"\begfr\s*cre\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\b", t)
    if v is None:
        v = _first_float(r"\b(?:gfr)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\b", t)

    if v is not None:
        if v < 5 or v > 200:
            return v, "egfr_value_out_of_range_verify"
        return v, None

    # 2) Explicit unavailability reasons (Epic-style)
    if re.search(r"\begfr\b.*\bcannot\s+be\s+calculated\b.*\bolder\b.*\b180\s+days\b", t):
        return None, "egfr_unavailable_older_than_180d"

    if re.search(r"\b(computed\s+egfr|egfr)\b.*\bunavailable\b", t):
        return None, "egfr_unavailable"

    if re.search(r"\begfr\b.*\bno\s+results\s+found\b", t):
        return None, "egfr_not_found"

    if re.search(r"\begfr\b.*\bdid\s+not\s+fit\b.*\bcriterion\b", t):
        return None, "egfr_unavailable_criteria_not_met"

    if re.search(r"\bcrcl\b.*\bcannot\s+be\s+calculated\b", t):
        return None, "egfr_unavailable_related_missing_creatinine"

    return None, None


def extract_egfr(raw: str) -> Optional[float]:
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
        return True if v in ("yes", "true") else False

    return None


def extract_labs(raw: str) -> Dict[str, Optional[float]]:
    t = raw.lower()

    tc = _first_float(
        r"\b(?:total\s*(?:chol(?:esterol)?|tc)|chol(?:esterol)?|tc)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b",
        t
    )

    # LDL — tolerant (covers "LDL Chol Calc", "LDL Calculated", "LDL (NIH Calc)", etc.)
    ldl = _first_float(
        r"\bldl\b(?:\s*[\-\s]*c\b)?(?:\s*chol(?:esterol)?)?"
        r"(?:\s*(?:calc|calculated|nih\s*calc|chol\s*calc|cholesterol\s*calc|chol\s*calculated))?"
        r"\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b",
        t,
    )
    if ldl is None:
        # Fallback: catch table-style lines that contain LDL and a number later on the same line
        for line in t.splitlines():
            if re.search(r"\bldl\b|ldl[\-\s]*c|ldl\s*chol", line, flags=re.I):
                m = re.search(r"(\d{1,4}(?:\.\d+)?)\b", line)
                if m:
                    ldl = _to_float(m.group(1))
                    if ldl is not None:
                        break

    # HDL tolerance: allow high HDL values (parser should not reject >100).
    # We'll accept up to 300 as "tolerant" and let downstream logic clamp if needed.
    hdl = _first_float(r"\bhdl(?:\s*-\s*c|\s*c|-c)?\s*(?:chol(?:esterol)?)?\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t)
    if hdl is not None and hdl > 300:
        hdl = None

    tg = _first_float(r"\b(?:triglycerides|trigs|tgs|tg)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t)
    apob = _first_float(r"\b(?:apo\s*b|apob)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t)

    # Lp(a) — robust: inline or Epic/LabCorp table component code (e.g., "LIPOA 96.1 (H) 12/22/2025")
    lpa = _first_float(r"\b(?:lp\(a\)|lpa|lipoprotein\s*\(a\))\s*[:=]?\s*(\d{1,6}(?:\.\d+)?)\b", t)
    if lpa is None:
        lpa = _first_float(r"\blipoa\b[^\d]{0,20}(\d{1,6}(?:\.\d+)?)\b", t)
    if lpa is None:
        lpa = _first_float(
            r"\blipoprotein\s*\(a\)\b[\s\S]{0,120}?\bvalue\b[\s\S]{0,60}?(\d{1,6}(?:\.\d+)?)\b",
            t,
        )

    a1c_table = _first_float(
        r"hemoglobin\s*a1c[\s\S]{0,300}?\b\d{1,2}/\d{1,2}/\d{2,4}\s+(\d{1,2}(?:\.\d+)?)\b",
        t,
    )
    a1c_inline = _first_float(r"\b(?:a1c|hba1c|hb\s*a1c)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\s*%?\b", t)

    ascvd = _first_float(r"\bascvd\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\s*%?\b", t)

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

    # Diabetes meds (raw, additive)
    extracted["dm_meds_raw"] = extract_diabetes_meds(raw)

    # Family history
    fhx_bool, fhx_text = extract_fhx(raw)
    extracted["fhx"] = fhx_bool
    extracted["fhx_text"] = fhx_text

    # CAC not-done logic
    cac_nd = extract_cac_not_done(raw)
    extracted["cac_not_done"] = cac_nd
    if cac_nd:
        extracted["cac"] = None

    # PREVENT-related
    extracted["bmi"] = extract_bmi(raw)

    egfr_val, egfr_reason = extract_egfr_with_reason(raw)
    extracted["egfr"] = egfr_val
    extracted["egfr_reason"] = egfr_reason

    uacr_val, uacr_reason = extract_uacr_with_reason(raw)
    extracted["uacr"] = uacr_val
    extracted["uacr_reason"] = uacr_reason

    extracted["lipidLowering"] = extract_lipid_lowering(raw)

    # Diabetes override: A1c >= 6.5 forces diabetes = True
    # (This remains, but keyword-based false positives are fixed by extract_diabetes_flag)
    if labs.get("a1c") is not None and labs["a1c"] >= 6.5:
        if extracted.get("diabetes") is False:
            conflicts.append("Diabetes conflict: text says no diabetes, but A1c ≥ 6.5%")
        extracted["diabetes"] = True

    # Dev-friendly guardrails
    if extracted.get("sex") is None:
        warnings.append("Sex not detected — PCE/eGFR may be inaccurate")

    # HDL tolerance warning (optional, non-breaking)
    if extracted.get("hdl") is not None and extracted["hdl"] > 100:
        warnings.append("HDL > 100 mg/dL detected — PCE may clamp or reject depending on implementation")

    for key, label in [
        ("ldl", "LDL"),
        ("apob", "ApoB"),
        ("lpa", "Lp(a)"),
        ("lpa_unit", "Lp(a) unit"),
        ("a1c", "A1c"),
        ("bmi", "BMI (PREVENT)"),
        ("egfr", "eGFR (PREVENT)"),
        ("uacr", "UACR (PREVENT)"),
    ]:
        if extracted.get(key) is None:
            warnings.append(f"{label} not detected")

    if extracted.get("cac") is None and not extracted.get("cac_not_done", False):
        warnings.append("CAC not detected")

    return ParseReport(extracted=extracted, warnings=warnings, conflicts=conflicts)


def parse_ascvd_block(raw: str) -> Dict[str, Any]:
    return parse_ascvd_block_with_report(raw).extracted


def parse_smartphrase(raw: str) -> Dict[str, Any]:
    """
    UI adapter: returns exactly what your app expects.
    (Additive keys: fhx, fhx_text, cac_not_done, egfr_reason, dm_meds_raw)
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
        # additive keys:
        "fhx", "fhx_text", "cac_not_done",
        "egfr_reason",
        "dm_meds_raw",
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


