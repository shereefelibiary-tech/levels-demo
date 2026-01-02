import streamlit as st
from levels_engine import parse_levels_smartphrase, evaluate_levels_banded, render_note, Patient

st.set_page_config(page_title="LEVELS Demo", layout="wide")

st.title("LEVELS™ v1.1 — Public Demo (De-identified)")
st.warning(
    "⚠️ Do NOT enter names, MRNs, DOBs, dates, or free-text notes. "
    "This tool is for de-identified data only."
)

with st.form("levels_form"):
    consent = st.checkbox("I confirm this input contains no patient identifiers (PHI).")

    col1, col2, col3 = st.columns(3)

    with col1:
        age = st.number_input("Age (years)", 0, 120, 52)
        ascvd = st.selectbox("ASCVD (clinical)", ["No", "Yes"])
        fhx = st.selectbox("Premature family history", ["No", "Yes"])

    with col2:
        ldl = st.number_input("LDL-C (mg/dL)", 0.0, 400.0, 148.0)
        apob = st.number_input("ApoB (mg/dL)", 0.0, 300.0, 112.0)
        lpa = st.number_input("Lp(a)", 0.0, 1000.0, 165.0)

    with col3:
        lpa_unit = st.selectbox("Lp(a) unit", ["nmol/L", "mg/dL"])
        cac = st.number_input("CAC score (Agatston)", 0, 5000, 0)
        hscrp = st.number_input("hsCRP (mg/L)", 0.0, 50.0, 2.7)

    submitted = st.form_submit_button("Run Levels")

if submitted:
    if not consent:
        st.error("Please confirm no PHI is included.")
        st.stop()

    data = {
        "age": age,
        "ascvd": ascvd == "Yes",
        "fhx": fhx == "Yes",
        "ldl": ldl,
        "apob": apob,
        "lpa": lpa,
        "lpa_unit": lpa_unit,
        "cac": cac,
        "hscrp": hscrp,
    }

    patient = Patient(data)
    result = evaluate_levels_banded(patient)
    note = render_note(patient, result)

    st.subheader("Output (copy / paste)")
    st.code(note, language="text")

    st.caption("Inputs are processed in memory only and are not stored.")
