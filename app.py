import json
import re
import streamlit as st
from levels_engine import Patient, evaluate, render_note, VERSION

st.set_page_config(page_title="LEVELS Demo", layout="wide")
st.title(f"LEVELS™ {VERSION['levels']} — Public Demo (De-identified)")
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

with st.form("levels_form"):
    consent = st.checkbox("I confirm this input contains no patient identifiers (PHI).")

    st.subheader("Core (Levels)")
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
        hscrp = st.number_input("hsCRP (mg/L) (optional)", 0.0, 50.0, 2.7, step=0.1)

    st.subheader("Metabolic")
    m1, m2, m3 = st.columns(3)
    with m1:
        a1c = st.number_input("A1c (%) (optional)", 0.0, 15.0, 0.0, step=0.1)
    with m2:
        diabetes = st.selectbox("Diabetes", ["No", "Yes"])
    with m3:
        smoking = st.selectbox("Smoking (current)", ["No", "Yes"])

    st.subheader("Inflammatory states (optional)")
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

    st.subheader("PCE inputs (10-year ASCVD risk %)")
    d1, d2, d3 = st.columns(3)
    with d1:
        race = st.selectbox("Race (PCE)", ["Other (use non-Black coeffs)", "Black"])
        tc = st.number_input("Total cholesterol (mg/dL)", 0, 500, 210, step=1)
        hdl = st.number_input("HDL cholesterol (mg/dL)", 0, 150, 45, step=1)
    with d2:
        sbp = st.number_input("Systolic BP (mmHg)", 60, 250, 130, step=1)
        bp_treated = st.selectbox("On BP meds?", ["No", "Yes"])
    with d3:
        show_patient_summary = st.checkbox("Show patient-friendly summary", value=True)
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

    submitted = st.form_submit_button("Run Levels")

if submitted:
    if not consent:
        st.error("Please confirm the input contains no PHI.")
        st.stop()

    raw_check = " ".join([str(x) for x in [
        age, sex, ascvd, fhx, ldl, apob, lpa, lpa_unit, cac, hscrp, a1c, diabetes, smoking,
        race, tc, hdl, sbp, bp_treated
    ]])
    if contains_phi(raw_check):
        st.error("Possible identifier/date detected. Please remove PHI and retry.")
        st.stop()

    data = {
        # Levels core
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

        # Metabolic
        "a1c": float(a1c) if a1c and a1c > 0 else None,
        "diabetes": (diabetes == "Yes"),
        "smoking": (smoking == "Yes"),

        # Inflammation flags
        "ra": bool(ra),
        "psoriasis": bool(psoriasis),
        "sle": bool(sle),
        "ibd": bool(ibd),
        "hiv": bool(hiv),
        "osa": bool(osa),
        "nafld": bool(nafld),

        # PCE inputs
        "race": "black" if race == "Black" else "other",
        "tc": int(tc),
        "hdl": int(hdl),
        "sbp": int(sbp),
        "bp_treated": (bp_treated == "Yes"),

        # bleeding risk flags
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
    note = render_note(patient, out)

    st.subheader("Output (copy/paste)")
    st.code(note, language="text")

    st.download_button(
        "Download note (.txt)",
        data=note.encode("utf-8"),
        file_name="levels_note.txt",
        mime="text/plain"
    )
    st.download_button(
        "Download JSON",
        data=json.dumps(out, indent=2).encode("utf-8"),
        file_name="levels_output.json",
        mime="application/json"
    )

    if show_patient_summary:
        st.subheader("Patient-friendly summary (optional)")
        lvl = out["levels"]["label"]
        rs = out["risk_signal"]["score"]
        pce_val = out["pce_10y"].get("risk_pct")
        asp = out["aspirin"]["status"]

        msg = f"**Placement:** {lvl}\n\n"
        msg += f"**Risk Signal Score:** {rs}/100 (numeric summary of biologic + plaque signal; not a 10-year probability).\n\n"
        if pce_val is not None:
            msg += f"**10-year risk estimate (population):** {pce_val}%.\n\n"
        msg += f"**Aspirin note:** {asp}\n\n"
        msg += "Next steps focus on improving cholesterol particle burden (ApoB/LDL), addressing inflammation/metabolic drivers, and using CAC when it helps clarify substrate."
        st.write(msg)

    if show_json:
        st.subheader("JSON (debug / transparency)")
        st.json(out)

    st.caption(f"Versions: Levels {VERSION['levels']} | {VERSION['risk_signal']} | {VERSION['pce']} | {VERSION['aspirin']}. Inputs processed in memory only; no storage intended.")


