# app.py (Risk Continuum — cleaned + tabbed clinician-friendly layout)
# Goals:
# - Tight "Overview" (10-second read): Level/Evidence + 3 metrics (RSS/PCE/PREVENT) + Plan + Next steps + Targets
# - "Report" is the single copy/paste clinical narrative source of truth
# - "Details" holds anchors/why/sublevel/aspirin
# - "Debug" holds raw text/trace/json
# - Keep PREVENT visible in Overview (even if not active yet)
# - Keep LDL-first targets visible in Overview
# - Keep SmartPhrase ingest + Parse&Apply
# - Optional DEMO defaults toggle so you can click Run immediately

import json
import re
import streamlit as st
import levels_engine as le

from smartphrase_ingest.parser import parse_smartphrase
from levels_engine import Patient, evaluate, render_quick_text, VERSION, short_why

# ============================================================
# System naming
# ============================================================
SYSTEM_NAME = "Risk Continuum™"

LEVEL_NAMES = {
    1: "Minimal risk signal",
    2: "Emerging risk signals",
    3: "Actionable biologic risk",
    4: "Subclinical atherosclerosis present",
    5: "Very high risk / ASCVD intensity",
}

FALLBACK_LEVEL_LEGEND = [
    "Level 1: minimal signal → reinforce basics, periodic reassess",
    "Level 2A: mild/isolated signal → education, complete data, lifestyle sprint",
    "Level 2B: converging signals → lifestyle sprint + shorter reassess",
    "Level 3A: actionable biologic risk → shared decision; consider therapy based on trajectory",
    "Level 3B: biologic risk + enhancers → therapy often favored; refine with CAC if unknown",
    "Level 4: subclinical plaque present → treat like early disease; target-driven therapy",
    "Level 5: very high risk / ASCVD → secondary prevention intensity; maximize tolerated therapy",
]

# ============================================================
# Page + styling
# ============================================================
st.set_page_config(page_title="Risk Continuum", layout="wide")

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
.muted { color:#6b7280; font-size:0.9rem; }
.small-help { color: rgba(31,41,55,0.70); font-size:0.88rem; }

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

.level-strip {
  border:1px solid rgba(31,41,55,0.10);
  background: rgba(31,41,55,0.03);
  border-radius:12px;
  padding:12px 14px;
  margin: 8px 0 10px 0;
}
.level-strip .title { font-weight:900; font-size:1.05rem; margin:0 0 2px 0; }
.level-strip .sub { color: rgba(31,41,55,0.70); font-size:0.90rem; margin:0; }

.next-box {
  border:1px solid rgba(31,41,55,0.10);
  border-radius:12px;
  padding:12px;
  background:#fff;
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""
<div class="header-card">
  <div class="header-title">{SYSTEM_NAME} {VERSION.get("levels","")} — De-identified Demo</div>
  <p class="header-sub">Fast entry • SmartPhrase paste → auto-fill • Levels 1–5 (+ sublevels) • clinician-friendly output</p>
</div>
""",
    unsafe_allow_html=True,
)

st.info("De-identified use only. Do not enter patient identifiers.")

# ============================================================
# Debug expander (small)
# ============================================================
with st.expander("DEBUG: engine version", expanded=False):
    st.write("Engine sentinel:", getattr(le, "PCE_DEBUG_SENTINEL", "MISSING"))
    st.write("Engine VERSION:", getattr(le, "VERSION", {}))

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

def scrub_terms(s: str) -> str:
    if not s:
        return s
    s = re.sub(r"\brisk\s+drift\b", "Emerging risk", s, flags=re.IGNORECASE)
    s = re.sub(r"\bdrift\b", "Emerging risk", s, flags=re.IGNORECASE)
    s = re.sub(r"\bposture\b", "level", s, flags=re.IGNORECASE)
    return s

def scrub_list(xs):
    if not xs:
        return xs
    return [scrub_terms(str(x)) for x in xs]

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

    if re.search(r"\bdiabetic\s*:\s*(no|false)\b", t):
        return False
    if re.search(r"\bdiabetic\s*:\s*(yes|true)\b", t):
        return True

    if re.search(r"\b(no diabetes|not diabetic|denies diabetes)\b", t):
        return False
    if re.search(r"\b(diabetes|t2dm|type 2 diabetes|type ii diabetes)\b", t):
        if not re.search(r"\b(no diabetes|not diabetic|denies diabetes)\b", t):
            if re.search(r"\bdiabetes\s*mellitus\s*:\s*\{yes/no:\d+\}\b", t):
                return None
            return True
    return None

DATE_LIKE_PATTERNS = [
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},\s+\d{4}\b",
]

def is_date_like(v) -> bool:
    if v is None:
        return False
    s = str(v).strip().lower()
    return any(re.search(p, s, flags=re.I) for p in DATE_LIKE_PATTERNS)

def coerce_int(v):
    if v is None:
        return None
    if is_date_like(v):
        return None
    s = str(v).strip()
    m = re.search(r"[-+]?\d+", s)
    if not m:
        return None
    try:
        return int(m.group(0))
    except Exception:
        return None

def coerce_float(v):
    if v is None:
        return None
    if is_date_like(v):
        return None
    s = str(v).strip()
    m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None

def pick_dual_targets_ldl_first(out: dict, patient_data: dict) -> dict:
    targets = out.get("targets", {}) or {}
    ldl_goal = targets.get("ldl")
    apob_goal = targets.get("apob")
    apob_measured = patient_data.get("apob") is not None

    primary = None
    secondary = None

    if ldl_goal is not None:
        primary = ("LDL-C", f"<{int(ldl_goal)} mg/dL")
    elif apob_goal is not None:
        primary = ("ApoB", f"<{int(apob_goal)} mg/dL")

    if apob_goal is not None:
        secondary = ("ApoB", f"<{int(apob_goal)} mg/dL")

    return {"primary": primary, "secondary": secondary, "apob_measured": apob_measured}

def guideline_anchor_note(level: int, clinical_ascvd: bool) -> str:
    if clinical_ascvd:
        return "Guideline anchor: ACC/AHA secondary prevention (LDL-C <70). ESC/EAS very-high-risk often targets <55."
    if level >= 4:
        return "Guideline anchor: ACC/AHA & ESC/EAS targets for subclinical atherosclerosis (LDL-C <70)."
    if level == 3:
        return "Guideline anchor: ACC/AHA primary prevention—risk-enhanced approach; ApoB thresholds used as risk-enhancing markers."
    if level == 2:
        return "Guideline anchor: ACC/AHA primary prevention—individualized targets based on overall risk and trajectory."
    return "Guideline anchor: ACC/AHA primary prevention—lifestyle-first and periodic reassessment."

def render_high_yield_report(out: dict) -> str:
    lvl = out.get("levels", {}) or {}
    rs = out.get("riskSignal", {}) or {}
    risk10 = out.get("pooledCohortEquations10yAscvdRisk", {}) or {}
    targets = out.get("targets", {}) or {}
    ev = (lvl.get("evidence") or {}) if isinstance(lvl.get("evidence"), dict) else {}
    drivers = scrub_list(out.get("drivers", []) or [])
    next_actions = scrub_list(out.get("nextActions", []) or [])
    asp = out.get("aspirin", {}) or {}

    prevent10 = out.get("prevent10", {}) or {}
    p_total = prevent10.get("total_cvd_10y_pct")
    p_ascvd = prevent10.get("ascvd_10y_pct")

    level = (lvl.get("postureLevel") or lvl.get("level") or 1)
    try:
        level = int(level)
    except Exception:
        level = 1
    level = max(1, min(5, level))

    sub = lvl.get("sublevel")
    name = LEVEL_NAMES.get(level, "—")
    title = f"{SYSTEM_NAME} — Level {level}: {name}" + (f" ({sub})" if sub else "")

    risk_pct = risk10.get("risk_pct")
    risk_line = f"{risk_pct}%" if risk_pct is not None else "—"
    risk_cat = risk10.get("category") or ""

    evidence_line = scrub_terms(ev.get("cac_status") or out.get("diseaseBurden") or "—")
    burden_line = scrub_terms(ev.get("burden_band") or "—")

    rec_tag = scrub_terms(lvl.get("recommendationStrength") or "—")
    explainer = scrub_terms(lvl.get("explainer") or "")
    meaning = scrub_terms(lvl.get("meaning") or "")

    html = []
    html.append('<div class="report">')
    html.append(f"<h2>{title}</h2>")

    html.append('<div class="section">')
    html.append('<div class="section-title">Summary</div>')
    html.append(f"<p>{meaning}</p>" if meaning else "<p class='muted'>No summary available.</p>")
    if explainer:
        html.append(f"<p class='small-help'><strong>Level explainer:</strong> {explainer}</p>")
    if rec_tag and rec_tag != "—":
        html.append(f"<p class='small-help'><strong>Recommendation tag:</strong> {rec_tag}</p>")
    html.append("</div>")

    html.append('<div class="section">')
    html.append('<div class="section-title">Key metrics</div>')
    html.append(f"<p><strong>Risk Signal Score:</strong> {rs.get('score','—')}/100 ({rs.get('band','—')})</p>")
    if risk_pct is not None:
        html.append(f"<p><strong>10-year ASCVD risk (PCE):</strong> {risk_line} {f'({risk_cat})' if risk_cat else ''}</p>")
    else:
        html.append("<p><strong>10-year ASCVD risk (PCE):</strong> —</p>")

    if p_total is not None or p_ascvd is not None:
        html.append(f"<p><strong>PREVENT (10-year):</strong> total CVD {p_total}% / ASCVD {p_ascvd}%</p>")
    else:
        note = prevent10.get("notes")
        if note:
            html.append(f"<p class='muted'><strong>PREVENT (10-year):</strong> {scrub_terms(note)}</p>")

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
    if targets.get("ldl") is not None:
        tar_lines.append(f"LDL-C <{targets['ldl']} mg/dL")
    if targets.get("apob") is not None:
        tar_lines.append(f"ApoB <{targets['apob']} mg/dL")
    if tar_lines:
        html.append("<p><strong>Targets:</strong> " + " • ".join(tar_lines) + "</p>")

    plan = lvl.get("defaultPosture")
    if plan:
        plan_clean = re.sub(r"^\s*(Recommended:|Consider:|Pending more data:)\s*", "", str(plan)).strip()
        plan_clean = scrub_terms(plan_clean)
        html.append(f"<p><strong>Plan:</strong> {plan_clean}</p>")

    if next_actions:
        html.append("<p><strong>Next steps:</strong></p>")
        html.append("<p>" + "<br>".join([f"• {a}" for a in next_actions[:3]]) + "</p>")

    asp_status = scrub_terms(asp.get("status") or "")
    if asp_status:
        html.append(f"<p><strong>Aspirin:</strong> {asp_status}</p>")

    html.append("</div>")
    html.append("</div>")
    return "\n".join(html)

# ============================================================
# Parse & Apply
# ============================================================
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
    ("bmi", "BMI (PREVENT)"),
    ("egfr", "eGFR (PREVENT)"),
]

def apply_parsed_to_session(parsed: dict, raw_txt: str):
    applied, missing = [], []

    def apply_num(src_key, state_key, coerce_fn, label):
        nonlocal applied, missing
        v = parsed.get(src_key)
        v2 = coerce_fn(v)
        if v2 is None:
            missing.append(label)
            return
        st.session_state[state_key] = v2
        applied.append(label)

    apply_num("age", "age_val", coerce_int, "Age")
    apply_num("sbp", "sbp_val", coerce_int, "Systolic BP")
    apply_num("tc", "tc_val", coerce_int, "Total Cholesterol")
    apply_num("hdl", "hdl_val", coerce_int, "HDL")
    apply_num("ldl", "ldl_val", coerce_int, "LDL")
    apply_num("apob", "apob_val", coerce_int, "ApoB")

    lpa_v = coerce_float(parsed.get("lpa"))
    if lpa_v is not None:
        st.session_state["lpa_val"] = int(lpa_v)
        applied.append("Lp(a)")
    else:
        missing.append("Lp(a)")

    sex = parsed.get("sex")
    if sex in ("F", "M"):
        st.session_state["sex_val"] = sex
        applied.append("Gender")
    else:
        missing.append("Gender")

    if parsed.get("lpa_unit") in ("nmol/L", "mg/dL"):
        st.session_state["lpa_unit_val"] = parsed["lpa_unit"]
        applied.append("Lp(a) unit")
    else:
        missing.append("Lp(a) unit")

    a1c_v = coerce_float(parsed.get("a1c"))
    if a1c_v is not None:
        st.session_state["a1c_val"] = float(a1c_v)
        applied.append("A1c")
    else:
        missing.append("A1c")

    cac_v = coerce_int(parsed.get("cac"))
    if cac_v is not None:
        st.session_state["cac_known_val"] = "Yes"
        st.session_state["cac_val"] = int(cac_v)
        applied.append("Calcium score")
    else:
        missing.append("Calcium score")

    if parsed.get("smoker") is not None:
        st.session_state["smoking_val"] = "Yes" if bool(parsed["smoker"]) else "No"
        applied.append("Smoking")

    dm_guard = diabetes_negation_guard(raw_txt)
    if dm_guard is False:
        st.session_state["diabetes_choice_val"] = "No"
        applied.append("Diabetes (negation)")
    elif dm_guard is True:
        st.session_state["diabetes_choice_val"] = "Yes"
        applied.append("Diabetes (affirmed)")
    elif parsed.get("diabetes") is not None:
        st.session_state["diabetes_choice_val"] = "Yes" if bool(parsed["diabetes"]) else "No"
        applied.append("Diabetes")

    if parsed.get("bpTreated") is not None:
        st.session_state["bp_treated_val"] = "Yes" if bool(parsed["bpTreated"]) else "No"
        applied.append("BP meds")
    else:
        missing.append("BP meds")

    if parsed.get("africanAmerican") is not None:
        st.session_state["race_val"] = (
            "African American" if bool(parsed["africanAmerican"]) else "Other (use non-African American coefficients)"
        )
        applied.append("Race")

    if parsed.get("bmi") is not None:
        try:
            st.session_state["bmi_val"] = float(parsed["bmi"])
            applied.append("BMI")
        except Exception:
            pass
    if parsed.get("egfr") is not None:
        try:
            st.session_state["egfr_val"] = float(parsed["egfr"])
            applied.append("eGFR")
        except Exception:
            pass
    if parsed.get("lipidLowering") is not None:
        st.session_state["lipid_lowering_val"] = "Yes" if bool(parsed["lipidLowering"]) else "No"
        applied.append("Lipid therapy")

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

def cb_parse_and_apply():
    raw_txt = st.session_state.get("smartphrase_raw", "") or ""
    parsed = parse_smartphrase(raw_txt) if raw_txt.strip() else {}
    st.session_state["parsed_preview_cache"] = parsed

    applied, missing = apply_parsed_to_session(parsed, raw_txt)
    st.session_state["last_applied_msg"] = "Applied: " + (", ".join(applied) if applied else "None")
    st.session_state["last_missing_msg"] = "Missing/unparsed: " + (", ".join(missing) if missing else "")

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

# PREVENT defaults
st.session_state.setdefault("bmi_val", 0.0)
st.session_state.setdefault("egfr_val", 0.0)
st.session_state.setdefault("lipid_lowering_val", "No")

st.session_state.setdefault("smartphrase_raw", "")
st.session_state.setdefault("parsed_preview_cache", {})
st.session_state.setdefault("last_applied_msg", "")
st.session_state.setdefault("last_missing_msg", "")

for k in ["ra", "psoriasis", "sle", "ibd", "hiv", "osa", "nafld"]:
    st.session_state.setdefault(f"infl_{k}_val", False)

# ============================================================
# DEMO defaults (optional)
# ============================================================
st.session_state.setdefault("demo_defaults_on", True)
st.session_state.setdefault("demo_defaults_applied", False)

def apply_demo_defaults():
    st.session_state["age_val"] = 55
    st.session_state["sex_val"] = "M"
    st.session_state["race_val"] = "Other (use non-African American coefficients)"
    st.session_state["sbp_val"] = 128
    st.session_state["bp_treated_val"] = "No"
    st.session_state["smoking_val"] = "No"
    st.session_state["diabetes_choice_val"] = "No"

    st.session_state["tc_val"] = 190
    st.session_state["hdl_val"] = 50
    st.session_state["ldl_val"] = 115
    st.session_state["apob_val"] = 92
    st.session_state["lpa_val"] = 90
    st.session_state["lpa_unit_val"] = "nmol/L"
    st.session_state["a1c_val"] = 5.6
    st.session_state["hscrp_val"] = 1.2

    st.session_state["cac_known_val"] = "No"
    st.session_state["cac_val"] = 0

    st.session_state["bmi_val"] = 28.0
    st.session_state["egfr_val"] = 85.0
    st.session_state["lipid_lowering_val"] = "No"

    for kk in ["ra", "psoriasis", "sle", "ibd", "hiv", "osa", "nafld"]:
        st.session_state[f"infl_{kk}_val"] = False

    st.session_state["demo_defaults_applied"] = True

def reset_demo_defaults():
    st.session_state["demo_defaults_applied"] = False

with st.sidebar:
    st.markdown("### Demo")
    demo_on = st.checkbox("Use demo defaults (auto-fill)", value=st.session_state["demo_defaults_on"])
    st.session_state["demo_defaults_on"] = demo_on

    cA, cB = st.columns(2)
    with cA:
        if st.button("Apply demo"):
            apply_demo_defaults()
    with cB:
        if st.button("Reset demo"):
            reset_demo_defaults()

if st.session_state["demo_defaults_on"] and not st.session_state["demo_defaults_applied"]:
    apply_demo_defaults()

# ============================================================
# Clear callbacks
# ============================================================
def cb_clear_pasted_text():
    st.session_state["smartphrase_raw"] = ""
    st.session_state["parsed_preview_cache"] = {}
    st.session_state["last_applied_msg"] = ""
    st.session_state["last_missing_msg"] = ""

def cb_clear_autofilled_fields():
    for k, v in [
        ("age_val", 0), ("sex_val", "F"), ("race_val", "Other (use non-African American coefficients)"),
        ("sbp_val", 0), ("tc_val", 0), ("ldl_val", 0), ("hdl_val", 0),
        ("apob_val", 0), ("lpa_val", 0), ("lpa_unit_val", "nmol/L"),
        ("a1c_val", 0.0), ("hscrp_val", 0.0),
        ("bp_treated_val", "No"), ("smoking_val", "No"), ("diabetes_choice_val", "No"),
        ("cac_known_val", "No"), ("cac_val", 0),
        ("bmi_val", 0.0), ("egfr_val", 0.0), ("lipid_lowering_val", "No"),
    ]:
        st.session_state[k] = v

    for kk in ["ra", "psoriasis", "sle", "ibd", "hiv", "osa", "nafld"]:
        st.session_state[f"infl_{kk}_val"] = False

    st.session_state["last_applied_msg"] = ""
    st.session_state["last_missing_msg"] = ""
    st.session_state["demo_defaults_applied"] = False

# ============================================================
# SmartPhrase ingest
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
        height=220,
        placeholder="Paste Epic output here…",
        key="smartphrase_raw",
    )

    if smart_txt and contains_phi(smart_txt):
        st.warning("Possible identifier/date detected in pasted text. Please remove PHI before using.")

    parsed_preview = parse_smartphrase(smart_txt or "") if (smart_txt or "").strip() else {}
    st.session_state["parsed_preview_cache"] = parsed_preview

    if st.session_state.get("last_applied_msg"):
        st.success(st.session_state["last_applied_msg"])
    if st.session_state.get("last_missing_msg"):
        st.warning(st.session_state["last_missing_msg"])

    c1, c2, c3, c4 = st.columns([1, 1, 1.4, 2.6])
    with c1:
        st.button("Parse & Apply", type="primary", on_click=cb_parse_and_apply)
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

# ============================================================
# Main form
# ============================================================
with st.form("risk_continuum_form"):
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

    # PREVENT inputs (required)
    b4, b5, b6 = st.columns(3)
    with b4:
        bmi = st.number_input("BMI (kg/m²) (for PREVENT)", 0.0, 80.0, step=0.1, format="%.1f", key="bmi_val")
    with b5:
        lipid_lowering = st.radio(
            "On lipid-lowering therapy? (for PREVENT)",
            ["No", "Yes"],
            horizontal=True,
            key="lipid_lowering_val",
        )
    with b6:
        st.caption("PREVENT requires BMI, eGFR, and lipid-therapy status.")

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
        egfr = st.number_input("eGFR (mL/min/1.73m²) (for PREVENT)", 0.0, 200.0, step=1.0, format="%.0f", key="egfr_val")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Imaging")

    d1, d2 = st.columns([1, 2])
    with d1:
        cac_known = st.radio("Calcium score available?", ["Yes", "No"], horizontal=True, key="cac_known_val")
    with d2:
        st.number_input(
            "Calcium score (Agatston)",
            min_value=0,
            max_value=5000,
            step=1,
            key="cac_val",
            disabled=False,
            help="If CAC is not available, set 'Calcium score available?' to No. The engine will ignore this value.",
        )

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

    show_json = st.checkbox("Show JSON (debug)", value=False)
    submitted = st.form_submit_button("Run", type="primary")

# ============================================================
# Output rendering (Tabbed)
# ============================================================
if submitted:
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
        "ra": bool(ra),
        "psoriasis": bool(psoriasis),
        "sle": bool(sle),
        "ibd": bool(ibd),
        "hiv": bool(hiv),
        "osa": bool(osa),
        "nafld": bool(nafld),
        "bleed_gi": bool(bleed_gi),
        "bleed_ich": bool(bleed_ich),
        "bleed_anticoag": bool(bleed_anticoag),
        "bleed_nsaid": bool(bleed_nsaid),
        "bleed_disorder": bool(bleed_disorder),
        "bleed_ckd": bool(bleed_ckd),

        # PREVENT required inputs
        "bmi": float(bmi) if bmi and bmi > 0 else None,
        "egfr": float(egfr) if egfr and egfr > 0 else None,
        "lipid_lowering": (lipid_lowering == "Yes"),
    }
    data = {k: v for k, v in data.items() if v is not None}

    patient = Patient(data)
    out = evaluate(patient)

    note_text = scrub_terms(render_quick_text(patient, out))

    lvl = out.get("levels", {}) or {}
    ev = (lvl.get("evidence") or {}) if isinstance(lvl.get("evidence"), dict) else {}
    rs = out.get("riskSignal", {}) or {}
    risk10 = out.get("pooledCohortEquations10yAscvdRisk", {}) or {}
    prevent10 = out.get("prevent10", {}) or {}

    level = (lvl.get("managementLevel") or lvl.get("postureLevel") or lvl.get("level") or 1)
    try:
        level = int(level)
    except Exception:
        level = 1
    level = max(1, min(5, level))
    sub = lvl.get("sublevel")

    legend = lvl.get("legend") or FALLBACK_LEVEL_LEGEND
    explainer = scrub_terms(lvl.get("explainer") or "")
    rec_tag = scrub_terms(lvl.get("recommendationStrength") or "—")

    # LDL-first targets block
    t_pick = pick_dual_targets_ldl_first(out, data)
    primary = t_pick["primary"]
    apob_line = t_pick["secondary"]
    apob_measured = t_pick["apob_measured"]

    clinical_ascvd = bool(ev.get("clinical_ascvd")) if isinstance(ev, dict) else False

    # Plan one-liner (strip tag prefix)
    plan = lvl.get("defaultPosture") or ""
    plan_clean = re.sub(r"^\s*(Recommended:|Consider:|Pending more data:)\s*", "", str(plan)).strip()
    plan_clean = scrub_terms(plan_clean)

    # Next steps bullets (engine)
    next_actions = scrub_list(out.get("nextActions", []) or [])

    # PREVENT values
    p_total = prevent10.get("total_cvd_10y_pct")
    p_ascvd = prevent10.get("ascvd_10y_pct")
    p_note = scrub_terms(prevent10.get("notes", ""))

    tab_overview, tab_report, tab_details, tab_debug = st.tabs(["Overview", "Report", "Details", "Debug"])

    # =========================
    # OVERVIEW (tight)
    # =========================
    with tab_overview:
        title_line = f"Level {level}" + (f" ({sub})" if sub else "") + f" — {LEVEL_NAMES.get(level,'—')}"
        evidence_line = f"Evidence: {scrub_terms(ev.get('cac_status','—'))}  |  Burden: {scrub_terms(ev.get('burden_band','—'))}"

        st.markdown(
            f"""
<div class="level-strip">
  <div class="title">{title_line}</div>
  <div class="sub">{evidence_line}</div>
</div>
""",
            unsafe_allow_html=True,
        )

        # Metrics row (RSS / PCE / PREVENT total / PREVENT ASCVD)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Risk Signal Score", f"{rs.get('score','—')}/100", rs.get("band","—"))
        m2.metric("PCE 10y ASCVD", f"{risk10.get('risk_pct')}%" if risk10.get("risk_pct") is not None else "—", risk10.get("category",""))
        m3.metric("PREVENT 10y total CVD", f"{p_total}%" if p_total is not None else "—")
        m4.metric("PREVENT 10y ASCVD", f"{p_ascvd}%" if p_ascvd is not None else "—")

        if (p_total is None and p_ascvd is None) and p_note:
            st.caption(f"PREVENT: {p_note}")

        # Lipid targets (compact)
        st.markdown("### Lipid targets")
        if primary:
            st.markdown(f"**{primary[0]} {primary[1]}**")
            st.caption(guideline_anchor_note(level, clinical_ascvd))
        else:
            st.markdown("**Target: —**")

        if apob_line is not None:
            hover = (
                "Quick anchors: <80 good • 80–99 borderline • ≥100 high • ≥130 very high (risk signal). "
                "ApoB is a particle-count check—especially helpful when TG/metabolic risk is present."
            )
            st.markdown(f"**{apob_line[0]} {apob_line[1]}** <span title=\"{hover}\">ⓘ</span>", unsafe_allow_html=True)
            st.caption("ApoB: risk-enhancing marker (ACC/AHA) and treatment target in higher-risk tiers (ESC/EAS).")
            if not apob_measured:
                st.caption("ApoB not measured here — optional add-on to check for discordance.")

        # Plan + Next steps (tight)
        st.markdown("### Plan")
        st.write(plan_clean if plan_clean else "—")

        if explainer:
            st.caption(f"Explainer: {explainer}")

        st.markdown("### Next steps")
        if next_actions:
            st.markdown("<div class='next-box'>" + "<br>".join([f"• {a}" for a in next_actions[:3]]) + "</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='next-box'>—</div>", unsafe_allow_html=True)

        # Optional quick references
        with st.expander("How Levels work (legend + quick reference)", expanded=False):
            st.caption("Legend:")
            for item in legend:
                st.write(f"• {scrub_terms(item)}")

        with st.expander("PREVENT comparator (details)", expanded=False):
            if p_total is not None or p_ascvd is not None:
                st.markdown(f"**10-year total CVD:** {p_total}%")
                st.markdown(f"**10-year ASCVD:** {p_ascvd}%")
            else:
                st.caption(p_note or "PREVENT not calculated.")

        # Downloads
        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "Download clinical text (.txt)",
                data=note_text.encode("utf-8"),
                file_name="risk_continuum_note.txt",
                mime="text/plain",
                use_container_width=True,
            )
        with d2:
            st.download_button(
                "Download JSON",
                data=json.dumps(out, indent=2).encode("utf-8"),
                file_name="risk_continuum_output.json",
                mime="application/json",
                use_container_width=True,
            )

    # =========================
    # REPORT (single source of truth narrative)
    # =========================
    with tab_report:
        st.subheader("Clinical report (high-yield)")
        st.markdown(render_high_yield_report(out), unsafe_allow_html=True)

    # =========================
    # DETAILS (when you need it)
    # =========================
    with tab_details:
        st.subheader("Anchors (near-term vs lifetime)")
        anchors = out.get("anchors", {}) or {}
        near = scrub_terms((anchors.get("nearTerm") or {}).get("summary", "—"))
        life = scrub_terms((anchors.get("lifetime") or {}).get("summary", "—"))
        st.markdown(f"**Near-term anchor:** {near}")
        st.markdown(f"**Lifetime anchor:** {life}")

        st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

        st.subheader("Interpretation (why / recommendation tag)")
        st.markdown(f"**Recommendation tag:** {rec_tag}")

        why_list = scrub_list((lvl.get("why") or [])[:5])
        if why_list:
            st.markdown("**Why this level:**")
            for w in why_list:
                st.write(f"• {w}")

        st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

        st.subheader("Aspirin")
        asp = out.get("aspirin", {}) or {}
        asp_status = scrub_terms(asp.get("status", "Not assessed"))
        asp_why = scrub_terms(short_why(asp.get("rationale", []), max_items=4))
        st.write(f"**{asp_status}**" + (f" — **Why:** {asp_why}" if asp_why else ""))

    # =========================
    # DEBUG (raw output)
    # =========================
    with tab_debug:
        st.subheader("Quick output (raw text)")
        st.code(note_text, language="text")

        st.subheader("Trace (audit trail)")
        st.json(out.get("trace", []))

        if show_json:
            st.subheader("JSON (debug)")
            st.json(out)

    st.caption(
        f"Versions: {VERSION.get('levels','')} | {VERSION.get('riskSignal','')} | {VERSION.get('riskCalc','')} | "
        f"{VERSION.get('aspirin','')} | {VERSION.get('prevent','')}. No storage intended."
    )
else:
    st.caption("Enter values (or use Demo defaults) and click Run.")

