import streamlit as st

from smartphrase_ingest.parser import parse_ascvd_block_with_report
from levels_engine import Patient, evaluate, render_quick_text, VERSION

st.set_page_config(page_title="LEVELS", layout="centered")

# --- helper: only update UI fields when parser found a value ---
def set_if_found(key, value):
    if value is not None:
        st.session_state[key] = value

# --- initialize fields so widgets don't jump around ---
DEFAULT_FIELDS = {
    "raw_text": "",
    "age": None, "sex": None,
    "sbp": None, "dbp": None,
    "tc": None, "ldl": None, "hdl": None, "tg": None,
    "apob": None, "lpa": None,
    "a1c": None, "ascvd": None, "cac": None,
    "diabetes": None, "smoker": None, "former_smoker": None,
    "parse_warnings": [], "parse_conflicts": [],
    "sex_override": None, "age_override": None,
}
for k, v in DEFAULT_FIELDS.items():
    st.session_state.setdefault(k, v)

st.markdown(f"### LEVELS (Engine v{VERSION})")

# -------------------------
# 1) Paste + Parse section
# -------------------------
st.markdown("#### Input")
raw_text = st.text_area(
    "Paste SmartPhrase / note block",
    height=260,
    key="raw_text",
)

col1, col2 = st.columns([1, 1])
with col1:
    parse_btn = st.button("Parse textbox", type="primary", use_container_width=True)
with col2:
    clear_btn = st.button("Clear parsed values", use_container_width=True)

if clear_btn:
    for k in [
        "age", "sex", "sbp", "dbp", "tc", "ldl", "hdl", "tg", "apob", "lpa", "a1c", "ascvd", "cac",
        "diabetes", "smoker", "former_smoker",
        "parse_warnings", "parse_conflicts",
        "sex_override", "age_override",
    ]:
        st.session_state[k] = None if k not in ("parse_warnings", "parse_conflicts") else []
    st.success("Cleared parsed values (textbox preserved).")

if parse_btn:
    report = parse_ascvd_block_with_report(raw_text)

    # Displayables
    st.session_state["parse_warnings"] = report.warnings
    st.session_state["parse_conflicts"] = report.conflicts

    # Non-destructive hydration: only set fields if parser found values
    for k, v in report.extracted.items():
        set_if_found(k, v)

# Show parse status
if st.session_state["parse_conflicts"]:
    st.error("Conflicts found:")
    for c in st.session_state["parse_conflicts"]:
        st.write(f"• {c}")

if st.session_state["parse_warnings"]:
    st.warning("Missing / uncertain fields:")
    for w in st.session_state["parse_warnings"]:
        st.write(f"• {w}")

# -------------------------
# 2) Overrides section
# -------------------------
sex_missing = st.session_state.get("sex") is None
age_missing = st.session_state.get("age") is None

if sex_missing:
    st.info("Sex not detected — select manually (used for ASCVD logic).")
    st.session_state["sex_override"] = st.radio(
        "Sex (override)",
        ["M", "F"],
        horizontal=True,
        index=0 if st.session_state.get("sex_override") != "F" else 1,
    )

if age_missing:
    st.info("Age not detected — enter manually.")
    st.session_state["age_override"] = st.number_input("Age (override)", 18, 100, value=55, step=1)

# -------------------------
# 3) Review + Run section
# -------------------------
st.markdown("#### Review & Run")

def _int_or(default, v):
    try:
        return int(v) if v is not None else default
    except Exception:
        return default

def _float_or(default, v):
    try:
        return float(v) if v is not None else default
    except Exception:
        return default

with st.form("run_form"):
    sbp = st.number_input("SBP", 60, 260, value=_int_or(120, st.session_state.get("sbp")), step=1)
    dbp = st.number_input("DBP", 30, 180, value=_int_or(80, st.session_state.get("dbp")), step=1)

    tc  = st.number_input("Total cholesterol", 50, 600, value=_int_or(200, st.session_state.get("tc")), step=1)
    ldl = st.number_input("LDL", 0, 400, value=_int_or(110, st.session_state.get("ldl")), step=1)
    hdl = st.number_input("HDL", 0, 300, value=_int_or(45, st.session_state.get("hdl")), step=1)
    tg  = st.number_input("Triglycerides", 20, 1500, value=_int_or(150, st.session_state.get("tg")), step=1)

    apob = st.number_input("ApoB", 0, 300, value=_int_or(90, st.session_state.get("apob")), step=1)
    lpa  = st.number_input("Lp(a)", 0.0, 500.0, value=_float_or(0.0, st.session_state.get("lpa")), step=1.0)

    a1c   = st.number_input("A1c (%)", 3.0, 20.0, value=_float_or(5.6, st.session_state.get("a1c")), step=0.1)
    ascvd = st.number_input("ASCVD 10-year (%)", 0.0, 100.0, value=_float_or(0.0, st.session_state.get("ascvd")), step=0.1)
    cac   = st.number_input("CAC", 0, 5000, value=_int_or(0, st.session_state.get("cac")), step=1)

    # Optional booleans (keep Unknown option)
    diabetes = st.radio("Diabetes", ["Unknown", "No", "Yes"], horizontal=True)
    smoker = st.radio("Current smoker", ["Unknown", "No", "Yes"], horizontal=True)

    run_btn = st.form_submit_button("Run LEVELS", type="primary", use_container_width=True)

if run_btn:
    sex_final = st.session_state.get("sex") or st.session_state.get("sex_override")
    age_final = st.session_state.get("age") or st.session_state.get("age_override")

    diabetes_val = None if diabetes == "Unknown" else (diabetes == "Yes")
    # A1c override (matches parser behavior)
    if a1c >= 6.5:
        diabetes_val = True

    smoker_val = None if smoker == "Unknown" else (smoker == "Yes")

    st.session_state.update({
        "sex": sex_final,
        "age": int(age_final) if age_final is not None else None,
        "sbp": int(sbp), "dbp": int(dbp),
        "tc": float(tc), "ldl": float(ldl), "hdl": float(hdl), "tg": float(tg),
        "apob": float(apob), "lpa": float(lpa),
        "a1c": float(a1c), "ascvd": float(ascvd), "cac": float(cac),
        "diabetes": diabetes_val, "smoker": smoker_val,
    })

    patient = Patient(
        age=st.session_state["age"],
        sex=st.session_state["sex"],
        sbp=st.session_state["sbp"],
        dbp=st.session_state["dbp"],
        tc=st.session_state["tc"],
        ldl=st.session_state["ldl"],
        hdl=st.session_state["hdl"],
        tg=st.session_state["tg"],
        apob=st.session_state["apob"],
        lpa=st.session_state["lpa"],
        a1c=st.session_state["a1c"],
        ascvd_10y=st.session_state["ascvd"],
        cac=st.session_state["cac"],
        diabetes=st.session_state["diabetes"],
        smoker=st.session_state["smoker"],
        former_smoker=st.session_state.get("former_smoker"),
    )

    result = evaluate(patient)
    output = render_quick_text(result, patient)

    st.markdown("#### Output")
    st.code(output)
