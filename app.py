import json
import re
import streamlit as st
from levels_engine import Patient, evaluate, render_quick_text, VERSION

# ---- Polished global styling ----
st.set_page_config(page_title="LEVELS", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"]  {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, "Helvetica Neue", Arial, sans-serif;
}
.small-muted { color: rgba(0,0,0,0.6); font-size: 0.9rem; }
.card {
  border: 1px solid rgba(49,51,63,0.15);
  border-radius: 14px;
  padding: 14px 16px;
  background: white;
}
.hdr { font-size: 1.15rem; font-weight: 700; margin-bottom: 6px; }
.divline { margin: 10px 0 14px 0; border-top: 1px solid rgba(49,51,63,0.12); }
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="card">
  <div class="hdr">LEVELS™ {VERSION["levels"]} — De-identified Demo</div>
  <div class="small-muted">Organized for quick clinical entry. Output rendered as polished markdown + raw text export.</div>
</div>
""", unsafe_allow_html=True)

st.warning("⚠️ Do NOT enter names, MRNs, DOBs, dates, addresses, phone numbers, or free-text notes.")

# Minimal PHI guardrails (mostly redundant since this is structured)
PHI_PATTERNS = [
    r"\b\d{3}-\d{2}-\d{4}\b",
    r"\b\d{2}/\d{2}/\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\bMRN\b|\bMedical Record\b",
    r"@",
    r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"
]
def contains_phi(s: str) -> bool:
    if not s:
        return False
    for pat in PHI_PATTERNS:
        if re.search(pat, s, re.IGNORECASE):
            return True
    return False

mode = st.radio("Output mode", ["Quick (default)", "Full (details)"], horizontal=True)

# Family history choices
FHX_OPTIONS = [
    "None / Unknown",
    "Father with premature ASCVD (<55)",
    "Mother with premature ASCVD (<65)",
    "Sibling with premature ASCVD",
    "Multiple 1st-degree relatives",
    "Other premature relative"
]

def fhx_to_bool(choice: str) -> bool:
    return choice is not None and choice != "None / Unknown"

with st.form("levels_form"):
    consent = st.checkbox("I confirm this input contains no patient identifiers (PHI).", value=False)

    st.markdown('<div class="divline"></div>', unsafe_allow_html=True)
    st.subheader("Patient context")

    a1, a2, a3 = st.columns(3)
    with a1:
        age = st.number_input("Age (years)", 0, 120, 52, step=1)
        sex = st.selectbox("Sex", ["F", "M"])
        race = st.selectbox("Race (calculator)", ["Other (use non-Black coefficients)", "Black"])
    with a2:
        fhx_choice = st.selectbox("Premature family history (detail)", FHX_OPTIONS, index=0)
        ascvd = st.selectbox("ASCVD (clinical)", ["No", "Yes"])
    with a3:
        # keep empty for balance; you can add optional fields later
        st.caption("")

    st.markdown('<div class="divline"></div>', unsafe_allow_html=True)
    st.subheader("Vitals & metabolic")

    b1, b2, b3 = st.columns(3)
    with b1:
        sbp = st.number_input("Systolic BP (mmHg)", 60, 250, 130, step=1)
        bp_treated = st.selectbox("On BP meds?", ["No", "Yes"])
    with b2:
        smoking = st.selectbox("Smoking (current)", ["No", "Yes"])
        diabetes = st.selectbox("Diabetes", ["No", "Yes"])
    with b3:
        # A1c default 5.0, tenths
        a1c = st.number_input("A1c (%) (optional)", 0.0, 15.0, 5.0, step=0.1, format="%.1f")

    st.markdown('<div class="divline"></div>', unsafe_allow_html=True)
    st.subheader("Labs")

    c1, c2, c3 = st.columns(3)
    with c1:
        ldl = st.number_input("LDL-C (mg/dL)", 0, 400, 148, step=1)
        apob = st.number_input("ApoB (mg/dL)", 0, 300, 112, step=1)
    with c2:
        lpa = st.number_input("Lp(a) value", 0, 1000, 165, step=1)
        lpa_unit = st.selectbox("Lp(a) unit", ["nmol/L", "mg/dL"])
    with c3:
        tc = st.number_input("Total cholesterol (mg/dL)", 0, 500, 210, step=1)
        hdl = st.number_input("HDL cholesterol (mg/dL)", 0, 150, 45, step=1)
        # keep hsCRP default 2.7 (demo-friendly)
        hscrp = st.number_input("hsCRP (mg/L) (optional)", 0.0, 50.0, 2.7, step=0.1, format="%.1f")

    st.markdown('<div class="divline"></div>', unsafe_allow_html=True)
    st.subheader("Imaging")

    d1, d2 = st.columns([1, 2])
    with d1:
        cac_known = st.selectbox("CAC available?", ["Yes", "No"])
    with d2:
        cac = st.number_input("CAC score (Agatston)", 0, 5000, 0, step=1) if cac_known == "Yes" else None

    st.markdown('<div class="divline"></div>', unsafe_allow_html=True)
    st.subheader("Inflammatory states (optional)")

    e1, e2, e3 = st.columns(3)
    with e1:
        ra = st.checkbox("Rheumatoid arthritis", value=False)
        psoriasis = st.checkbox("Psoriasis", value=False)
    with e2:
        sle = st.checkbox("SLE", value=False)
        ibd = st.checkbox("IBD", value=False)
    with e3:
        hiv = st.checkbox("HIV", value=False)
        osa = st.checkbox("OSA", value=False)
        nafld = st.checkbox("NAFLD/MASLD", value=False)

    with st.expander("Bleeding risk (for aspirin decision-support) — optional"):
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

if submitted:
    if not consent:
        st.error("Please confirm no PHI is included.")
        st.stop()

    raw_check = " ".join([str(x) for x in [
        age, sex, race, fhx_choice, ascvd, sbp, bp_treated, smoking, diabetes, a1c,
        ldl, apob, lpa, lpa_unit, tc, hdl, hscrp, cac
    ]])
    if contains_phi(raw_check):
        st.error("Possible identifier/date detected. Please remove PHI and retry.")
        st.stop()

    data = {
        # Patient context
        "age": int(age),
        "sex": sex,
        "race": "black" if race == "Black" else "other",
        "ascvd": (ascvd == "Yes"),
        "fhx": fhx_to_bool(fhx_choice),
        "fhx_detail": fhx_choice,  # optional, engine may ignore

        # Vitals/metabolic
        "sbp": int(sbp),
        "bp_treated": (bp_treated == "Yes"),
        "smoking": (smoking == "Yes"),
        "diabetes": (diabetes == "Yes"),
        "a1c": float(a1c) if a1c and a1c > 0 else None,

        # Labs (integers where appropriate)
        "ldl": int(ldl),
        "apob": int(apob),
        "lpa": int(lpa),
        "lpa_unit": lpa_unit,
        "tc": int(tc),
        "hdl": int(hdl),
        "hscrp": float(hscrp) if hscrp and hscrp > 0 else None,

        # Imaging
        "cac": int(cac) if cac is not None else None,

        # Inflammatory states
        "ra": bool(ra), "psoriasis": bool(psoriasis), "sle": bool(sle),
        "ibd": bool(ibd), "hiv": bool(hiv), "osa": bool(osa), "nafld": bool(nafld),

        # Bleeding risk flags
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

    # Use the engine's text (Quick) as the single source for export
    note_text = render_quick_text(patient, out)

    # Build pretty markdown from the raw text (bold labels, bullets, headings)
    lines = note_text.splitlines()
    md_lines = []
    for line in lines:
        if line.startswith("LEVELS™"):
            md_lines.append(f"## {line}")
            continue
        if line.startswith("Level ") or line.startswith("Atherosclerotic disease burden") or line.startswith("Confidence"):
            if ":" in line:
                left, right = line.split(":", 1)
                md_lines.append(f"**{left.strip()}:** {right.strip()}")
            else:
                md_lines.append(f"**{line.strip()}**")
            continue
        if line.strip().startswith("•"):
            md_lines.append(f"- {line.strip()[1:].strip()}")
            continue
        if ":" in line and not line.strip().startswith("-"):
            # Bold labels before colon
            left, right = line.split(":", 1)
            md_lines.append(f"**{left.strip()}:** {right.strip()}")
            continue
        md_lines.append(line)

    pretty_md = "\n".join(md_lines)

    # Metrics row (nice glance)
    rs = out.get("riskSignal", {})
    risk10 = out.get("pooledCohortEquations10yAscvdRisk", {})
    lvl = out.get("levels", {})
    m1, m2, m3 = st.columns(3)
    m1.metric("Level", f"{lvl.get('level','—')}")
    m2.metric("Risk Signal Score", f"{rs.get('score','—')}/100")
    if risk10.get("risk_pct") is not None:
        m3.metric("10-year ASCVD risk", f"{risk10.get('risk_pct')}%")
    else:
        m3.metric("10-year ASCVD risk", "—")

    st.markdown('<div class="divline"></div>', unsafe_allow_html=True)

    st.subheader("Output (polished)")
    st.markdown(pretty_md)

    st.download_button(
        "Download raw text (.txt)",
        data=note_text.encode("utf-8"),
        file_name="levels_note.txt",
        mime="text/plain"
    )
    st.download_button(
        "Download JSON",
        data=json.dumps(out, indent=2).encode("utf-8"),
        file_name="levels_output.json",
        mime="application/json"
    )

    with st.expander("Show raw text (copy/paste)"):
        st.code(note_text, language="text")

    if show_json:
        st.subheader("JSON (debug)")
        st.json(out)

    st.caption(f"Versions: {VERSION['levels']} | {VERSION['riskSignal']} | {VERSION['riskCalc']} | {VERSION['aspirin']}. Inputs processed in memory only; no storage intended.")

