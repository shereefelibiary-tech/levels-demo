# app.py
# ============================================================
# LEVELS — Streamlit app with:
# - Textbox parsing (for Epic/SmartPhrase-style blocks)
# - Robust sex extraction (male/female, 57M, Sex: Male, etc.)
# - "Fail loudly" flags when data missing / conflicting
# - Manual overrides only when needed (missing/conflict)
# - Includes LDL, ApoB, Lp(a), CAC, BP, A1c, ASCVD
# - Fixes: form submit button + numeric max ranges (HDL, etc.)
# ============================================================

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Optional, Tuple, Dict, Any

import streamlit as st

# Your existing engine (expected to exist in your project)
# ------------------------------------------------------------
# levels_engine should define:
#   - Patient dataclass/model (or similar)
#   - evaluate(patient) -> result (dict-like or object)
#   - render_quick_text(result, patient) -> str
#   - VERSION
#
# If your Patient signature differs, adapt build_patient_from_state()
from levels_engine import Patient, evaluate, render_quick_text, VERSION


# ============================================================
# Styling
# ============================================================

st.set_page_config(page_title="LEVELS", layout="wide")

st.markdown(
    """
<style>
html, body, [class*="css"] {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, "Helvetica Neue", Arial, sans-serif;
  color: #111827;
}

.smallcaps {
  font-variant: all-small-caps;
  letter-spacing: 0.06em;
  color: rgba(17,24,39,0.72);
}

.card {
  background: #ffffff;
  border: 1px solid rgba(17,24,39,0.12);
  border-radius: 16px;
  padding: 16px;
}

.muted {
  color: rgba(17,24,39,0.65);
  font-size: 0.92rem;
}

hr {
  border: none;
  border-top: 1px solid rgba(17,24,39,0.10);
  margin: 14px 0;
}

.badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  border: 1px solid rgba(17,24,39,0.14);
  font-size: 0.82rem;
  margin-right: 6px;
}

.badge-warn {
  background: rgba(245,158,11,0.10);
  border-color: rgba(245,158,11,0.25);
}

.badge-bad {
  background: rgba(239,68,68,0.10);
  border-color: rgba(239,68,68,0.25);
}

.badge-ok {
  background: rgba(16,185,129,0.10);
  border-color: rgba(16,185,129,0.25);
}

pre {
  white-space: pre-wrap !important;
  word-wrap: break-word !important;
}
</style>
""",
    unsafe_allow_html=True,
)

# ============================================================
# Parsing helpers (robust + forgiving)
# ============================================================

@dataclass
class ParseReport:
    extracted: Dict[str, Any]
    warnings: list[str]
    conflicts: list[str]


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


def extract_sex(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (sex, warning)
      sex: "M" | "F" | None
      warning: None if clean; otherwise reason (missing/conflict)
    """
    if not raw or not raw.strip():
        return None, "Sex not detected (empty text)"

    t = raw.lower()
    hits = []

    # 1) Explicit: Sex: Male, Gender=f
    explicit = re.findall(r"\b(sex|gender)\s*[:=]\s*(male|female|m|f|man|woman)\b", t)
    for _, val in explicit:
        hits.append(val)

    # 2) Compressed: 57M / 63F; also M57 / F63
    hits += re.findall(r"\b\d{1,3}\s*([mf])\b", t)
    hits += re.findall(r"\b([mf])\s*\d{1,3}\b", t)

    # 3) Free text words
    if re.search(r"\b(male|man)\b", t):
        hits.append("male")
    if re.search(r"\b(female|woman)\b", t):
        hits.append("female")

    # Normalize
    norm = []
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

    # Common: "57 yo", "57 y/o", "57-year-old", "Age: 57", "57M"
    age = _first_int(r"\bage\s*[:=]\s*(\d{1,3})\b", t)
    if age is None:
        age = _first_int(r"\b(\d{1,3})\s*(yo|y/o|yr|yrs|year|years)\b", t)
    if age is None:
        age = _first_int(r"\b(\d{1,3})\s*-\s*year\s*-\s*old\b", t.replace("–", "-").replace("—", "-"))
    if age is None:
        age = _first_int(r"\b(\d{1,3})\s*-\s*year\s*old\b", t.replace("–", "-").replace("—", "-"))
    if age is None:
        age = _first_int(r"\b(\d{1,3})\s*(m|f)\b", t)  # 57M / 63F

    if age is None:
        return None, "Age not detected"

    if age < 18 or age > 100:
        return age, "Age looks unusual — please verify"

    return age, None


def extract_bp(raw: str) -> Optional[Tuple[int, int]]:
    # Examples: 128/78, BP 144/82, "BP today 142/86"
    m = re.search(r"\b(?:bp\s*)?(\d{2,3})\s*/\s*(\d{2,3})\b", raw, flags=re.I)
    if not m:
        return None
    try:
        return int(m.group(1)), int(m.group(2))
    except Exception:
        return None


def extract_bool_flags(raw: str) -> Dict[str, Optional[bool]]:
    """
    Returns dict of {diabetes, smoker, former_smoker} (values can be None if unknown)
    """
    t = raw.lower()

    # Diabetes
    diabetes: Optional[bool] = None
    if re.search(r"\b(no diabetes|not diabetic|denies diabetes)\b", t):
        diabetes = False
    if re.search(r"\b(diabetes|t2dm|type 2 diabetes|type ii diabetes)\b", t):
        diabetes = True

    # Smoking
    smoker: Optional[bool] = None
    former_smoker: Optional[bool] = None

    if re.search(r"\b(never smoker|non-smoker|nonsmoker|never smoked)\b", t):
        smoker = False
        former_smoker = False
    if re.search(r"\b(former smoker|ex-smoker|quit smoking)\b", t):
        smoker = False
        former_smoker = True
    if re.search(r"\b(current smoker|smoker|smokes)\b", t):
        # guard against "non-smoker" already caught above
        if not re.search(r"\b(non-smoker|nonsmoker)\b", t):
            smoker = True
            former_smoker = False

    return {"diabetes": diabetes, "smoker": smoker, "former_smoker": former_smoker}


def extract_labs(raw: str) -> Dict[str, Optional[float]]:
    t = raw

    # Accept: "LDL 112", "LDL=112", "LDL: 112 mg/dL"
    # Total cholesterol: "Total cholesterol 198", "TC 198", "Chol 198"
    labs = {
        "tc": _first_float(r"\b(?:total\s*cholesterol|total\s*chol|tc|cholesterol|chol)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "ldl": _first_float(r"\bldl\s*(?:chol(?:esterol)?)?\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "hdl": _first_float(r"\bhdl\s*(?:chol(?:esterol)?)?\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "tg": _first_float(r"\b(?:triglycerides|trigs|tgs|tg)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "apob": _first_float(r"\b(?:apo\s*b|apob)\s*[:=]?\s*(\d{1,4}(?:\.\d+)?)\b", t),
        "lpa": _first_float(r"\b(?:lp\(a\)|lpa|lipoprotein\s*\(a\))\s*[:=]?\s*(\d{1,6}(?:\.\d+)?)\b", t),
        "a1c": _first_float(r"\b(?:a1c|hba1c|hb\s*a1c)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\s*%?\b", t),
        "ascvd": _first_float(r"\bascvd\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\s*%?\b", t),
        "cac": _first_float(r"\b(?:cac|coronary\s*artery\s*calcium|calcium\s*score)\s*(?:score)?\s*[:=]?\s*(\d{1,6}(?:\.\d+)?)\b", t),
    }
    return labs


def parse_text_block(raw: str) -> ParseReport:
    extracted: Dict[str, Any] = {}
    warnings: list[str] = []
    conflicts: list[str] = []

    # Demographics
    sex, sex_warn = extract_sex(raw)
    age, age_warn = extract_age(raw)
    extracted["sex"] = sex
    extracted["age"] = age
    if sex_warn:
        # conflict vs missing separation
        if "conflict" in sex_warn.lower():
            conflicts.append(sex_warn)
        else:
            warnings.append(sex_warn)
    if age_warn:
        warnings.append(age_warn)

    # Vitals
    bp = extract_bp(raw)
    if bp:
        extracted["sbp"], extracted["dbp"] = bp
    else:
        extracted["sbp"], extracted["dbp"] = None, None
        warnings.append("BP not detected")

    # Flags
    flags = extract_bool_flags(raw)
    extracted.update(flags)

    # Labs
    labs = extract_labs(raw)
    extracted.update(labs)

    # Diabetes override by A1c >= 6.5
    if labs.get("a1c") is not None and labs["a1c"] >= 6.5:
        if extracted.get("diabetes") is False:
            conflicts.append("Diabetes conflict: text says no diabetes, but A1c ≥ 6.5%")
        extracted["diabetes"] = True

    # Missing-data warnings that matter for Levels output
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


# ============================================================
# Build Patient object for engine (adapt if your Patient differs)
# ============================================================

def build_patient_from_state(state: dict) -> Patient:
    """
    Map Streamlit session_state fields -> your Patient model.
    Adjust field names here if your Patient signature differs.
    """

    # Common pattern: Patient(age=..., sex=..., etc.)
    # If your Patient expects different names/types, change here only.
    return Patient(
        age=state.get("age"),
        sex=state.get("sex"),  # "M" or "F"
        sbp=state.get("sbp"),
        dbp=state.get("dbp"),
        tc=state.get("tc"),
        ldl=state.get("ldl"),
        hdl=state.get("hdl"),
        tg=state.get("tg"),
        apob=state.get("apob"),
        lpa=state.get("lpa"),
        a1c=state.get("a1c"),
        ascvd_10y=state.get("ascvd"),
        cac=state.get("cac"),
        diabetes=state.get("diabetes"),
        smoker=state.get("smoker"),
        former_smoker=state.get("former_smoker"),
    )


# ============================================================
# UI
# ============================================================

st.markdown(
    f"""
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;">
    <div>
      <div class="smallcaps">LEVELS</div>
      <div style="font-size:1.35rem;font-weight:700;margin-top:4px;">CV Prevention — parse → validate → generate</div>
      <div class="muted" style="margin-top:4px;">Paste an Epic SmartPhrase-style block. The app will extract fields, flag gaps/conflicts, and run the Levels engine.</div>
    </div>
    <div style="text-align:right;">
      <span class="badge">Engine v{VERSION}</span>
      <span class="badge">App v1.0</span>
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

left, right = st.columns([1.1, 0.9], gap="large")


# -----------------------------
# Left: Text input + Parse
# -----------------------------
with left:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="smallcaps">Input</div>', unsafe_allow_html=True)

    default_example = """57 yo male
A1c 6.1%
Total cholesterol 198
LDL 112
HDL 46
Triglycerides 162
BP 128/78
ASCVD 8.4%
Non-smoker
No diabetes
"""

    raw_text = st.text_area(
        "Paste note / SmartPhrase block",
        value=st.session_state.get("raw_text", default_example),
        height=260,
        key="raw_text",
    )

    colA, colB = st.columns([1, 1])
    with colA:
        parse_btn = st.button("Parse textbox", type="primary", use_container_width=True)
    with colB:
        clear_btn = st.button("Clear parsed values", use_container_width=True)

    if clear_btn:
        for k in [
            "age", "sex", "sbp", "dbp", "tc", "ldl", "hdl", "tg", "apob", "lpa", "a1c", "ascvd", "cac",
            "diabetes", "smoker", "former_smoker",
            "sex_override", "age_override",
        ]:
            if k in st.session_state:
                del st.session_state[k]
        st.success("Cleared parsed values.")

    if parse_btn:
        report = parse_text_block(raw_text)
        st.session_state["parse_report"] = asdict(report)

        # Hydrate session state with extracted values
        for k, v in report.extracted.items():
            st.session_state[k] = v

        # Create override slots (only used when missing/conflict)
        if "sex_override" not in st.session_state:
            st.session_state["sex_override"] = None
        if "age_override" not in st.session_state:
            st.session_state["age_override"] = None

    # Show parse report (always show if present)
    pr = st.session_state.get("parse_report")
    if pr:
        warnings = pr.get("warnings", [])
        conflicts = pr.get("conflicts", [])

        if conflicts:
            st.markdown("**Conflicts**")
            for c in conflicts:
                st.markdown(f'- <span class="badge badge-bad">{c}</span>', unsafe_allow_html=True)

        if warnings:
            st.markdown("**Missing / uncertain fields**")
            for w in warnings:
                st.markdown(f'- <span class="badge badge-warn">{w}</span>', unsafe_allow_html=True)

        if not warnings and not conflicts:
            st.markdown('<span class="badge badge-ok">Parse looks clean</span>', unsafe_allow_html=True)

        with st.expander("View extracted dictionary"):
            st.json(pr.get("extracted", {}))

    st.markdown("</div>", unsafe_allow_html=True)


# -----------------------------
# Right: Review + Submit to engine
# -----------------------------
with right:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="smallcaps">Review & Run</div>', unsafe_allow_html=True)

    # Manual overrides only when missing/conflict
    sex_missing_or_conflict = (st.session_state.get("sex") is None)
    age_missing = (st.session_state.get("age") is None)

    if sex_missing_or_conflict:
        st.warning("Sex is missing or conflicted — please select manually (used for ASCVD logic).")
        st.session_state["sex_override"] = st.radio(
            "Sex (override)",
            options=["M", "F"],
            horizontal=True,
            index=0 if st.session_state.get("sex_override") != "F" else 1,
        )

    if age_missing:
        st.warning("Age is missing — please enter manually.")
        st.session_state["age_override"] = st.number_input("Age (override)", 18, 100, value=55, step=1)

    # Always show the parsed values in a form so user can tweak quickly
    with st.form("review_form"):
        c1, c2 = st.columns(2)

        with c1:
            # Use safer numeric ranges to avoid Streamlit max errors
            sbp = st.number_input("SBP (mmHg)", 60, 260, value=int(st.session_state.get("sbp") or 120), step=1)
            dbp = st.number_input("DBP (mmHg)", 30, 180, value=int(st.session_state.get("dbp") or 80), step=1)
            a1c = st.number_input("A1c (%)", 3.0, 20.0, value=float(st.session_state.get("a1c") or 5.6), step=0.1)

            diabetes_default = st.session_state.get("diabetes")
            diabetes = st.radio(
                "Diabetes",
                options=["Unknown", "No", "Yes"],
                index=2 if diabetes_default is True else (1 if diabetes_default is False else 0),
                horizontal=True,
            )

            smoker_default = st.session_state.get("smoker")
            smoker = st.radio(
                "Current smoker",
                options=["Unknown", "No", "Yes"],
                index=2 if smoker_default is True else (1 if smoker_default is False else 0),
                horizontal=True,
            )

        with c2:
            tc = st.number_input("Total cholesterol (mg/dL)", 50, 600, value=int(st.session_state.get("tc") or 200), step=1)
            ldl = st.number_input("LDL (mg/dL)", 0, 400, value=int(st.session_state.get("ldl") or 110), step=1)
            hdl = st.number_input("HDL (mg/dL)", 0, 300, value=int(st.session_state.get("hdl") or 45), step=1)
            tg = st.number_input("Triglycerides (mg/dL)", 20, 1500, value=int(st.session_state.get("tg") or 150), step=1)

            apob = st.number_input("ApoB (mg/dL)", 0, 300, value=int(st.session_state.get("apob") or 90), step=1)
            lpa = st.number_input("Lp(a) (nmol/L or mg/dL as entered)", 0.0, 500.0, value=float(st.session_state.get("lpa") or 0.0), step=1.0)
            cac = st.number_input("CAC score", 0, 5000, value=int(st.session_state.get("cac") or 0), step=1)

            ascvd = st.number_input("ASCVD 10-year risk (%)", 0.0, 100.0, value=float(st.session_state.get("ascvd") or 0.0), step=0.1)

        submitted = st.form_submit_button("Run LEVELS", type="primary", use_container_width=True)

    # Convert form outputs to internal state
    if submitted:
        # Apply sex/age from parsed unless override is needed
        sex_final = st.session_state.get("sex")
        age_final = st.session_state.get("age")

        if sex_missing_or_conflict:
            sex_final = st.session_state.get("sex_override")
        if age_missing:
            age_final = st.session_state.get("age_override")

        # Apply diabetes/smoker with A1c override logic
        diabetes_val: Optional[bool] = None
        if diabetes == "Yes":
            diabetes_val = True
        elif diabetes == "No":
            diabetes_val = False

        # A1c override: A1c >= 6.5 forces diabetes = True
        if a1c >= 6.5:
            diabetes_val = True

        smoker_val: Optional[bool] = None
        if smoker == "Yes":
            smoker_val = True
        elif smoker == "No":
            smoker_val = False

        # Store final values
        st.session_state.update(
            {
                "sex": sex_final,
                "age": int(age_final) if age_final is not None else None,
                "sbp": int(sbp),
                "dbp": int(dbp),
                "tc": float(tc),
                "ldl": float(ldl),
                "hdl": float(hdl),
                "tg": float(tg),
                "apob": float(apob) if apob is not None else None,
                "lpa": float(lpa) if lpa is not None else None,
                "a1c": float(a1c),
                "ascvd": float(ascvd) if ascvd is not None else None,
                "cac": float(cac) if cac is not None else None,
                "diabetes": diabetes_val,
                "smoker": smoker_val,
                "former_smoker": None,  # optional: you can add UI if desired
            }
        )

        # Basic validation banners
        problems = []
        if st.session_state.get("age") is None:
            problems.append("Age missing")
        if st.session_state.get("sex") is None:
            problems.append("Sex missing")
        if st.session_state.get("ascvd") in (None, 0.0):
            problems.append("ASCVD missing/0 — consider entering if available")

        if problems:
            st.warning("Before interpreting output: " + " • ".join(problems))

        # Run engine
        try:
            patient = build_patient_from_state(st.session_state)
            result = evaluate(patient)
            output_text = render_quick_text(result, patient)

            st.session_state["last_patient"] = patient
            st.session_state["last_result"] = result
            st.session_state["last_output_text"] = output_text

        except TypeError as e:
            st.error(
                "Engine call failed due to Patient field mismatch.\n\n"
                "This means your levels_engine.Patient signature doesn't match build_patient_from_state().\n"
                "Fix by editing build_patient_from_state() mapping.\n\n"
                f"Error: {e}"
            )
        except Exception as e:
            st.error(f"Engine error: {e}")

    st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# Output area
# ============================================================

st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<div class="smallcaps">Output</div>', unsafe_allow_html=True)

last_output = st.session_state.get("last_output_text")
last_patient = st.session_state.get("last_patient")
last_result = st.session_state.get("last_result")

if last_output:
    st.markdown("#### Clinical summary (Levels)")
    st.code(last_output)

    st.markdown("#### Notes (guideline framing)")
    st.markdown(
        """
- **Near-term risk** is typically anchored to 10-year ASCVD risk plus major enhancers (e.g., diabetes, CAC, very high ApoB/Lp(a), strong FH).
- **Long-term risk** can remain elevated even when short-term risk is low (e.g., younger age, CAC=0, but high ApoB/Lp(a) or strong family history).
- This output is intended to align with an **ACC-style risk discussion**: risk estimate → enhancers → shared decision → intensity of therapy.
"""
    )

    with st.expander("Debug: last patient object"):
        try:
            st.write(last_patient)
        except Exception:
            st.json(st.session_state.get("last_patient"))

    with st.expander("Debug: raw engine result"):
        st.write(last_result)

else:
    st.markdown('<div class="muted">Run the parser and click <b>Run LEVELS</b> to generate output.</div>', unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)
