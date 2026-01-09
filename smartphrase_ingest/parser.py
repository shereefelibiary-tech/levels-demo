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

