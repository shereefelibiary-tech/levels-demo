# app.py (fully consolidated, single-file, stable) — ONLY changes: calcium score box always visible + CAC payload uses session_state
import json
import re
import streamlit as st

from smartphrase_ingest.parser import parse_smartphrase
from levels_engine import Patient, evaluate, render_quick_text, VERSION, short_why

# ============================================================
# Clinician-native Level names (locked)
# ============================================================
LEVEL_NAMES = {
    1: "Minimal risk",
    2: "Emerging risk",
    3: "High biologic risk",
    4: "Subclinical atherosclerosis",
    5: "Atherosclerosis",
}

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
  background:#fff; border:1px solid rgba(31,41,55,0.12);
  border-radius:14px; padding:16px 18px; margin-bottom:10px;
}
.header-title { font-size:1.15rem; font-weight:800; margin:0 0 4px 0; }
.header-sub { color: rgba(31,41,55,0.60); font-size:0.9rem; margin:0; }

.hr { margin:10px 0 14px 0; border-top:1px solid rgba(31,41,55,0.12); }

.report {
  background:#fff;
  border:1px solid rgba(31,41,55,0.12);
  border-radius:14px;
  padding:18px 20px;
}
.report h2 { font-size:1.15rem; font-weight:800; margin:0 0 12px 0; }

.section { margin-top: 14px; }
.section-title {
  font-variant-caps:all-small-caps;
  letter-spacing:0.08em;
  font-weight:800;
  font-size:0.85rem;
  color:#4b5563;
  margin-bottom:6px;
  border-bottom:1px solid rgba(31,41,55,0.10);
  padding-bottom:2px;
}
.section p { margin: 6px 0; line-height: 1.45; }
.section ul { margin: 6px 0 6px 18px; }
.section li { margin: 4px 0; }

.muted { color:#6b7280; font-size:0.9rem; }
.small-help { color: rgba(31,41,55,0.70); font-size:0.88rem; }

.kv {
  display:flex; gap:10px; flex-wrap:wrap;
  border:1px solid rgba(31,41,55,0.10);
  background:#fbfbfb;
  border-radius:12px;
  padding:10px 12px;
  margin-top:10px;
}
.kv div { font-size:0.9rem; }
.kv strong { font-weight:800; }

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
  border:1px solid rgba(31,41,55,0.10);
  border-radius:12px;
  padding:12px;
  background: rgba(31,41,55,0.03);
  margin-top:10px;
}
.level-card h3 { font-size:0.95rem; margin:0 0 6px 0; font-weight:800; }

.next-row { display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; }
.next-chip {
  display:inline-block;
  padding:6px 10px;
  border-radius:10px;
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
  <div class="header-title">LEVELS™ {VERSION.get("levels","")} — De-identified Demo</div>
  <p class="header-sub">Fast entry • SmartPhrase paste → auto-fill • Management Levels 1–5 • high-yield clinical report</p>
</div>
""",
    unsafe_allow_html=True,
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

# ------------------------------------------------------------
# UI-side parsing helpers (hsCRP + inflammatory flags + diabetes negation)
# ------------------------------------------------------------
def parse_hscrp_from_text(txt: str):
    if not txt:
        return None
    m = re.search(r"\b(?:hs\s*crp|hscrp)\s*[:=]?\s*(\d{1,3}(?:\.\d+)?)\b", txt, flags=re.I)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None

def parse_inflammatory_flags_from_text(txt: str) -> dict:
    if not txt:
        return {}
    t = txt.lower()
    flags = {}

    def has_yes(term: str) -> bool:
        return bool(re.search(rf"\b{re.escape(term)}\b\s*[:=]?\s*(yes|true|present)\b", t))

    for key, term in [
        ("ra", "ra"),
        ("ra", "rheumatoid arthritis"),
        ("psoriasis", "psoriasis"),
        ("sle", "sle"),
        ("ibd", "ibd"),
        ("hiv", "hiv"),
        ("osa", "osa"),
        ("nafld", "nafld"),
        ("nafld", "masld"),
    ]:
        if has_yes(term):
            flags[key] = True

    return flags

def diabetes_negation_guard(txt: str):
    if not txt:
        return None
    t = txt.lower()
    if re.search(r"\b(no diabetes|not diabetic|denies diabetes)\b", t):
        return False
    if re.search(r"\b(diabetes|t2dm|type 2 diabetes|type ii diabetes)\b", t):
        if not re.search(r"\b(no diabetes|not diabetic|denies diabetes)\b", t):
            return True
    return None

# ------------------------------------------------------------
# Streamlit-native "Management Level ladder" (always renders)
# ------------------------------------------------------------
def render_management_ladder(level: int, sublevel: str | None = None):
    try:
        lvl = int(level or 0)
    except Exception:
        lvl = 1
    lvl = max(1, min(5, lvl))

    st.markdown(
        f"### Management Level: **{lvl} — {LEVEL_NAMES.get(lvl, '—')}**"
        + (f" (**{sublevel}**)" if sublevel else "")
    )

    cols = st.columns(5)
    for i in range(1, 6):
        marker = "✅" if i == lvl else " "
        with cols[i - 1]:
            st.markdown(f"**{marker} {i}**")
            st.caption(LEVEL_NAMES[i])

# ------------------------------------------------------------
# Sublevel explainer
# ------------------------------------------------------------
def sublevel_explainer(sub: str):
    if sub == "3A":
        return (
            "High biology without strong enhancers; plaque not proven.",
            ["Trend labs", "Lifestyle sprint", "Shared decision on statin", "Consider calcium score if unknown"],
        )
    if sub == "3B":
        return (
            "High biology with enhancers (Lp(a)/FHx/inflammation) → higher lifetime acceleration.",
            ["Statin default often reasonable", "Address enhancers", "Consider calcium score if unknown", "ApoB-guided targets"],
        )
    if sub == "3C":
        return (
            "Higher near-term risk phenotype despite no proven plaque.",
            ["Treat risk seriously", "Statin default often reasonable", "Confirm BP/lipids", "Consider calcium score if unknown"],
        )
    return ("", [])

# ------------------------------------------------------------
# High-yield Clinical Report (built from engine JSON)
# ------------------------------------------------------------
def render_high_yield_report(out: dict) -> str:
    lvl = out.get("levels", {}) or {}
    rs = out.get("riskSignal", {}) or {}
    risk10 = out.get("pooledCohortEquations10yAscvdRisk", {}) or {}
    targets = out.get("targets", {}) or {}
    ev = (lvl.get("evidence") or {}) if isinstance(lvl.get("evidence"), dict) else {}
    drivers = out.get("drivers", []) or []
    next_actions = out.get("nextActions", []) or []
    asp = out.get("aspirin", {}) or {}

    mgmt_level = (lvl.get("managementLevel") or lvl.get("postureLevel") or lvl.get("level") or 1)
    try:
        mgmt_level = int(mgmt_level)
    except Exception:
        mgmt_level = 1
    mgmt_level = max(1, min(5, mgmt_level))
    sub = lvl.get("sublevel")
    name = LEVEL_NAMES.get(mgmt_level, "—")
    title = f"LEVELS™ — Management Level {mgmt_level}: {name}" + (f" ({sub})" if sub else "")

    risk_pct = risk10.get("risk_pct")
    risk_line = f"{risk_pct}%" if risk_pct is not None else "—"
    risk_cat = risk10.get("category") or ""

    evidence_line = ev.get("cac_status") or out.get("diseaseBurden") or "—"
    burden_line = ev.get("burden_band") or "—"

    html = []
    html.append('<div class="report">')
    html.append(f"<h2>{title}</h2>")

    html.append('<div class="section">')
    html.append('<div class="section-title">Summary</div>')
    meaning = lvl.get("meaning")
    if meaning:
        html.append(f"<p>{meaning}</p>")
    else:
        html.append("<p class='muted'>No summary available.</p>")
    html.append("</div>")

    html.append('<div class="section">')
    html.append('<div class="section-title">Key metrics</div>')
    html.append(f"<p><strong>Risk Signal Score:</strong> {rs.get('score','—')}/100 ({rs.get('band','—')})</p>")
    if risk_pct is not None:
        html.append(f"<p><strong>10-year ASCVD risk (PCE):</strong> {risk_line} {f'({risk_cat})' if risk_cat else ''}</p>")
    else:
        html.append("<p><strong>10-year ASCVD risk (PCE):</strong> —</p>")
    html.append(f"<p><strong>Evidence:</strong> {evidence_line}</p>")
    html.append(f"<p><strong>Burden:</strong> {burden_line}</p>")
    html.append("</div>")

    html.append('<div class="section">')
    html.append('<div class="section-title">Primary drivers</div>')
    if drivers:
        html.append("<ul>")
        for d in drivers[:3]:
            html.append(f"<li>{d}</li>")
        html.append("</ul>")
    else:
        html.append("<p class='muted'>No drivers listed.</p>")
    html.append("</div>")

    html.append('<div class="section">')
    html.append('<div class="section-title">Targets & plan</div>')

    tar_lines = []
    if targets.get("apob") is not None:
        tar_lines.append(f"ApoB <{targets['apob']} mg/dL")
    if targets.get("ldl") is not None:
        tar_lines.append(f"LDL-C <{targets['ldl']} mg/dL")
    if tar_lines:
        html.append("<p><strong>Targets:</strong> " + " • ".join(tar_lines) + "</p>")

    posture = lvl.get("defaultPosture")
    if posture:
        posture_clean = re.sub(r"^\s*(Default posture:|Consider:|Defer—need data:)\s*", "", str(posture)).strip()
        posture_clean = posture_clean.replace("Risk drift", "Emerging risk").replace("drift", "Emerging risk")
        html.append(f"<p><strong>Plan:</strong> {posture_clean}</p>")

    if next_actions:
        html.append("<p><strong>Next steps:</strong></p>")
        html.append("<ul>")
        for a in next_actions[:3]:
            html.append(f"<li>{a}</li>")
        html.append("</ul>")

    asp_status = asp.get("status")
    if asp_status:
        html.append(f"<p><strong>Aspirin:</strong> {asp_status}</p>")

    html.append("</div>")
    html.append("</div>")
    return "\n".join(html)

# ------------------------------------------------------------
# Parse coverage UI
# ------------------------------------------------------------
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
    ("cac", "Calcium score"),
    ("a1c", "A1c"),
    ("ascvd_10y", "ASCVD 10-year risk (if present)"),
]

# ------------------------------------------------------------
# Apply parsed → session
# ------------------------------------------------------------
def apply_parsed_to_session(parsed: dict, raw_txt: str):
    applied, missing = [], []

    def set_if_present(src_key, state_key, transform=lambda x: x, label=None):
        nonlocal applied, missing
        label = label or src_key
        if parsed.get(src_key) is not None:
            st.session_state[state_key] = transform(parsed[src_key])
            applied.append(label)
        else:
            missing.append(label)

    set_if_present("age", "age_val", int, "Age")
    set_if_present("sex", "sex_val", lambda v: v, "Gender")
    set_if_present("sbp", "sbp_val", int, "Systolic BP")

    set_if_present("tc", "tc_val", int, "Total Cholesterol")
    set_if_present("hdl", "hdl_val", int, "HDL")
    set_if_present("ldl", "ldl_val", int, "LDL")

    set_if_present("apob", "apob_val", int, "ApoB")
    set_if_present("lpa", "lpa_val", lambda v: int(float(v)), "Lp(a)")

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
        st.session_state["cac_val"] = int(float(parsed["cac"]))
        applied.append("Calcium score")
    else:
        missing.append("Calcium score")

    if parsed.get("smoker") is not None:
        st.session_state["smoking_val"] = "Yes" if parsed["smoker"] else "No"
        applied.append("Smoking")

    dm_guard = diabetes_negation_guard(raw_txt)
    if dm_guard is False:
        st.session_state["diabetes_choice_val"] = "No"
        applied.append("Diabetes(manual) (negation)")
    elif parsed.get("diabetes") is not None:
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

    # Optional extras from raw text
    h = parse_hscrp_from_text(raw_txt)
    if h is not None:
        st.session_state["hscrp_val"] = float(h)
        applied.append("hsCRP")

    infl = parse_inflammatory_flags_from_text(raw_txt)
    for k, v in infl.items():
        st.session_state[f"infl_{k}_val"] = bool(v)
        applied.append(k.upper())

    missing = [m for i, m in enumerate(missing) if m not in missing[:i]]
    return applied, missing

# ============================================================
# Session defaults
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
st.session_state.setdefault("hscrp_val", 0.0)
st.session_state.setdefault("bp_treated_val", "No")
st.session_state.setdefault("smoking_val", "No")
st.session_state.setdefault("diabetes_choice_val", "No")
st.session_state.setdefault("cac_known_val", "No")
st.session_state.setdefault("cac_val", 0)
st.session_state.setdefault("smartphrase_raw", "")

for k in ["ra","psoriasis","sle","ibd","hiv","osa","nafld"]:
    st.session_state.setdefault(f"infl_{k}_val", False)

# ============================================================
# Callbacks
# ============================================================
def cb_clear_pasted_text():
    st.session_state["smartphrase_raw"] = ""

def cb_clear_autofilled_fields():
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
    st.session_state["hscrp_val"] = 0.0
    st.session_state["bp_treated_val"] = "No"
    st.session_state["smoking_val"] = "No"
    st.session_state["diabetes_choice_val"] = "No"
    st.session_state["cac_known_val"] = "No"
    st.session_state["cac_val"] = 0
    for k in ["ra","psoriasis","sle","ibd","hiv","osa","nafld"]:
        st.session_state[f"infl_{k}_val"] = False

# ============================================================
# Top-level mode
# ============================================================
mode = st.radio("Output mode", ["Quick (default)", "Full (details)"], horizontal=True)

# ============================================================
# SmartPhrase ingest (parsed preview + coverage + loaded defaults)
# ============================================================
st.subheader("SmartPhrase ingest (optional)")

with st.expander("Paste Epic output to auto-fill fields", expanded=False):
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
            applied, missing = apply_parsed_to_session(parsed_preview, smart_txt or "")
            st.success("Applied: " + (", ".join(applied) if applied else "None"))
            if missing:
                st.warning("Missing/unparsed: " + ", ".join(missing))
            st.rerun()
    with c2:
        st.button("Clear pasted text", on_click=cb_clear_pasted_text)
    with c3:
        st.button("Clear auto-filled fields", on_click=cb_clear_autofilled_fields)
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
  <div>hsCRP: {st.session_state.get("hscrp_val", 0.0) or "—"}</div>
  <div>Calcium score: {st.session_state.get("cac_val", 0) if st.session_state.get("cac_known_val")=="Yes" else "—"} ({st.session_state.get("cac_known_val", "No")})</div>
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

    fhx_choice = st.selectbox("Premature family history", FHX_OPTIONS, index=0)

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
        hdl = st.number_input("HDL cholesterol (mg/dL)", 0, 300, step=1, key="hdl_val")
    with c2:
        apob = st.number_input("ApoB (mg/dL)", 0, 300, step=1, key="apob_val")
        lpa = st.number_input("Lp(a) value", 0, 2000, step=1, key="lpa_val")
        lpa_unit = st.radio("Lp(a) unit", ["nmol/L", "mg/dL"], horizontal=True, key="lpa_unit_val")
    with c3:
        hscrp = st.number_input("hsCRP (mg/L) (optional)", 0.0, 50.0, step=0.1, format="%.1f", key="hscrp_val")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Imaging")

    # ✅ CHANGE 1: Calcium score box ALWAYS visible (disabled if No)
    d1, d2, d3 = st.columns([1, 1, 1])
    with d1:
        cac_known = st.radio("Calcium score available?", ["Yes", "No"], horizontal=True, key="cac_known_val")
    with d2:
        st.number_input(
            "Calcium score (Agatston)",
            min_value=0,
            max_value=5000,
            step=1,
            key="cac_val",
            disabled=(cac_known != "Yes"),
            help="Enter 0 if known zero. If not available, leave disabled.",
        )
    with d3:
        st.caption("")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Inflammatory states (optional)")

    e1, e2, e3 = st.columns(3)
    with e1:
        ra = st.checkbox("Rheumatoid arthritis", key="infl_ra_val")
        psoriasis = st.checkbox("Psoriasis", key="infl_psoriasis_val")
    with e2:
        sle = st.checkbox("SLE", key="infl_sle_val")
        ibd = st.checkbox("IBD", key="infl_ibd_val")
    with e3:
        hiv = st.checkbox("HIV", key="infl_hiv_val")
        osa = st.checkbox("OSA", key="infl_osa_val")
        nafld = st.checkbox("NAFLD/MASLD", key="infl_nafld_val")

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
    # Required fields (keep as you wanted)
    req_errors = []
    if age <= 0: req_errors.append("Age is required (must be > 0).")
    if sbp <= 0: req_errors.append("Systolic BP is required (must be > 0).")
    if tc <= 0: req_errors.append("Total cholesterol is required (must be > 0).")
    if hdl <= 0: req_errors.append("HDL is required (must be > 0).")

    if req_errors:
        st.error("Please complete required fields:\n- " + "\n- ".join(req_errors))
        st.stop()

    diabetes_effective = True if a1c >= 6.5 else (diabetes_choice == "Yes")

    # ✅ CHANGE 2: CAC payload uses session_state, preserves CAC=0 when available
    cac_to_send = int(st.session_state["cac_val"]) if cac_known == "Yes" else None

    data = {
        "age": int(age),
        "sex": gender,
        "race": "black" if race == "African American" else "other",
        "ascvd": (ascvd == "Yes"),
        "fhx": fhx_to_bool(fhx_choice),
        "sbp": int(sbp),
        "bp_treated": (bp_treated == "Yes"),
        "smoking": (smoking == "Yes"),
        "diabetes": diabetes_effective,
        "a1c": float(a1c) if a1c and a1c > 0 else None,
        "tc": int(tc) if tc and tc > 0 else None,
        "ldl": int(ldl) if ldl and ldl > 0 else None,
        "hdl": int(hdl) if hdl and hdl > 0 else None,
        "apob": int(apob) if apob and apob > 0 else None,
        "lpa": float(lpa) if lpa and lpa > 0 else None,
        "lpa_unit": lpa_unit,
        "hscrp": float(hscrp) if hscrp and hscrp > 0 else None,
        "cac": cac_to_send,

        "ra": bool(ra), "psoriasis": bool(psoriasis), "sle": bool(sle),
        "ibd": bool(ibd), "hiv": bool(hiv), "osa": bool(osa), "nafld": bool(nafld),

        "bleed_gi": bool(bleed_gi), "bleed_ich": bool(bleed_ich),
        "bleed_anticoag": bool(bleed_anticoag), "bleed_nsaid": bool(bleed_nsaid),
        "bleed_disorder": bool(bleed_disorder), "bleed_ckd": bool(bleed_ckd),
    }
    data = {k: v for k, v in data.items() if v is not None}

    patient = Patient(data)
    out = evaluate(patient)

    # Quick text (kept, but cleaned)
    note_text = render_quick_text(patient, out)
    note_text = note_text.replace("Posture Level", "Management Level")
    note_text = note_text.replace("Risk drift", "Emerging risk").replace("drift", "Emerging risk")

    # --- Key metrics FIRST ---
    st.subheader("Key metrics")
    lvl = out.get("levels", {}) or {}
    rs = out.get("riskSignal", {}) or {}
    risk10 = out.get("pooledCohortEquations10yAscvdRisk", {}) or {}

    mgmt_level = (lvl.get("managementLevel") or lvl.get("postureLevel") or lvl.get("level") or 1)
    try:
        mgmt_level = int(mgmt_level)
    except Exception:
        mgmt_level = 1
    mgmt_level = max(1, min(5, mgmt_level))
    sub = lvl.get("sublevel")

    render_management_ladder(mgmt_level, sub)
    st.caption("Legend: Management Level reflects prevention intensity. Evidence reflects plaque certainty (Calcium score / ASCVD).")

    m1, m2, m3 = st.columns(3)
    m1.metric("Management Level", f"{mgmt_level}" + (f" ({sub})" if sub else ""))
    m2.metric("Risk Signal Score", f"{rs.get('score','—')}/100")
    m3.metric("10-year ASCVD risk", f"{risk10.get('risk_pct')}%" if risk10.get("risk_pct") is not None else "—")

    ev = (lvl.get("evidence") or {}) if isinstance(lvl.get("evidence"), dict) else {}
    st.markdown(f"**Evidence:** {ev.get('cac_status','—')} / **Burden:** {ev.get('burden_band','—')}")

    # --- Clinical report: high yield ---
    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Clinical report (high-yield)")
    st.markdown(render_high_yield_report(out), unsafe_allow_html=True)

    # Downloads
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

    with st.expander("Anchors (near-term vs lifetime)", expanded=False):
        anchors = out.get("anchors", {}) or {}
        near = (anchors.get("nearTerm") or {}).get("summary", "—")
        life = (anchors.get("lifetime") or {}).get("summary", "—")
        st.markdown(f"**Near-term anchor:** {near}")
        st.markdown(f"**Lifetime anchor:** {life}")

    with st.expander("Interpretation (why / plan / explainer)", expanded=False):
        st.markdown("<div class='level-card'>", unsafe_allow_html=True)
        st.markdown(
            f"<h3>Interpretation — Management Level {mgmt_level}: {LEVEL_NAMES.get(mgmt_level,'—')}</h3>",
            unsafe_allow_html=True,
        )

        meaning = lvl.get("meaning")
        if meaning:
            st.markdown(f"<p class='small-help'><strong>What this means:</strong> {meaning}</p>", unsafe_allow_html=True)

        why_list = (lvl.get("why") or [])[:3]
        if why_list:
            st.markdown("<div class='small-help'><strong>Why this level:</strong></div>", unsafe_allow_html=True)
            st.markdown("<ul>", unsafe_allow_html=True)
            for w in why_list:
                st.markdown(f"<li>{w}</li>", unsafe_allow_html=True)
            st.markdown("</ul>", unsafe_allow_html=True)

        if lvl.get("defaultPosture"):
            posture_clean = re.sub(r"^\s*(Default posture:|Consider:|Defer—need data:)\s*", "", str(lvl["defaultPosture"])).strip()
            posture_clean = posture_clean.replace("Risk drift", "Emerging risk").replace("drift", "Emerging risk")
            st.markdown(f"<p class='small-help'><strong>Plan:</strong> {posture_clean}</p>", unsafe_allow_html=True)

        if sub:
            expl, chips = sublevel_explainer(sub)
            if expl:
                st.markdown(f"<p class='small-help'><strong>Explainer {sub}:</strong> {expl}</p>", unsafe_allow_html=True)
            if chips:
                st.markdown("<div class='next-row'>", unsafe_allow_html=True)
                for c in chips:
                    st.markdown(f"<span class='next-chip'>{c}</span>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Aspirin summary", expanded=False):
        asp = out.get("aspirin", {}) or {}
        asp_status = asp.get("status", "Not assessed")
        asp_why = short_why(asp.get("rationale", []), max_items=3)
        st.write(f"**{asp_status}**" + (f" — **Why:** {asp_why}" if asp_why else ""))

    if mode.startswith("Quick"):
        with st.expander("Quick output (raw text)", expanded=False):
            st.code(note_text, language="text")

    with st.expander("Trace (audit trail)", expanded=False):
        st.json(out.get("trace", []))

    if show_json:
        with st.expander("JSON (debug)", expanded=False):
            st.json(out)

    st.caption(
        f"Versions: {VERSION.get('levels','')} | {VERSION.get('riskSignal','')} | {VERSION.get('riskCalc','')} | {VERSION.get('aspirin','')}. No storage intended."
    )
