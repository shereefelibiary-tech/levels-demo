import json
import re
import streamlit as st
from levels_engine import Patient, evaluate, render_quick_text, VERSION

# ============================================================
# Page + “clinical report” styling
# ============================================================

st.set_page_config(page_title="LEVELS", layout="wide")

st.markdown("""
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
.header-title {
  font-size: 1.15rem;
  font-weight: 800;
  margin: 0 0 4px 0;
}
.header-sub {
  color: rgba(31,41,55,0.60);
  font-size: 0.9rem;
  margin: 0;
}

.hr {
  margin: 10px 0 14px 0;
  border-top: 1px solid rgba(31,41,55,0.12);
}

.report {
  background: #ffffff;
  border: 1px solid rgba(31,41,55,0.12);
  border-radius: 14px;
  padding: 18px 20px;
}

.report h2 {
  font-size: 1.15rem;
  font-weight: 800;
  margin: 0 0 10px 0;
}

.section { margin-top: 14px; }
.section-title {
  font-variant-caps: all-small-caps;
  letter-spacing: 0.08em;
  font-weight: 800;
  font-size: 0.85rem;
  color: #4b5563;
  margin-bottom: 6px;
  border-bottom: 1px solid rgba(31,41,55,0.10);
  padding-bottom: 2px;
}

.section p { margin: 6px 0; line-height: 1.45; }
.section ul { margin: 6px 0 6px 18px; }
.section li { margin: 4px 0; }

.muted { color: #6b7280; font-size: 0.9rem; }
</style>
""", unsafe_allow_html=True)

st.markdown(
    f"""
<div class="header-card">
  <div class="header-title">LEVELS™ {VERSION["levels"]} — De-identified Demo</div>
  <p class="header-sub">Fast entry • radios for common choices • polished clinical report output + raw text export</p>
</div>
""",
    unsafe_allow_html=True
)

st.info("De-identified use only. Do not enter patient identifiers.")

# ============================================================
# Guardrails
# ============================================================

PHI_PATTERNS = [
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
    for pat in PHI_PATTERNS:
        if re.search(pat, s, re.IGNORECASE):
            return True
    return False

# ============================================================
# Clinical report renderer (BUG FIX: don't split mg/dL)
# ============================================================

def render_clinical_report(note_text: str) -> str:
    """
    Converts engine raw text into a polished HTML report.
    IMPORTANT: Next-steps split uses ' / ' (space-slash-space), so mg/dL is never broken.
    """
    lines = [ln.rstrip() for ln in (note_text or "").splitlines()]

    out = []
    out.append('<div class="report">')

    title = next((ln for ln in lines if ln.strip()), "LEVELS™ Output")
    out.append(f"<h2>{title}</h2>")

    def open_section(title_):
        out.append('<div class="section">')
        out.append(f'<div class="section-title">{title_}</div>')

    def close_section():
        out.append("</div>")

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1

        if not line or line == title:
            continue

        # Summary section
        if line.startswith("Level "):
            open_section("Summary")
            out.append(f"<p><strong>{line}</strong></p>")
            # pull labeled lines until next known section
            while i < len(lines):
                nxt = lines[i].strip()
                if not nxt:
                    i += 1
                    continue
                if nxt.startswith(("Risk Signal Score", "Pooled Cohort Equations", "Drivers:", "Targets", "Next:", "Aspirin")):
                    break
                if ":" in nxt:
                    left, right = nxt.split(":", 1)
                    out.append(f"<p><strong>{left.strip()}:</strong> {right.strip()}</p>")
                else:
                    out.append(f"<p>{nxt}</p>")
                i += 1
            close_section()
            continue

        # Key metrics section
        if line.startswith("Risk Signal Score") or line.startswith("Pooled Cohort Equations"):
            open_section("Key metrics")
            j = i - 1
            while j < len(lines):
                ln = lines[j].strip()
                if not ln:
                    j += 1
                    continue
                if ln.startswith(("Drivers:", "Targets", "Next:", "Aspirin")):
                    break
                if ":" in ln:
                    left, right = ln.split(":", 1)
                    out.append(f"<p><strong>{left.strip()}:</strong> {right.strip()}</p>")
                else:
                    out.append(f"<p>{ln}</p>")
                j += 1
            i = j
            close_section()
            continue

        # Drivers section
        if line.startswith("Drivers:"):
            open_section("Primary drivers")
            items = [x.strip() for x in line.split(":", 1)[1].split(";") if x.strip()]
            out.append("<ul>")
            for it in items:
                out.append(f"<li>{it}</li>")
            out.append("</ul>")
            close_section()
            continue

        # Targets section
        if line == "Targets" or line.startswith("Targets"):
            open_section("Targets")
            out.append("<ul>")
            while i < len(lines):
                ln = lines[i].strip()
                if not ln:
                    i += 1
                    continue
                if ln.startswith(("Benefit context", "ESC/EAS", "Next:", "Aspirin")) or ln == "Targets":
                    break
                if ln.startswith("•"):
                    out.append(f"<li>{ln[1:].strip()}</li>")
                else:
                    out.append(f"<li>{ln}</li>")
                i += 1
            out.append("</ul>")
            if i < len(lines) and lines[i].strip().startswith("Benefit context"):
                out.append(f"<p class='muted'>{lines[i].strip()}</p>")
                i += 1
            if i < len(lines) and lines[i].strip().startswith("ESC/EAS"):
                out.append(f"<p class='muted'>{lines[i].strip()}</p>")
                i += 1
            close_section()
            continue

        # Next steps section (FIXED)
        if line.startswith("Next:"):
            open_section("Next steps")
            payload = line.split(":", 1)[1].strip()
            # Only split on " / " so mg/dL is preserved
            if " / " in payload:
                steps = [x.strip() for x in payload.split(" / ") if x.strip()]
            else:
                steps = [payload] if payload else []

            out.append("<ul>")
            for s in steps:
                out.append(f"<li>{s}</li>")
            out.append("</ul>")
            close_section()
            continue

        # Aspirin section
        if line.startswith("Aspirin"):
            open_section("Aspirin")
            out.append(f"<p>{line}</p>")
            close_section()
            continue

        # Fallback
        open_section("Additional")
        out.append(f"<p class='muted'>{line}</p>")
        close_section()

    out.append("</div>")
    return "\n".join(out)

# ============================================================
# Inputs (organized clinical sequence)
# ============================================================

FHX_OPTIONS = [
    "None / Unknown",
    "Father with premature ASCVD (MI/stroke/PCI/CABG/PAD) <55",
    "Mother with premature ASCVD (MI/stroke/PCI/CABG/PAD) <65",
    "Sibling with premature ASCVD",
    "Multiple first-degree relatives",
    "Other premature relative",
]

def fhx_to_bool(choice: str) -> bool:
    return choice is not None and choice != "None / Unknown"

mode = st.radio("Output mode", ["Quick (default)", "Full (details)"], horizontal=True)

with st.form("levels_form"):
    st.subheader("Patient context")

    a1, a2, a3 = st.columns(3)
    with a1:
        age = st.number_input("Age (years)", 0, 120, 52, step=1)
        sex = st.radio("Sex", ["F", "M"], horizontal=True)
    with a2:
        race = st.radio("Race (calculator)", ["Other (use non-Black coefficients)", "Black"], horizontal=False)
    with a3:
        ascvd = st.radio("ASCVD (clinical)", ["No", "Yes"], horizontal=True)

    fhx_choice = st.selectbox("Premature family history (Father <55; Mother <65)", FHX_OPTIONS, index=0)

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Cardiometabolic profile")

    b1, b2, b3 = st.columns(3)
    with b1:
        sbp = st.number_input("Systolic BP (mmHg)", 60, 250, 130, step=1)
        bp_treated = st.radio("On BP meds?", ["No", "Yes"], horizontal=True)
    with b2:
        smoking = st.radio("Smoking (current)", ["No", "Yes"], horizontal=True)
        diabetes_choice = st.radio("Diabetes (manual)", ["No", "Yes"], horizontal=True)
    with b3:
        a1c = st.number_input("A1c (%)", 0.0, 15.0, 5.0, step=0.1, format="%.1f")
        if a1c >= 6.5:
            st.info("A1c ≥ 6.5% ⇒ Diabetes will be set to YES automatically.")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Labs")

    c1, c2, c3 = st.columns(3)
    with c1:
        tc = st.number_input("Total cholesterol (mg/dL)", 0, 500, 210, step=1)
        ldl = st.number_input("LDL-C (mg/dL)", 0, 400, 148, step=1)
        hdl = st.number_input("HDL cholesterol (mg/dL)", 0, 150, 45, step=1)
    with c2:
        apob = st.number_input("ApoB (mg/dL)", 0, 300, 112, step=1)
        lpa = st.number_input("Lp(a) value", 0, 1000, 165, step=1)
        lpa_unit = st.radio("Lp(a) unit", ["nmol/L", "mg/dL"], horizontal=True)
    with c3:
        hscrp = st.number_input("hsCRP (mg/L) (optional)", 0.0, 50.0, 2.7, step=0.1, format="%.1f")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Imaging")

    d1, d2, d3 = st.columns([1, 1, 1])
    with d1:
        cac_known = st.radio("CAC available?", ["Yes", "No"], horizontal=True)
    with d2:
        cac = st.number_input("CAC score (Agatston)", 0, 5000, 0, step=1) if cac_known == "Yes" else None
    with d3:
        st.caption("")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
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

# ============================================================
# Run + output
# ============================================================

if submitted:
    raw_check = " ".join([str(x) for x in [
        age, sex, race, fhx_choice, ascvd, sbp, bp_treated, smoking, diabetes_choice, a1c,
        tc, ldl, hdl, apob, lpa, lpa_unit, hscrp, cac
    ]])
    if contains_phi(raw_check):
        st.error("Possible identifier/date detected. Please remove PHI and retry.")
        st.stop()

    diabetes_effective = True if a1c >= 6.5 else (diabetes_choice == "Yes")

    data = {
        "age": int(age),
        "sex": sex,
        "race": "black" if race == "Black" else "other",
        "ascvd": (ascvd == "Yes"),
        "fhx": fhx_to_bool(fhx_choice),
        "fhx_detail": fhx_choice,

        "sbp": int(sbp),
        "bp_treated": (bp_treated == "Yes"),
        "smoking": (smoking == "Yes"),
        "diabetes": diabetes_effective,
        "a1c": float(a1c) if a1c and a1c > 0 else None,

        "tc": int(tc),
        "ldl": int(ldl),
        "hdl": int(hdl),
        "apob": int(apob),
        "lpa": int(lpa),
        "lpa_unit": lpa_unit,
        "hscrp": float(hscrp) if hscrp and hscrp > 0 else None,

        "cac": int(cac) if cac is not None else None,

        "ra": bool(ra), "psoriasis": bool(psoriasis), "sle": bool(sle),
        "ibd": bool(ibd), "hiv": bool(hiv), "osa": bool(osa), "nafld": bool(nafld),

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

    note_text = render_quick_text(patient, out)
    clinical_html = render_clinical_report(note_text)

    # Metrics row
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

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Clinical report")
    st.markdown(clinical_html, unsafe_allow_html=True)

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

    st.caption(f"Versions: {VERSION['levels']} | {VERSION['riskSignal']} | {VERSION['riskCalc']} | {VERSION['aspirin']}. No storage intended.")


