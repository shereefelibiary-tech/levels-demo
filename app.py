import json
import re
import streamlit as st
from typing import Dict, Any, List, Optional

from smartphrase_ingest.parser import parse_smartphrase
from levels_engine import Patient, evaluate, render_compact_text, render_full_text, VERSION, short_why

# ============================================================
# Page + styling
# ============================================================
st.set_page_config(page_title="LEVELS", layout="wide")

st.markdown(
    """
<style>
html, body, [class*="css"] {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, "Helvetica Neue", Arial, sans-serif;
  color: #1f2937;
}
.header-card {
  background: #ffffff;
  border: 1px solid rgba(31,41,55,0.12);
  border-radius: 14px;
  padding: 16px 18px;
  margin-bottom: 10px;
}
.header-title { font-size: 1.15rem; font-weight: 800; margin: 0 0 4px 0; }
.header-sub { color: rgba(31,41,55,0.60); font-size: 0.9rem; margin: 0; }
.hr { margin: 10px 0 14px 0; border-top: 1px solid rgba(31,41,55,0.12); }

.report {
  background: #ffffff;
  border: 1px solid rgba(31,41,55,0.12);
  border-radius: 14px;
  padding: 18px 20px;
}
.report h2 { font-size: 1.10rem; font-weight: 900; margin: 0 0 10px 0; }

.section { margin-top: 12px; }
.section-title {
  font-variant-caps: all-small-caps;
  letter-spacing: 0.08em;
  font-weight: 900;
  font-size: 0.82rem;
  color: #4b5563;
  margin-bottom: 6px;
  border-bottom: 1px solid rgba(31,41,55,0.10);
  padding-bottom: 2px;
}
.section p { margin: 6px 0; line-height: 1.45; }
.section ul { margin: 6px 0 6px 18px; }
.section li { margin: 4px 0; }

.muted { color: #6b7280; font-size: 0.9rem; }
.small-help { color: rgba(31,41,55,0.70); font-size: 0.88rem; }

.badge {
  display:inline-block; padding:2px 8px; border-radius:999px;
  border:1px solid rgba(31,41,55,0.15); background:#fff;
  font-size:0.82rem; margin-left:6px;
}
.ok { border-color: rgba(16,185,129,0.35); background: rgba(16,185,129,0.08); }
.miss { border-color: rgba(245,158,11,0.35); background: rgba(245,158,11,0.10); }

.crit { display:flex; gap:8px; flex-wrap:wrap; margin-top: 8px; }
.crit-pill {
  display:inline-block; padding:6px 10px; border-radius: 999px;
  border:1px solid rgba(31,41,55,0.14); background:#fff;
  font-size:0.85rem; font-weight:800;
}
.crit-ok { border-color: rgba(16,185,129,0.35); background: rgba(16,185,129,0.08); }
.crit-miss { border-color: rgba(245,158,11,0.35); background: rgba(245,158,11,0.10); }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""
<div class="header-card">
  <div class="header-title">LEVELS™ {VERSION.get("levels","")} — De-identified Demo</div>
  <p class="header-sub">SmartPhrase paste → auto-fill • compact professional output • no storage intended</p>
</div>
""",
    unsafe_allow_html=True,
)

st.info("De-identified use only. Do not enter patient identifiers.")

# ============================================================
# Reset + clear callbacks (MUST be callbacks)
# ============================================================
def reset_form_state():
    for k in list(st.session_state.keys()):
        if k.startswith("_"):
            continue
        del st.session_state[k]
    st.session_state["_reset_done"] = True

def clear_pasted_text():
    # Safe because runs before widget is recreated on rerun
    st.session_state["smartphrase_raw"] = ""
    st.session_state["_cleared_done"] = True

c_reset, c_tip = st.columns([1, 4])
with c_reset:
    st.button("Reset form", type="secondary", on_click=reset_form_state)
with c_tip:
    st.caption("If a widget looks wrong after an update, click Reset form.")

if st.session_state.get("_reset_done"):
    st.success("Form reset.")
    del st.session_state["_reset_done"]

# ============================================================
# Guardrails
# ============================================================
PHI_PATTERNS: List[str] = [
    r"\b\d{3}-\d{2}-\d{4}\b",
    r"\b\d{2}/\d{2}/\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\bMRN\b|\bMedical Record\b",
    r"@",
    r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",
]

def contains_phi(s: str) -> bool:
    if not s:
        return False
    return any(re.search(pat, s, re.IGNORECASE) for pat in PHI_PATTERNS)

# ============================================================
# Parsing enhancements (parser + regex fallback)
# ============================================================
def _rx_first(patterns: List[str], text: str, flags=re.IGNORECASE):
    for pat in patterns:
        m = re.search(pat, text, flags)
        if m:
            return m
    return None

def _to_int(x) -> Optional[int]:
    try:
        return int(round(float(str(x).strip())))
    except:
        return None

def _to_float(x) -> Optional[float]:
    try:
        return float(str(x).strip())
    except:
        return None

def regex_extract_smartphrase(text: str) -> Dict[str, Any]:
    t = text or ""
    out: Dict[str, Any] = {}

    m = _rx_first([r"\bAGE[:\s]+(\d{2,3})\b", r"\bAge[:\s]+(\d{2,3})\b", r"\b(\d{2,3})\s*y/?o\b"], t)
    if m: out["age"] = _to_int(m.group(1))

    m = _rx_first([r"\bSEX[:\s]+(M|F)\b", r"\bSex[:\s]+(M|F)\b"], t)
    if m: out["sex"] = str(m.group(1)).upper()

    if re.search(r"\bblack\b|\bafrican[-\s]?american\b", t, re.IGNORECASE):
        out["africanAmerican"] = True

    m = _rx_first([r"\bSBP[:\s]+(\d{2,3})\b", r"\bSystolic\s*BP[:\s]+(\d{2,3})\b"], t)
    if m:
        out["sbp"] = _to_int(m.group(1))
    else:
        m2 = _rx_first([r"\bBP[:\s]+(\d{2,3})\s*/\s*\d{2,3}\b"], t)
        if m2:
            out["sbp"] = _to_int(m2.group(1))

    m = _rx_first([r"\b(TC|TOTAL\s*CHOLESTEROL)[:\s]+(\d{2,3})\b", r"\bTotal\s*Cholesterol[:\s]+(\d{2,3})\b"], t)
    if m: out["tc"] = _to_int(m.group(m.lastindex))

    m = _rx_first([r"\bHDL[:\s]+(\d{2,3})\b"], t)
    if m: out["hdl"] = _to_int(m.group(1))

    m = _rx_first([r"\bLDL[-\s]*C?\b[:\s]+(\d{2,3})\b", r"\bLDL\b[:\s]+(\d{2,3})\b"], t)
    if m: out["ldl"] = _to_int(m.group(1))

    m = _rx_first([r"\bApoB\b[:\s]+(\d{2,3})\b", r"\bAPOB\b[:\s]+(\d{2,3})\b"], t)
    if m: out["apob"] = _to_int(m.group(1))

    m = _rx_first([r"\bLp\(a\)\b[:\s]+([\d.]+)\s*(nmol/L|mg/dL)?", r"\bLPA\b[:\s]+([\d.]+)\s*(nmol/L|mg/dL)?"], t)
    if m:
        out["lpa"] = _to_int(m.group(1))
        if m.group(2):
            out["lpa_unit"] = m.group(2)

    m = _rx_first([r"\bLPA\s*UNIT[:\s]+(nmol/L|mg/dL)\b"], t)
    if m: out["lpa_unit"] = m.group(1)

    m = _rx_first([r"\bCALCIUM\s*SCORE[:\s]+(\d{1,4})\b", r"\bCAC\b[:=\s]+(\d{1,4})\b", r"\bAgatston[:\s]+(\d{1,4})\b"], t)
    if m: out["cac"] = _to_int(m.group(1))

    m = _rx_first([r"\bA1C\b[:\s]+([\d.]+)\b", r"\bHbA1c\b[:\s]+([\d.]+)\b"], t)
    if m: out["a1c"] = _to_float(m.group(1))

    m = _rx_first([r"\bhs\s*CRP\b[:\s]+([\d.]+)\b", r"\bhscrp\b[:\s]+([\d.]+)\b"], t)
    if m: out["hscrp"] = _to_float(m.group(1))

    return {k: v for k, v in out.items() if v is not None}

def merged_parse(text: str) -> Dict[str, Any]:
    base = parse_smartphrase(text or "") if (text or "").strip() else {}
    fallback = regex_extract_smartphrase(text or "")
    merged = dict(fallback)
    merged.update({k: v for k, v in base.items() if v is not None})
    return merged

# ============================================================
# Apply parsed values to session_state
# ============================================================
TARGET_PARSE_FIELDS = [
    ("age", "Age"),
    ("sex", "Sex"),
    ("sbp", "Systolic BP"),
    ("tc", "Total Cholesterol"),
    ("hdl", "HDL"),
    ("ldl", "LDL"),
    ("apob", "ApoB"),
    ("lpa", "Lp(a)"),
    ("lpa_unit", "Lp(a) unit"),
    ("a1c", "A1c"),
    ("hscrp", "hsCRP"),
    ("cac", "Calcium Score"),
]

def apply_parsed_to_session(parsed: Dict[str, Any]):
    applied: List[str] = []
    missing: List[str] = []

    def set_if_present(src_key: str, state_key: str, transform=lambda x: x, label: Optional[str] = None):
        nonlocal applied, missing
        label = label or src_key
        if parsed.get(src_key) is not None:
            st.session_state[state_key] = transform(parsed[src_key])
            applied.append(label)
        else:
            missing.append(label)

    set_if_present("age", "age_val", lambda v: int(float(v)), "Age")
    set_if_present("sex", "sex_val", lambda v: str(v).strip().upper()[0], "Sex")
    set_if_present("sbp", "sbp_val", lambda v: int(float(v)), "Systolic BP")
    set_if_present("tc", "tc_val", lambda v: int(float(v)), "Total Cholesterol")
    set_if_present("hdl", "hdl_val", lambda v: int(float(v)), "HDL")
    set_if_present("ldl", "ldl_val", lambda v: int(float(v)), "LDL")
    set_if_present("apob", "apob_val", lambda v: int(float(v)), "ApoB")
    set_if_present("lpa", "lpa_val", lambda v: int(float(v)), "Lp(a)")

    if parsed.get("lpa_unit") is not None:
        st.session_state["lpa_unit_val"] = str(parsed["lpa_unit"])
        applied.append("Lp(a) unit")
    else:
        missing.append("Lp(a) unit")

    if parsed.get("a1c") is not None:
        st.session_state["a1c_val"] = float(parsed["a1c"])
        applied.append("A1c")
    else:
        missing.append("A1c")

    if parsed.get("hscrp") is not None:
        st.session_state["hscrp_val"] = float(parsed["hscrp"])
        applied.append("hsCRP")
    else:
        missing.append("hsCRP")

    if parsed.get("cac") is not None:
        st.session_state["cac_known_val"] = "Yes"
        st.session_state["cac_val"] = int(float(parsed["cac"]))
        applied.append("Calcium Score")
    else:
        missing.append("Calcium Score")

    missing = [m for i, m in enumerate(missing) if m not in missing[:i]]
    return applied, missing

# ============================================================
# Report renderer FROM JSON
# ============================================================
def render_report_from_json(out: Dict[str, Any], patient: Patient) -> str:
    lvl = out.get("levels", {})
    rs = out.get("riskSignal", {})
    risk10 = out.get("pooledCohortEquations10yAscvdRisk", {})
    t = out.get("targets", {})
    asp = out.get("aspirin", {})
    conf = out.get("confidence", {})

    lvl_disp = f"{lvl.get('level','—')}"
    if int(lvl.get("level", 0) or 0) == 2 and lvl.get("sublevel"):
        lvl_disp += f" ({lvl.get('sublevel')})"

    if patient.get("ascvd") is True:
        cs = "N/A (clinical ASCVD)"
    elif patient.has("cac"):
        cs = str(int(patient.get("cac")))
    else:
        cs = "Not available"

    if risk10.get("risk_pct") is not None:
        pce = f"{risk10['risk_pct']}% ({risk10.get('category','')})"
    else:
        pce = risk10.get("notes") or ("Not calculated (missing inputs)" if risk10.get("missing") else "Not calculated")

    drivers = out.get("drivers") or []
    plan = out.get("nextActions") or []

    asp_status = asp.get("status", "Not assessed")
    asp_why = short_why(asp.get("rationale", []), max_items=2)
    miss_top = ", ".join(conf.get("top_missing", []) or [])

    html: List[str] = []
    html.append('<div class="report">')
    html.append(f"<h2>LEVELS™ {out.get('version',{}).get('levels','')}</h2>")

    html.append('<div class="section">')
    html.append('<div class="section-title">Summary</div>')
    html.append(f"<p><strong>Assessment:</strong> Level {lvl_disp} — {lvl.get('label','')}</p>")
    if lvl.get("meaning"):
        html.append(f"<p class='muted'>{lvl.get('meaning')}</p>")
    html.append("</div>")

    html.append('<div class="section">')
    html.append('<div class="section-title">Key numbers</div>')
    html.append(f"<p><strong>Calcium Score:</strong> {cs}</p>")
    html.append(f"<p><strong>10-year ASCVD (PCE):</strong> {pce}</p>")
    html.append(f"<p><strong>Risk Signal Score:</strong> {rs.get('score','—')}/100 ({rs.get('band','')})</p>")
    if drivers:
        html.append(f"<p><strong>Drivers:</strong> {'; '.join(drivers)}</p>")
    html.append("</div>")

    html.append('<div class="section">')
    html.append('<div class="section-title">Plan</div>')
    html.append(f"<p><strong>Targets:</strong> ApoB &lt;{t.get('apob','—')} mg/dL; LDL-C &lt;{t.get('ldl','—')} mg/dL</p>")
    if plan:
        html.append("<ul>")
        for s in plan:
            html.append(f"<li>{s}</li>")
        html.append("</ul>")
    html.append(f"<p><strong>Aspirin:</strong> {asp_status}" + (f" <span class='muted'>({asp_why})</span>" if asp_why else "") + "</p>")
    html.append(f"<p class='muted'><strong>Data quality:</strong> {conf.get('confidence','—')} ({conf.get('pct','—')}%)" + (f" — Missing: {miss_top}" if miss_top else "") + "</p>")
    html.append("</div>")

    html.append("</div>")
    return "\n".join(html)

# ============================================================
# Mode
# ============================================================
mode = st.radio("Output mode", ["Compact (default)", "Full (details)"], horizontal=True)

# ============================================================
# SmartPhrase ingest
# ============================================================
st.subheader("SmartPhrase ingest (optional)")

with st.expander("Paste Epic output to auto-fill fields (LDL/ApoB/Lp(a)/Calcium Score)", expanded=False):
    st.markdown(
        "<div class='small-help'>Paste de-identified Epic output. Click <strong>Parse & Apply</strong>. "
        "Parser + fallback extractor improves fill-rate.</div>",
        unsafe_allow_html=True,
    )

    smart_txt = st.text_area(
        "SmartPhrase text (de-identified)",
        height=260,
        placeholder="Paste Epic output here…",
        key="smartphrase_raw",
    )

    if smart_txt and contains_phi(smart_txt):
        st.warning("Possible identifier/date detected in pasted text. Please remove PHI before using.")

    parsed_preview = merged_parse(smart_txt or "") if (smart_txt or "").strip() else {}

    c1, c2, c3 = st.columns([1, 1, 3])
    with c1:
        if st.button("Parse & Apply", type="primary"):
            applied, missing = apply_parsed_to_session(parsed_preview)
            st.success("Applied: " + (", ".join(applied) if applied else "None"))
            if missing:
                st.warning("Missing/unparsed: " + ", ".join(missing))
            st.rerun()

    with c2:
        st.button("Clear pasted text", on_click=clear_pasted_text)

    with c3:
        st.caption("Parsed preview (merged)")
        st.json(parsed_preview)

    if st.session_state.get("_cleared_done"):
        st.success("Pasted text cleared.")
        del st.session_state["_cleared_done"]

    st.markdown("### Parse coverage (explicit)")
    for key, label in TARGET_PARSE_FIELDS:
        ok = parsed_preview.get(key) is not None
        badge = "<span class='badge ok'>parsed</span>" if ok else "<span class='badge miss'>not found</span>"
        val = f": {parsed_preview.get(key)}" if ok else ""
        st.markdown(f"- **{label}** {badge}{val}", unsafe_allow_html=True)

# ============================================================
# Main form
# ============================================================
with st.form("levels_form"):
    st.subheader("Patient context")

    a1, a2, a3 = st.columns(3)
    with a1:
        age = st.number_input("Age (years)", 0, 120, value=int(st.session_state.get("age_val", 52)), step=1, key="age_val")
        sex_default = st.session_state.get("sex_val", "F")
        sex_index = 0 if str(sex_default).upper() == "F" else 1
        sex = st.radio("Sex", ["F", "M"], horizontal=True, index=sex_index, key="sex_val")

    with a2:
        race_options = ["Other (use non-Black coefficients)", "Black"]
        race_default = st.session_state.get("race_val", "Other (use non-Black coefficients)")
        race_index = 1 if race_default == "Black" else 0
        race = st.radio("Race (calculator)", race_options, horizontal=False, index=race_index, key="race_val")

    with a3:
        ascvd = st.radio("ASCVD (clinical)", ["No", "Yes"], horizontal=True)

    fhx_choice = st.selectbox("Premature family history (Father <55; Mother <65)", [
        "None / Unknown",
        "Father with premature ASCVD (MI/stroke/PCI/CABG/PAD) <55",
        "Mother with premature ASCVD (MI/stroke/PCI/CABG/PAD) <65",
        "Sibling with premature ASCVD",
        "Multiple first-degree relatives",
        "Other premature relative",
    ], index=0)

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Cardiometabolic profile")

    b1, b2, b3 = st.columns(3)
    with b1:
        sbp = st.number_input("Systolic BP (mmHg)", 60, 250, value=int(st.session_state.get("sbp_val", 130)), step=1, key="sbp_val")
        bp_default = st.session_state.get("bp_treated_val", "No")
        bp_index = 1 if bp_default == "Yes" else 0
        bp_treated = st.radio("On BP meds?", ["No", "Yes"], horizontal=True, index=bp_index, key="bp_treated_val")

    with b2:
        sm_default = st.session_state.get("smoking_val", "No")
        sm_index = 1 if sm_default == "Yes" else 0
        smoking = st.radio("Smoking (current)", ["No", "Yes"], horizontal=True, index=sm_index, key="smoking_val")

        dm_default = st.session_state.get("diabetes_choice_val", "No")
        dm_index = 1 if dm_default == "Yes" else 0
        diabetes_choice = st.radio("Diabetes (manual)", ["No", "Yes"], horizontal=True, index=dm_index, key="diabetes_choice_val")

    with b3:
        a1c = st.number_input("A1c (%)", 0.0, 15.0, float(st.session_state.get("a1c_val", 5.0)), step=0.1, format="%.1f", key="a1c_val")
        if a1c >= 6.5:
            st.info("A1c ≥ 6.5% ⇒ Diabetes will be set to YES automatically.")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Labs")

    c1, c2, c3 = st.columns(3)
    with c1:
        tc = st.number_input("Total cholesterol (mg/dL)", 0, 500, value=int(st.session_state.get("tc_val", 210)), step=1, key="tc_val")
        ldl = st.number_input("LDL-C (mg/dL)", 0, 400, value=int(st.session_state.get("ldl_val", 148)), step=1, key="ldl_val")
        hdl = st.number_input("HDL cholesterol (mg/dL)", 0, 150, value=int(st.session_state.get("hdl_val", 45)), step=1, key="hdl_val")
    with c2:
        apob = st.number_input("ApoB (mg/dL)", 0, 300, value=int(st.session_state.get("apob_val", 112)), step=1, key="apob_val")
        lpa = st.number_input("Lp(a) value", 0, 1000, value=int(st.session_state.get("lpa_val", 165)), step=1, key="lpa_val")
        unit_default = st.session_state.get("lpa_unit_val", "nmol/L")
        unit_index = 0 if str(unit_default) == "nmol/L" else 1
        lpa_unit = st.radio("Lp(a) unit", ["nmol/L", "mg/dL"], horizontal=True, index=unit_index, key="lpa_unit_val")
    with c3:
        hscrp = st.number_input("hsCRP (mg/L) (optional)", 0.0, 50.0, float(st.session_state.get("hscrp_val", 0.0)), step=0.1, format="%.1f", key="hscrp_val")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Imaging — Calcium Score")

    d1, d2 = st.columns([1, 2])
    with d1:
        cac_default = st.session_state.get("cac_known_val", "No")
        cac_known = st.radio("Calcium Score available?", ["Yes", "No"], horizontal=True,
                             index=0 if cac_default == "Yes" else 1, key="cac_known_val")
    with d2:
        cac = st.number_input("Calcium Score (Agatston)", 0, 5000,
                              value=int(st.session_state.get("cac_val", 0)),
                              step=1, key="cac_val") if cac_known == "Yes" else None

    with st.expander("Bleeding risk (for aspirin) — optional"):
        f1, f2, f3 = st.columns(3)
        with f1:
            bleed_gi = st.checkbox("Prior GI bleed / ulcer", value=False)
            bleed_nsaid = st.checkbox("Chronic NSAID/steroid use", value=False)
        with f2:
            bleed_anticoag = st.checkbox("Anticoagulant use", value=False)
            bleed_disorder = st.checkbox("Bleeding disorder / thrombocytopenia", value=False)
        with f3:
            bleed_ich = st.checkbox("Prior intracranial hemorrhage", value=False)
            bleed_ckd = st.checkbox("Advanced CKD / eGFR <45", value=False)

    show_json = st.checkbox("Show JSON (debug)", value=True)
    submitted = st.form_submit_button("Run")

# ============================================================
# Run + output
# ============================================================
if submitted:
    raw_check = " ".join([str(x) for x in [age, sex, race, fhx_choice, ascvd, sbp, bp_treated, smoking, diabetes_choice, a1c,
                                          tc, ldl, hdl, apob, lpa, lpa_unit, hscrp, cac]])
    if contains_phi(raw_check):
        st.error("Possible identifier/date detected. Please remove PHI and retry.")
        st.stop()

    diabetes_effective = True if a1c >= 6.5 else (diabetes_choice == "Yes")

    data = {
        "age": int(age),
        "sex": sex,
        "race": "black" if race == "Black" else "other",
        "ascvd": (ascvd == "Yes"),
        "fhx": (fhx_choice != "None / Unknown"),
        "fhx_detail": fhx_choice,
        "sbp": int(sbp),
        "bp_treated": (bp_treated == "Yes"),
        "smoking": (smoking == "Yes"),
        "diabetes": diabetes_effective,
        "a1c": float(a1c) if a1c > 0 else None,
        "tc": int(tc),
        "ldl": int(ldl),
        "hdl": int(hdl),
        "apob": int(apob),
        "lpa": int(lpa),
        "lpa_unit": lpa_unit,
        "hscrp": float(hscrp) if hscrp and hscrp > 0 else None,
        "cac": int(cac) if cac is not None else None,
        "bleed_gi": bool(bleed_gi),
        "bleed_ich": bool(bleed_ich),
        "bleed_anticoag": bool(bleed_anticoag),
        "bleed_nsaid": bool(bleed_nsaid),
        "bleed_disorder": bool(bleed_disorder),
        "bleed_ckd": bool(bleed_ckd),
    }
    data = {k: v for k, v in data.items() if v is not None}

    patient = Patient(data)
    out = evaluate(patient)

    note_text = render_compact_text(patient, out) if mode.startswith("Compact") else render_full_text(patient, out)
    report_html = render_report_from_json(out, patient)

    rs = out.get("riskSignal", {})
    risk10 = out.get("pooledCohortEquations10yAscvdRisk", {})
    lvl = out.get("levels", {})
    asp = out.get("aspirin", {})

    lvl_disp = f"{lvl.get('level','—')}"
    if int(lvl.get("level", 0) or 0) == 2 and lvl.get("sublevel"):
        lvl_disp += f" ({lvl.get('sublevel')})"

    cs_disp = "—"
    if patient.get("ascvd") is True:
        cs_disp = "N/A"
    elif patient.has("cac"):
        cs_disp = str(int(patient.get("cac")))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Level", lvl_disp)
    m2.metric("Calcium Score", cs_disp)
    m3.metric("Risk Signal Score", f"{rs.get('score','—')}/100")
    m4.metric("10-year ASCVD (PCE)", f"{risk10.get('risk_pct')}%" if risk10.get("risk_pct") is not None else "—")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Clinical report")
    st.markdown(report_html, unsafe_allow_html=True)

    with st.expander("Copy/paste text"):
        st.code(note_text, language="text")

    st.download_button("Download raw text (.txt)", data=note_text.encode("utf-8"),
                       file_name="levels_note.txt", mime="text/plain")
    st.download_button("Download JSON", data=json.dumps(out, indent=2).encode("utf-8"),
                       file_name="levels_output.json", mime="application/json")

    asp_status = asp.get("status", "Not assessed")
    asp_why = short_why(asp.get("rationale", []), max_items=2)
    st.caption(f"Aspirin: {asp_status}" + (f" — Why: {asp_why}" if asp_why else ""))

    if show_json:
        st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
        st.subheader("JSON (debug)")
        st.json(out)

    st.caption(
        f"Versions: {VERSION.get('levels','')} | {VERSION.get('riskSignal','')} | {VERSION.get('riskCalc','')} | {VERSION.get('aspirin','')}. No storage intended."
    )


