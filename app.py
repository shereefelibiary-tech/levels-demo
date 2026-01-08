import json
import re
import streamlit as st
from levels_engine import Patient, evaluate, render_quick_text, VERSION

# ---- Polished global styling ----
st.set_page_config(page_title="LEVELS", layout="wide")

st.markdown("""
<style>
/* Global font + spacing (best effort in Streamlit) */
html, body, [class*="css"]  {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, "Helvetica Neue", Arial, "Noto Sans", "Liberation Sans", sans-serif;
}
.small-muted { color: rgba(0,0,0,0.6); font-size: 0.9rem; }
.card {
  border: 1px solid rgba(49,51,63,0.15);
  border-radius: 14px;
  padding: 14px 16px;
  background: white;
}
.hdr {
  font-size: 1.15rem;
  font-weight: 700;
  margin-bottom: 6px;
}
.divline { margin: 8px 0 12px 0; border-top: 1px solid rgba(49,51,63,0.12); }
.badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  background: rgba(0,0,0,0.05);
  font-size: 0.85rem;
}
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="card">
  <div class="hdr">LEVELS™ {VERSION["levels"]} — De-identified Demo</div>
  <div class="small-muted">No PHI. Integers for key labs. A1c/hsCRP to tenths. Output designed for quick clinical reference.</div>
</div>
""", unsafe_allow_html=True)

st.warning("⚠️ Do NOT enter names, MRNs, DOBs, dates, addresses, phone numbers, or free-text notes.")

PHI_PATTERNS = [
    r"\b\d{3}-\d{2}-\d{4}\b",
    r"\b\d{2}/\d{2}/\d{4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\bMRN\b|\bMedical Record\b",
    r"@",
    r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"
]
def contains_phi(s: str) -> bool:
    if not s: return False
    for pat in PHI_PATTERNS:
        if re.search(pat, s, re.IGNORECASE):
            return True
    return False

mode = st.radio("Output mode", ["Quick (default)", "Full (details)"], horizontal=True)

with st.form("levels_form"):
    consent = st.checkbox("I confirm this input contains no patient identifiers (PHI).", value=False)

    st.markdown('<div class="divline"></div>', unsafe_allow_html=True)
    st.markdown("### Core (Levels)")

    c1, c2, c3 = st.columns(3)
    with c1:
        age = st.number_input("Age (years)", 0, 120, 52, step=1)
        sex = st.selectbox("Sex", ["F", "M"])
        ascvd = st.selectbox("ASCVD (clinical)", ["No", "Yes"])
        fhx = st.selectbox("Premature family history", ["No", "Yes"])
    with c2:
        ldl = st.number_input("LDL-C (mg/dL)", 0, 400, 148, step=1)
        apob = st.number_input("ApoB (mg/dL)", 0, 300, 112, step=1)
        lpa = st.number_input("Lp(a) value", 0, 1000, 165, step=1)
    with c3:
        lpa_unit = st.selectbox("Lp(a) unit", ["nmol/L", "mg/dL"])
        cac_known = st.selectbox("CAC available?", ["Yes", "No"])
        cac = st.number_input("CAC score (Agatston)", 0, 5000, 0, step=1) if cac_known == "Yes" else None
        hscrp = st.number_input("hsCRP (mg/L) (optional)", 0.0, 50.0, 2.7, step=0.1, format="%.1f")

    st.markdown("### Metabolic")
    m1, m2, m3 = st.columns(3)
    with m1:
        a1c = st.number_input("A1c (%) (optional)", 0.0, 15.0, 5.0, step=0.1, format="%.1f")
    with m2:
        diabetes = st.selectbox("Diabetes", ["No", "Yes"])
    with m3:
        smoking = st.selectbox("Smoking (current)", ["No", "Yes"])

    st.markdown("### Inflammatory states (optional)")
    i1, i2, i3 = st.columns(3)
    with i1:
        ra = st.checkbox("Rheumatoid arthritis", value=False)
        psoriasis = st.checkbox("Psoriasis", value=False)
    with i2:
        sle = st.checkbox("SLE", value=False)
        ibd = st.checkbox("IBD", value=False)
    with i3:
        hiv = st.checkbox("HIV", value=False)
        osa = st.checkbox("OSA", value=False)
        nafld = st.checkbox("NAFLD/MASLD", value=False)

    st.markdown("### Pooled Cohort Equations (10-year ASCVD risk)")
    d1, d2, d3 = st.columns(3)
    with d1:
        race = st.selectbox("Race (calculator)", ["Other (use non-Black coefficients)", "Black"])
        tc = st.number_input("Total cholesterol (mg/dL)", 0, 500, 210, step=1)
        hdl = st.number_input("HDL cholesterol (mg/dL)", 0, 150, 45, step=1)
    with d2:
        sbp = st.number_input("Systolic BP (mmHg)", 60, 250, 130, step=1)
        bp_treated = st.selectbox("On BP meds?", ["No", "Yes"])
    with d3:
        show_json = st.checkbox("Show JSON", value=True)

    with st.expander("Bleeding risk (for aspirin decision-support) — optional"):
        b1, b2, b3 = st.columns(3)
        with b1:
            bleed_gi = st.checkbox("Prior GI bleed / ulcer", value=False)
            bleed_nsaid = st.checkbox("Chronic NSAID/steroid use", value=False)
        with b2:
            bleed_anticoag = st.checkbox("Anticoagulant use", value=False)
            bleed_disorder = st.checkbox("Bleeding disorder / thrombocytopenia", value=False)
        with b3:
            bleed_ich = st.checkbox("Prior intracranial hemorrhage", value=False)
            bleed_ckd = st.checkbox("Advanced CKD / eGFR <45", value=False)

    submitted = st.form_submit_button("Run")

if submitted:
    if not consent:
        st.error("Please confirm no PHI is included.")
        st.stop()

    raw_check = " ".join([str(x) for x in [age, sex, ascvd, fhx, ldl, apob, lpa, lpa_unit, cac, hscrp, a1c, diabetes, smoking, race, tc, hdl, sbp, bp_treated]])
    if contains_phi(raw_check):
        st.error("Possible identifier/date detected. Please remove PHI and retry.")
        st.stop()

    data = {
        "age": int(age),
        "sex": sex,
        "ascvd": (ascvd == "Yes"),
        "fhx": (fhx == "Yes"),
        "ldl": int(ldl),
        "apob": int(apob),
        "lpa": int(lpa),
        "lpa_unit": lpa_unit,
        "cac": int(cac) if cac is not None else None,
        "hscrp": float(hscrp) if hscrp and hscrp > 0 else None,
        "a1c": float(a1c) if a1c and a1c > 0 else None,
        "diabetes": (diabetes == "Yes"),
        "smoking": (smoking == "Yes"),
        "ra": bool(ra), "psoriasis": bool(psoriasis), "sle": bool(sle), "ibd": bool(ibd), "hiv": bool(hiv),
        "osa": bool(osa), "nafld": bool(nafld),
        "race": "black" if race == "Black" else "other",
        "tc": int(tc),
        "hdl": int(hdl),
        "sbp": int(sbp),
        "bp_treated": (bp_treated == "Yes"),
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

    # Top metrics row
    rs = out["riskSignal"]
    risk10 = out["pooledCohortEquations10yAscvdRisk"]
    lvl = out["levels"]

    m1, m2, m3 = st.columns(3)
    m1.metric("Level", f"{lvl['level']}", help=lvl["label"])
    m2.metric("Risk Signal Score", f"{rs['score']}/100", help=rs["note"])
    if risk10.get("risk_pct") is not None:
        m3.metric("10-year ASCVD risk", f"{risk10['risk_pct']}%", help="Pooled Cohort Equations (population estimate)")
    else:
        m3.metric("10-year ASCVD risk", "—", help="Not calculated")

    st.markdown('<div class="divline"></div>', unsafe_allow_html=True)

    # Output
    note = render_quick_text(patient, out)
    st.subheader("Output")

# --- Pretty display (markdown) ---
md = (
    note.replace("LEVELS™", "## LEVELS™")  # make the title a markdown header
        .replace("Level", "**Level**", 1)  # first occurrence only (light touch)
)

# Better: explicitly format the lines
lines = note.splitlines()
md_lines = []
for line in lines:
    if line.startswith("LEVELS™"):
        md_lines.append(f"## {line}")
        continue
    if line.startswith("Level "):
        md_lines.append(f"**{line}**")
        continue
    if ":" in line and not line.strip().startswith("•"):
        # Bold label before colon (e.g., "Confidence: ...")
        left, right = line.split(":", 1)
        md_lines.append(f"**{left.strip()}:** {right.strip()}")
        continue
    # Keep bullets as-is (markdown bullets)
    if line.strip().startswith("•"):
        md_lines.append(f"- {line.strip()[1:].strip()}")
        continue
    if line.strip() == "":
        md_lines.append("")
        continue
    md_lines.append(line)

md = "\n".join(md_lines)

st.markdown(md)

# --- Copy-friendly raw text export ---
st.download_button(
    "Download raw text (.txt)",
    data=note.encode("utf-8"),
    file_name="levels_note.txt",
    mime="text/plain"
)

# Optional: show raw text in an expander for copy/paste
with st.expander("Show raw text (copy/paste)"):
    st.code(note, language="text")

    st.download_button("Download JSON", data=json.dumps(out, indent=2).encode("utf-8"), file_name="levels_output.json", mime="application/json")

    if show_json:
        st.subheader("JSON (debug)")
        st.json(out)

    st.caption(f"Versions: {VERSION['levels']} | {VERSION['riskSignal']} | {VERSION['riskCalc']} | {VERSION['aspirin']}. No storage intended.")


