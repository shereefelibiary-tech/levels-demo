# app.py
# LEVELS UI (Streamlit) — restores your prior UI and fixes the bugs you listed.
#
# This version fixes the Streamlit Session State error by:
# - For any widget with a `key=...`, we DO NOT pass `value=` or `index=`.
# - We control defaults ONLY via st.session_state.setdefault(...).
#
# Preserves everything you asked for up to now:
# - Same wide layout + same UI sections + same styling + PHI guardrails
# - SmartPhrase ingest (paste → parse → apply) with explicit coverage flags
# - Added: A1c parsed + applied
# - Added: Clear auto-filled fields button
# - Defaults now mean "no value yet" (numeric fields default to 0 / 0.0 and are treated as empty)
# - Output: Clinical report is primary; others moved into expanders
# - Terminology: Sex → Gender, Black → African American (UI labels)
# - HDL max widened to avoid StreamlitValueAboveMaxError
#
# NOTE: Streamlit number_input cannot be blank, so 0 is used as empty placeholder.

import json
import re
import streamlit as st

from smartphrase_ingest.parser import parse_smartphrase
from levels_engine import Patient, evaluate, render_quick_text, VERSION, short_why

# ============================================================
# Page + “clinical report” styling
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
.small-help { color: rgba(31,41,55,0.70); font-size: 0.88rem; }

.kv {
  display:flex; gap:10px; flex-wrap:wrap;
  border: 1px solid rgba(31,41,55,0.10);
  background:#fbfbfb;
  border-radius:12px;
  padding:10px 12px;
  margin-top:10px;
}
.kv div { font-size: 0.9rem; }
.kv strong { font-weight: 800; }

.badge {
  display:inline-block;
  padding:2px 8px;
  border-radius:999px;
  border:1px solid rgba(31,41,55,0.15);
  background:#fff;
  font-size:0.82rem;
  margin-left:6px;
}
.ok { border-color: rgba(16,185,129,0.35); background: rgba(16,185,129,0.08); }
.miss { border-color: rgba(245,158,11,0.35); background: rgba(245,158,11,0.10); }

.level-card {
  border: 1px solid rgba(31,41,55,0.10);
  border-radius: 12px;
  padding: 12px 12px;
  background: rgba(31,41,55,0.03);
  margin-top: 10px;
}
.level-card h3 {
  font-size: 0.95rem;
  margin: 0 0 6px 0;
  font-weight: 800;
}
.pill {
  display:inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  border:1px solid rgba(31,41,55,0.16);
  background:#fff;
  font-size:0.80rem;
  font-weight:800;
}
.pill-green { border-color: rgba(16,185,129,0.35); background: rgba(16,185,129,0.08); }
.pill-yellow { border-color: rgba(245,158,11,0.35); background: rgba(245,158,11,0.10); }
.pill-red { border-color: rgba(239,68,68,0.28); background: rgba(239,68,68,0.09); }

.next-row {
  display:flex; gap:8px; flex-wrap:wrap;
  margin-top: 8px;
}
.next-chip {
  display:inline-block;
  padding: 6px 10px;
  border-radius: 10px;
  border:1px solid rgba(31,41,55,0.14);
  background:#fff;
  font-size:0.86rem;
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""
<div class="header-card">
  <div class="header-title">LEVELS™ {VERSION["levels"]} — De-identified Demo</div>
  <p class="header-sub">Fast entry • radios for common choices • SmartPhrase paste → auto-fill (LDL/ApoB/Lp(a)/CAC/A1c) • clinical report output</p>
</div>
""",
    unsafe_allow_html=True,
)

st.info("De-identified use only. Do not enter patient identifiers.")

# ============================================================
# Guardrails
# ============================================================
PHI_PATTERNS = [
    r"\b\d{3}-\d{2}-\d{4}\b",              # SSN-like
    r"\b\d{2}/\d{2}/\d{4}\b",              # date
    r"\b\d{4}-\d{2}-\d{2}\b",              # ISO date
    r"\bMRN\b|\bMedical Record\b",
    r"@",                                  # email-ish
    r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",  # phone
]

def contains_phi(s: str) -> bool:
    if not s:
        return False
    for pat in PHI_PATTERNS:
        if re.search(pat, s, re.IGNORECASE):
            return True
    return False

# ============================================================
# Clinical report renderer (mg/dL-safe Next split)
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

        if line.startswith("Level "):
            open_section("Summary")
            out.append(f"<p><strong>{line}</strong></p>")
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

        if line.startswith("Drivers:"):
            open_section("Primary drivers")
            items = [x.strip() for x in line.split(":", 1)[1].split(";") if x.strip()]
            out.append("<ul>")
            for it in items:
                out.append(f"<li>{it}</li>")
            out.append("</ul>")
            close_section()
            continue

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

        if line.startswith("Next:"):
            open_section("Next steps")
            payload = line.split(":", 1)[1].strip()
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

        if line.startswith("Aspirin") or line.startswith("Why:"):
            open_section("Aspirin")
            out.append(f"<p>{line}</p>")
            if i < len(lines) and lines[i].strip().startswith("Why:"):
                out.append(f"<p class='muted'>{lines[i].strip()}</p>")
                i += 1
            close_section()
            continue

        open_section("Additional")
        out.append(f"<p class='muted'>{line}</p>")
        close_section()

    out.append("</div>")
    return "\n".join(out)

# ============================================================
# Helpers
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

TARGET_PARSE_FIELDS = [
    ("age", "Age"),
    ("sex", "Gender"),
    ("sbp", "Systolic BP"),
    ("tc", "Total Cholesterol"),
    ("hdl", "HDL"),
    ("ldl", "LDL"),
    ("apob", "ApoB"),
    ("lpa", "Lp(a)"),
    ("lpa_unit", "Lp(a) unit"),
    ("cac", "CAC"),
    ("a1c", "A1c"),
    ("ascvd_10y", "ASCVD 10-year risk (if present)"),
]

def apply_parsed_to_session(parsed: dict):
    """
    Applies parsed values into Streamlit session_state keys used by the form widgets.
    Returns (applied_list, missing_list) for explicit flagging.
    """
    applied = []
    missing = []

    def set_if_present(src_key, state_key, transform=lambda x: x, label=None):
        nonlocal applied, missing
        label = label or src_key
        if parsed.get(src_key) is not None:
            st.session_state[state_key] = transform(parsed[src_key])
            applied.append(label)
        else:
            missing.append(label)

    set_if_present("age", "age_val", lambda v: int(v), "Age")
    set_if_present("sex", "sex_val", lambda v: v, "Gender")
    set_if_present("sbp", "sbp_val", lambda v: int(v), "Systolic BP")

    set_if_present("tc", "tc_val", lambda v: int(v), "Total Cholesterol")
    set_if_present("hdl", "hdl_val", lambda v: int(v), "HDL")
    set_if_present("ldl", "ldl_val", lambda v: int(v), "LDL")

    set_if_present("apob", "apob_val", lambda v: int(v), "ApoB")
    set_if_present("lpa", "lpa_val", lambda v: int(v), "Lp(a)")

    if parsed.get("lpa_unit") is not None:
        st.session_state["lpa_unit_val"] = parsed["lpa_unit"]
        applied.append("Lp(a) unit")
    else:
        missing.append("Lp(a) unit")

    if parsed.get("a1c") is not None:
        st.session_state["a1c_val"] = float(parsed["a1c"])
        applied.append("A1c")
    else:
        missing.append("A1c")

    if parsed.get("cac") is not None:
        st.session_state["cac_known_val"] = "Yes"
        st.session_state["cac_val"] = int(parsed["cac"])
        applied.append("CAC")
    else:
        missing.append("CAC")

    if parsed.get("smoker") is not None:
        st.session_state["smoking_val"] = "Yes" if parsed["smoker"] else "No"
        applied.append("Smoking")

    if parsed.get("diabetes") is not None:
        st.session_state["diabetes_choice_val"] = "Yes" if parsed["diabetes"] else "No"
        applied.append("Diabetes(manual)")

    if parsed.get("bpTreated") is not None:
        st.session_state["bp_treated_val"] = "Yes" if parsed["bpTreated"] else "No"
        applied.append("BP meds")

    if parsed.get("africanAmerican") is not None:
        st.session_state["race_val"] = (
            "African American" if parsed["africanAmerican"] else "Other (use non-African American coefficients)"
        )
        applied.append("Race")

    if parsed.get("ascvd_10y") is not None:
        st.session_state["ascvd10_val"] = float(parsed["ascvd_10y"])
        applied.append("ASCVD10y")

    missing = [m for i, m in enumerate(missing) if m not in missing[:i]]
    return applied, missing

def level_pill_class(level: int) -> str:
    if level <= 0:
        return "pill pill-green"
    if level == 1 or level == 2:
        return "pill pill-yellow"
    return "pill pill-red"

def level2_explainer(sub: str):
    if sub == "2A":
        return (
            "Biology is drifting (lipids/glycemia/metabolic), but no proof of plaque yet.",
            ["Confirm & trend labs", "Lifestyle sprint 8–12 wks", "Shared statin decision", "Consider CAC if unknown"],
        )
    if sub == "2B":
        return (
            "Risk enhancers (Lp(a)/FHx/inflammation/CKD) suggest accelerated lifetime risk.",
            ["Consider statin default", "Address enhancer drivers", "Consider CAC if unknown", "ApoB-guided targets"],
        )
    if sub == "2C":
        return (
            "Higher probability of silent disease (often CAC 1–99 or multi-domain intermediate risk).",
            ["Treat like early disease", "Statin default", "Intensify to targets", "Recheck response 6–12 wks"],
        )
    return ("Level 2 prevention zone.", ["Refine with CAC", "ApoB-guided targets", "Shared decisions"])

# ============================================================
# Session defaults (ONLY via session_state, to avoid widget conflicts)
# ============================================================
st.session_state.setdefault("age_val", 0)
st.session_state.setdefault("sex_val", "F")
st.session_state.setdefault("race_val", "Other (use non-African American coefficients)")
st.session_state.setdefault("sbp_val", 0)
st.session_state.setdefault("tc_val", 0)
st.session_state.setdefault("ldl_val", 0)
st.session_state.setdefault("hdl_val", 0)
st.session_state.setdefault("apob_val", 0)
st.session_state.setdefault("lpa_val", 0)
st.session_state.setdefault("lpa_unit_val", "nmol/L")
st.session_state.setdefault("a1c_val", 0.0)
st.session_state.setdefault("bp_treated_val", "No")
st.session_state.setdefault("smoking_val", "No")
st.session_state.setdefault("diabetes_choice_val", "No")
st.session_state.setdefault("cac_known_val", "No")
st.session_state.setdefault("cac_val", 0)
st.session_state.setdefault("smartphrase_raw", "")

# ============================================================
# Top-level mode
# ============================================================
mode = st.radio("Output mode", ["Quick (default)", "Full (details)"], horizontal=True)

# ============================================================
# SmartPhrase ingest (paste -> parse -> apply + flag missing)
# ============================================================
st.subheader("SmartPhrase ingest (optional)")

with st.expander("Paste Epic output to auto-fill fields (LDL/ApoB/Lp(a)/CAC/A1c)", expanded=False):
    st.markdown(
        "<div class='small-help'>Paste rendered Epic output (SmartPhrase text, ASCVD block, lipid panel, etc). "
        "Click <strong>Parse & Apply</strong>. This will auto-fill as many fields as possible, and explicitly flag what was not found.</div>",
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

    parsed_preview = parse_smartphrase(smart_txt or "") if (smart_txt or "").strip() else {}

    c1, c2, c3, c4 = st.columns([1, 1, 1.4, 2.6])
    with c1:
        if st.button("Parse & Apply", type="primary"):
            applied, missing = apply_parsed_to_session(parsed_preview)
            st.success("Applied: " + (", ".join(applied) if applied else "None"))
            if missing:
                st.warning("Missing/unparsed: " + ", ".join(missing))
            st.rerun()

    with c2:
        if st.button("Clear pasted text"):
            st.session_state["smartphrase_raw"] = ""
            st.rerun()

    with c3:
        if st.button("Clear auto-filled fields"):
            for k in [
                "age_val", "sex_val", "race_val", "sbp_val", "tc_val", "hdl_val", "ldl_val",
                "apob_val", "lpa_val", "lpa_unit_val", "cac_val", "cac_known_val",
                "smoking_val", "diabetes_choice_val", "bp_treated_val", "ascvd10_val", "a1c_val",
            ]:
                st.session_state.pop(k, None)

            # Re-seed empties (and common radio defaults)
            st.session_state["age_val"] = 0
            st.session_state["sex_val"] = "F"
            st.session_state["race_val"] = "Other (use non-African American coefficients)"
            st.session_state["sbp_val"] = 0
            st.session_state["tc_val"] = 0
            st.session_state["ldl_val"] = 0
            st.session_state["hdl_val"] = 0
            st.session_state["apob_val"] = 0
            st.session_state["lpa_val"] = 0
            st.session_state["lpa_unit_val"] = "nmol/L"
            st.session_state["a1c_val"] = 0.0
            st.session_state["bp_treated_val"] = "No"
            st.session_state["smoking_val"] = "No"
            st.session_state["diabetes_choice_val"] = "No"
            st.session_state["cac_known_val"] = "No"
            st.session_state["cac_val"] = 0

            st.rerun()

    with c4:
        st.caption("Parsed preview")
        st.json(parsed_preview)

    st.markdown("### Parse coverage (explicit)")
    for key, label in TARGET_PARSE_FIELDS:
        ok = parsed_preview.get(key) is not None
        badge = "<span class='badge ok'>parsed</span>" if ok else "<span class='badge miss'>not found</span>"
        val = f": {parsed_preview.get(key)}" if ok else ""
        st.markdown(f"- **{label}** {badge}{val}", unsafe_allow_html=True)

    st.markdown(
        f"""
<div class="kv">
  <div><strong>Loaded defaults:</strong></div>
  <div>Age: {st.session_state.get("age_val", 0) or "—"}</div>
  <div>Gender: {st.session_state.get("sex_val", "—")}</div>
  <div>Race: {st.session_state.get("race_val", "—")}</div>
  <div>SBP: {st.session_state.get("sbp_val", 0) or "—"}</div>
  <div>TC: {st.session_state.get("tc_val", 0) or "—"}</div>
  <div>HDL: {st.session_state.get("hdl_val", 0) or "—"}</div>
  <div>LDL: {st.session_state.get("ldl_val", 0) or "—"}</div>
  <div>ApoB: {st.session_state.get("apob_val", 0) or "—"}</div>
  <div>Lp(a): {st.session_state.get("lpa_val", 0) or "—"} {st.session_state.get("lpa_unit_val", "")}</div>
  <div>A1c: {st.session_state.get("a1c_val", 0.0) or "—"}</div>
  <div>CAC: {st.session_state.get("cac_val", 0) or "—"} ({st.session_state.get("cac_known_val", "No")})</div>
</div>
""",
        unsafe_allow_html=True,
    )

# ============================================================
# Main form
# ============================================================
with st.form("levels_form"):
    st.subheader("Patient context")

    a1, a2, a3 = st.columns(3)
    with a1:
        age = st.number_input("Age (years)", 0, 120, step=1, key="age_val")
        gender = st.radio("Gender", ["F", "M"], horizontal=True, key="sex_val")

    with a2:
        race_options = ["Other (use non-African American coefficients)", "African American"]
        race = st.radio("Race (calculator)", race_options, horizontal=False, key="race_val")

    with a3:
        ascvd = st.radio("ASCVD (clinical)", ["No", "Yes"], horizontal=True)

    fhx_choice = st.selectbox("Premature family history (Father <55; Mother <65)", FHX_OPTIONS, index=0)

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Cardiometabolic profile")

    b1, b2, b3 = st.columns(3)
    with b1:
        sbp = st.number_input("Systolic BP (mmHg)", 0, 250, step=1, key="sbp_val")
        bp_treated = st.radio("On BP meds?", ["No", "Yes"], horizontal=True, key="bp_treated_val")

    with b2:
        smoking = st.radio("Smoking (current)", ["No", "Yes"], horizontal=True, key="smoking_val")
        diabetes_choice = st.radio("Diabetes (manual)", ["No", "Yes"], horizontal=True, key="diabetes_choice_val")

    with b3:
        a1c = st.number_input("A1c (%)", 0.0, 15.0, step=0.1, format="%.1f", key="a1c_val")
        if a1c >= 6.5:
            st.info("A1c ≥ 6.5% ⇒ Diabetes will be set to YES automatically.")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Labs")

    c1, c2, c3 = st.columns(3)
    with c1:
        tc = st.number_input("Total cholesterol (mg/dL)", 0, 500, step=1, key="tc_val")
        ldl = st.number_input("LDL-C (mg/dL)", 0, 400, step=1, key="ldl_val")
        hdl = st.number_input("HDL cholesterol (mg/dL)", 0, 300, step=1, key="hdl_val")  # widened max

    with c2:
        apob = st.number_input("ApoB (mg/dL)", 0, 300, step=1, key="apob_val")
        lpa = st.number_input("Lp(a) value", 0, 2000, step=1, key="lpa_val")
        lpa_unit = st.radio("Lp(a) unit", ["nmol/L", "mg/dL"], horizontal=True, key="lpa_unit_val")

    with c3:
        hscrp = st.number_input("hsCRP (mg/L) (optional)", 0.0, 50.0, 0.0, step=0.1, format="%.1f")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Imaging")

    d1, d2, d3 = st.columns([1, 1, 1])
    with d1:
        cac_known = st.radio("CAC available?", ["Yes", "No"], horizontal=True, key="cac_known_val")
    with d2:
        cac = st.number_input("CAC score (Agatston)", 0, 5000, step=1, key="cac_val") if cac_known == "Yes" else None
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
    raw_check = " ".join(
        [str(x) for x in [
            age, gender, race, fhx_choice, ascvd, sbp, bp_treated, smoking, diabetes_choice, a1c,
            tc, ldl, hdl, apob, lpa, lpa_unit, hscrp, cac
        ]]
    )
    if contains_phi(raw_check):
        st.error("Possible identifier/date detected. Please remove PHI and retry.")
        st.stop()

    # Required fields (since empty placeholders are 0)
    req_errors = []
    if age <= 0:
        req_errors.append("Age is required (must be > 0).")
    if sbp <= 0:
        req_errors.append("Systolic BP is required (must be > 0).")
    if tc <= 0:
        req_errors.append("Total cholesterol is required (must be > 0).")
    if hdl <= 0:
        req_errors.append("HDL is required (must be > 0).")

    if req_errors:
        st.error("Please complete required fields:\n- " + "\n- ".join(req_errors))
        st.stop()

    diabetes_effective = True if a1c >= 6.5 else (diabetes_choice == "Yes")

    data = {
        "age": int(age),
        "sex": gender,
        "race": "black" if race == "African American" else "other",
        "ascvd": (ascvd == "Yes"),

        "fhx": fhx_to_bool(fhx_choice),
        "fhx_detail": fhx_choice,

        "sbp": int(sbp),
        "bp_treated": (bp_treated == "Yes"),
        "smoking": (smoking == "Yes"),
        "diabetes": diabetes_effective,

        "a1c": float(a1c) if a1c and a1c > 0 else None,
        "tc": int(tc) if tc and tc > 0 else None,
        "ldl": int(ldl) if ldl and ldl > 0 else None,
        "hdl": int(hdl) if hdl and hdl > 0 else None,
        "apob": int(apob) if apob and apob > 0 else None,
        "lpa": int(lpa) if lpa and lpa > 0 else None,
        "lpa_unit": lpa_unit,
        "hscrp": float(hscrp) if hscrp and hscrp > 0 else None,

        "cac": int(cac) if (cac is not None and cac > 0) else None,

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

    # Clinical report FIRST
    st.subheader("Clinical report")
    st.markdown(clinical_html, unsafe_allow_html=True)

    # Downloads below main report
    d1, d2 = st.columns(2)
    with d1:
        st.download_button(
            "Download clinical text (.txt)",
            data=note_text.encode("utf-8"),
            file_name="levels_note.txt",
            mime="text/plain",
            use_container_width=True,
        )
    with d2:
        st.download_button(
            "Download JSON",
            data=json.dumps(out, indent=2).encode("utf-8"),
            file_name="levels_output.json",
            mime="application/json",
            use_container_width=True,
        )

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    # Key metrics (collapsed)
    with st.expander("Key metrics (Level • Risk Signal • 10-year ASCVD)", expanded=False):
        rs = out.get("riskSignal", {})
        risk10 = out.get("pooledCohortEquations10yAscvdRisk", {})
        lvl = out.get("levels", {})

        m1, m2, m3 = st.columns(3)
        lvl_display = f"{lvl.get('level','—')}"
        if int(lvl.get("level", 0) or 0) == 2 and lvl.get("sublevel"):
            lvl_display += f" ({lvl.get('sublevel')})"

        m1.metric("Level", lvl_display)
        m2.metric("Risk Signal Score", f"{rs.get('score','—')}/100")
        if risk10.get("risk_pct") is not None:
            m3.metric("10-year ASCVD risk", f"{risk10.get('risk_pct')}%")
        else:
            m3.metric("10-year ASCVD risk", "—")

    # Level interpretation (collapsed)
    with st.expander("Level interpretation (why this level / posture / Level 2 explainer)", expanded=False):
        lvl = out.get("levels", {})
        lvl_display = f"{lvl.get('level','—')}"
        if int(lvl.get("level", 0) or 0) == 2 and lvl.get("sublevel"):
            lvl_display += f" ({lvl.get('sublevel')})"

        st.markdown("<div class='level-card'>", unsafe_allow_html=True)
        st.markdown(
            f"<h3>Level interpretation <span class='{level_pill_class(int(lvl.get('level',0) or 0))}'>{lvl_display}</span></h3>",
            unsafe_allow_html=True,
        )

        if lvl.get("meaning"):
            st.markdown(f"<p class='small-help'><strong>What this means:</strong> {lvl['meaning']}</p>", unsafe_allow_html=True)

        why_list = (lvl.get("why") or [])[:3]
        if why_list:
            st.markdown("<div class='small-help'><strong>Why this level:</strong></div>", unsafe_allow_html=True)
            st.markdown("<ul>", unsafe_allow_html=True)
            for w in why_list:
                st.markdown(f"<li>{w}</li>", unsafe_allow_html=True)
            st.markdown("</ul>", unsafe_allow_html=True)

        if lvl.get("defaultPosture"):
            st.markdown(f"<p class='small-help'><strong>Default posture:</strong> {lvl['defaultPosture']}</p>", unsafe_allow_html=True)

        if int(lvl.get("level", 0) or 0) == 2 and lvl.get("sublevel"):
            expl, chips = level2_explainer(lvl.get("sublevel"))
            st.markdown(f"<p class='small-help'><strong>Level 2 {lvl.get('sublevel')} explainer:</strong> {expl}</p>", unsafe_allow_html=True)
            st.markdown("<div class='next-row'>", unsafe_allow_html=True)
            for c in chips:
                st.markdown(f"<span class='next-chip'>{c}</span>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # Aspirin summary (collapsed)
    with st.expander("Aspirin summary", expanded=False):
        asp = out.get("aspirin", {})
        asp_status = asp.get("status", "Not assessed")
        asp_why = short_why(asp.get("rationale", []), max_items=3)
        st.write(f"**{asp_status}**" + (f" — **Why:** {asp_why}" if asp_why else ""))

    # Quick output (raw text) (collapsed; only if Quick mode)
    if mode.startswith("Quick"):
        with st.expander("Quick output (raw text)", expanded=False):
            st.code(note_text, language="text")

    # Raw text copy/paste (collapsed)
    with st.expander("Raw text (copy/paste)", expanded=False):
        st.code(note_text, language="text")

    # JSON debug (collapsed; only if checkbox)
    if show_json:
        with st.expander("JSON (debug)", expanded=False):
            st.json(out)

    st.caption(
        f"Versions: {VERSION['levels']} | {VERSION['riskSignal']} | {VERSION['riskCalc']} | {VERSION['aspirin']}. No storage intended."
    )

