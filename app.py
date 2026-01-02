import streamlit as st
from levels_engine import Patient, evaluate_levels_banded, render_note

st.set_page_config(page_title="LEVELS v1.1 Demo", layout="wide")

st.title("LEVELS™ v1.1 — Public Demo (De-identified)")
st.warning(
    "⚠️ Do NOT enter names, MRNs, DOBs, addresses, dates, or free-text notes. "
    "Use de-identified values only."
)

with st.form("levels_form"):
    consent = st.checkbox("I confirm this input contains no patient identifiers (PHI).")

    st.subheader("Core inputs")
    c1, c2, c3 = st.columns(3)

    with c1:
        age = st.number_input("Age (years)", 0, 120, 52)
        sex = st.selectbox("Sex (optional)", ["", "F", "M", "Other"])
        ascvd = st.selectbox("ASCVD (clinical)", ["No", "Yes"])

    with c2:
        ldl = st.number_input("LDL-C (mg/dL)", 0.0, 400.0, 148.0)
        apob = st.number_input("ApoB (mg/dL)", 0.0, 300.0, 112.0)
        non_hdl = st.number_input("Non-HDL-C (mg/dL) (optional)", 0.0, 400.0, 0.0)

    with c3:
        lpa = st.number_input("Lp(a) value", 0.0, 1000.0, 165.0)
        lpa_unit = st.selectbox("Lp(a) unit", ["nmol/L", "mg/dL"])
        cac_known = st.selectbox("CAC available?", ["Yes", "No"])

    st.subheader("Risk enhancers / overlays")
    c4, c5, c6 = st.columns(3)

    with c4:
        fhx = st.selectbox("Premature family history", ["No", "Yes"])
        smoking = st.selectbox("Smoking (current)", ["No", "Yes"])
        diabetes = st.selectbox("Diabetes", ["No", "Yes"])

    with c5:
        hscrp = st.number_input("hsCRP (mg/L) (optional)", 0.0, 50.0, 2.7)
        # inflammatory diseases
        ra = st.selectbox("Rheumatoid arthritis", ["No", "Yes"])
        psoriasis = st.selectbox("Psoriasis", ["No", "Yes"])

    with c6:
        sle = st.selectbox("SLE", ["No", "Yes"])
        ibd = st.selectbox("IBD", ["No", "Yes"])
        hiv = st.selectbox("HIV", ["No", "Yes"])

    with st.expander("Advanced (optional)"):
        c7, c8, c9 = st.columns(3)
        with c7:
            osa = st.selectbox("OSA", ["No", "Yes"])
            nafld = st.selectbox("NAFLD/MASLD", ["No", "Yes"])
        with c8:
            a1c = st.number_input("A1c (%) (optional)", 0.0, 15.0, 0.0)
        with c9:
            ccta_obstructive = st.selectbox("CCTA obstructive CAD ≥50% (optional)", ["Unknown", "No", "Yes"])

    # CAC score only if available
    cac = None
    if cac_known == "Yes":
        cac = st.number_input("CAC score (Agatston)", 0, 5000, 0)

    submitted = st.form_submit_button("Run Levels")

if submitted:
    if not consent:
        st.error("Please confirm the input contains no PHI.")
        st.stop()

    # Build patient dict (no identifiers; no dates)
    data = {
        "age": int(age),
        "sex": sex if sex else None,
        "ascvd": (ascvd == "Yes"),
        "ldl": float(ldl),
        "apob": float(apob),
        "non_hdl": float(non_hdl) if non_hdl and non_hdl > 0 else None,
        "lpa": float(lpa),
        "lpa_unit": lpa_unit,
        "fhx": (fhx == "Yes"),
        "smoking": (smoking == "Yes"),
        "diabetes": (diabetes == "Yes"),
        "hscrp": float(hscrp) if hscrp and hscrp > 0 else None,
        "ra": (ra == "Yes"),
        "psoriasis": (psoriasis == "Yes"),
        "sle": (sle == "Yes"),
        "ibd": (ibd == "Yes"),
        "hiv": (hiv == "Yes"),
        "osa": (osa == "Yes"),
        "nafld": (nafld == "Yes"),
    }

    if cac is not None:
        data["cac"] = int(cac)

    if a1c and a1c > 0:
        data["a1c"] = float(a1c)

    if ccta_obstructive != "Unknown":
        data["ccta_obstructive"] = (ccta_obstructive == "Yes")

    # remove None values
    data = {k: v for k, v in data.items() if v is not None}

    patient = Patient(data)
    result = evaluate_levels_banded(patient)
    note = render_note(patient, result)

    st.subheader("Output (copy/paste)")
    st.code(note, language="text")

    with st.expander("Show parsed input + JSON"):
        st.json(patient.data)
        st.json(result)

    st.caption("Inputs are processed in memory only and are not stored by this app.")

