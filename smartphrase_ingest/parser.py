# smartphrase_ingest/parser.py
import re
from typing import Dict, Any, Optional, Tuple


def _norm(s: str) -> str:
    return (s or "").strip()


def _to_float(s: str) -> Optional[float]:
    if not s:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s.replace(",", ""))
    return float(m.group(0)) if m else None


def _to_int(s: str) -> Optional[int]:
    v = _to_float(s)
    return int(round(v)) if v is not None else None


def _yesno(s: str) -> Optional[bool]:
    if s is None:
        return None
    t = _norm(str(s)).lower()
    if t.startswith("yes"):
        return True
    if t.startswith("no"):
        return False
    return None


def _line_value(text: str, label_regex: str) -> Optional[str]:
    """
    Extracts 'Label: value' lines (case-insensitive, multiline).
    label_regex should be regex-safe (e.g., r"ApoB", r"Lp\\(a\\)").
    """
    pat = re.compile(rf"^\s*{label_regex}\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    m = pat.search(text or "")
    return _norm(m.group(1)) if m else None


def _find_number_near(text: str, label_patterns) -> Optional[float]:
    """
    Scan lines; if a line matches any label pattern, return first numeric on that line.
    label_patterns: list of compiled regex or strings.
    """
    if not text:
        return None
    lines = (text or "").splitlines()
    for ln in lines:
        for lp in label_patterns:
            rx = re.compile(lp, re.IGNORECASE) if isinstance(lp, str) else lp
            if rx.search(ln):
                v = _to_float(ln)
                if v is not None:
                    return v
    return None


def _find_lpa(text: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Lp(a) appears as:
      - "Lp(a): 114 nmol/L"
      - "Lipoprotein(a) 87.8 mg/dL"
      - "LPA 120"
    Return (value, unit) where unit is "nmol/L", "mg/dL", or None.
    """
    if not text:
        return (None, None)

    patterns = [
        r"^\s*Lp\(a\)\s*:\s*(.+)$",
        r"^\s*Lipoprotein\s*\(a\)\s*:\s*(.+)$",
        r"^\s*LPA\s*:\s*(.+)$",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE | re.MULTILINE)
        if not m:
            continue
        rhs = _norm(m.group(1))
        val = _to_float(rhs)
        unit = None
        if rhs:
            if re.search(r"\bnmol\/l\b", rhs, re.IGNORECASE):
                unit = "nmol/L"
            elif re.search(r"\bmg\/dl\b", rhs, re.IGNORECASE):
                unit = "mg/dL"
        return (val, unit)

    # fallback: any line containing Lp(a) variants
    val = _find_number_near(text, [r"\bLp\(a\)\b", r"\bLipoprotein\s*\(a\)\b", r"\bLPA\b"])
    if val is None:
        return (None, None)

    # try to infer unit by nearby tokens in that line
    unit = None
    for ln in (text or "").splitlines():
        if re.search(r"\bLp\(a\)\b|\bLipoprotein\s*\(a\)\b|\bLPA\b", ln, re.IGNORECASE):
            if re.search(r"\bnmol\/l\b", ln, re.IGNORECASE):
                unit = "nmol/L"
            elif re.search(r"\bmg\/dl\b", ln, re.IGNORECASE):
                unit = "mg/dL"
            break

    return (val, unit)


def _find_cac(text: str) -> Optional[int]:
    """
    CAC appears as:
      - "Coronary artery calcium (CAC) score: 0"
      - "CAC score: 12"
      - "Agatston: 43"
    """
    if not text:
        return None

    # Direct label:value lines
    v = _line_value(text, r"Coronary artery calcium\s*\(CAC\)\s*score")
    if v:
        return _to_int(v)

    v = _line_value(text, r"CAC\s*score")
    if v:
        return _to_int(v)

    # Line contains "Agatston"
    n = _find_number_near(text, [r"\bAgatston\b", r"\bCAC\b.*\bscore\b"])
    return int(round(n)) if n is not None else None


def parse_smartphrase(text: str) -> Dict[str, Any]:
    """
    Best-effort extraction from pasted Epic text (SmartPhrase output, risk blocks, RESUFAST).
    Returns normalized keys used by the Streamlit app for auto-fill.

    Keys:
      age, sex, africanAmerican, smoker, diabetes, bpTreated, sbp
      tc, hdl, ldl, apob, lpa, lpa_unit, a1c, cac
      ascvd_10y
    """
    t = text or ""
    out: Dict[str, Any] = {}

    # ---------- ASCVD risk block ----------
    m = re.search(r"10-year ASCVD risk score.*?is:\s*([0-9]+(?:\.[0-9]+)?)\s*%", t, re.IGNORECASE | re.DOTALL)
    if m:
        out["ascvd_10y"] = float(m.group(1))

    age = _line_value(t, r"Age")
    if age:
        out["age"] = _to_int(age)

    sex = _line_value(t, r"Clinically relevant sex") or _line_value(t, r"Sex")
    if sex:
        s = _norm(sex).lower()
        if "female" in s:
            out["sex"] = "F"
        elif "male" in s:
            out["sex"] = "M"

    aa = _line_value(t, r"Is Non-Hispanic African American")
    if aa is not None:
        out["africanAmerican"] = _yesno(aa)

    dm = _line_value(t, r"Diabetic") or _line_value(t, r"Diabetes mellitus")
    if dm is not None:
        out["diabetes"] = _yesno(dm)

    sm = _line_value(t, r"Tobacco smoker") or _line_value(t, r"Smoking status")
    # Smoking status might be "Never", "Current", etc. Keep boolean if clearly yes/no; else omit.
    sm_bool = _yesno(sm) if sm is not None else None
    if sm_bool is not None:
        out["smoker"] = sm_bool
    else:
        if sm:
            s = _norm(sm).lower()
            if "current" in s:
                out["smoker"] = True
            elif "never" in s or "no" == s:
                out["smoker"] = False

    sbp = _line_value(t, r"Systolic Blood Pressure") or _line_value(t, r"Blood pressure\s*\(most recent\)")
    if sbp:
        # if bp is "144/82", take systolic
        m2 = re.search(r"(\d{2,3})\s*/\s*(\d{2,3})", sbp)
        if m2:
            out["sbp"] = int(m2.group(1))
        else:
            out["sbp"] = _to_int(sbp)

    bpt = _line_value(t, r"Is BP treated") or _line_value(t, r"On BP meds\?")
    if bpt is not None:
        out["bpTreated"] = _yesno(bpt)

    # ---------- Lipids / labs ----------
    tc = _line_value(t, r"Total Cholesterol") or _line_value(t, r"Total cholesterol")
    if tc:
        out["tc"] = _to_int(tc)
    else:
        n = _find_number_near(t, [r"\bTotal\s+Cholesterol\b", r"\bCholesterol,\s*Total\b", r"\bCHOL\b"])
        if n is not None:
            out["tc"] = int(round(n))

    hdl = _line_value(t, r"HDL Cholesterol") or _line_value(t, r"HDL cholesterol")
    if hdl:
        out["hdl"] = _to_int(hdl)
    else:
        n = _find_number_near(t, [r"\bHDL\b"])
        if n is not None:
            out["hdl"] = int(round(n))

    # LDL is often "LDL Cholesterol", "LDL Calculated", "LDL-C"
    ldl = _line_value(t, r"LDL(?:-C)?(?:\s+Cholesterol|\s+Calculated|\s+Calc)?") or _line_value(t, r"LDL-C")
    if ldl:
        out["ldl"] = _to_int(ldl)
    else:
        n = _find_number_near(t, [r"\bLDL\b", r"\bLDL-C\b", r"\bLDL\s+Calc\b", r"\bLDL\s+Calculated\b"])
        if n is not None:
            out["ldl"] = int(round(n))

    a1c = _line_value(t, r"A1c") or _line_value(t, r"HbA1c") or _line_value(t, r"HbA1C")
    if a1c:
        out["a1c"] = _to_float(a1c)

    apob = _line_value(t, r"ApoB") or _line_value(t, r"APOB")
    if apob:
        out["apob"] = _to_int(apob)
    else:
        n = _find_number_near(t, [r"\bApoB\b", r"\bAPOB\b"])
        if n is not None:
            out["apob"] = int(round(n))

    lpa_val, lpa_unit = _find_lpa(t)
    if lpa_val is not None:
        out["lpa"] = int(round(lpa_val))
    if lpa_unit:
        out["lpa_unit"] = lpa_unit

    cac = _find_cac(t)
    if cac is not None:
        out["cac"] = cac

    return out

