# app.py (Risk Continuum — v2.8 clinician-clean layout)
#
# COMPLETE, UPDATED, "NO OVERVIEW" VERSION with improvements:
# - Input validation warnings
# - Engine caching for speed
# - Markdown download button
# - Last calculation timestamp
# - Clearer PREVENT fallback message
# - Disabled CAC input when "No" selected

import json
import re
import textwrap
import html as _html
import uuid
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components
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
.hr { margin:12px 0 14px 0; border-top:1px solid rgba(31,41,55,0.12); }
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
.block {
  border:1px solid rgba(31,41,55,0.12);
  border-radius:14px;
  background:#fff;
  padding:14px 16px;
}
.block-title {
  font-variant-caps:all-small-caps;
  letter-spacing:0.08em;
  font-weight:900;
  font-size:0.85rem;
  color:#4b5563;
  margin-bottom:8px;
}
.kvline { margin: 6px 0; line-height:1.35; }
.kvline b { font-weight:900; }
.callout {
  border:1px solid rgba(31,41,55,0.10);
  border-radius:12px;
  padding:12px 12px;
  background:#fbfbfb;
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

with st.expander("DEBUG: engine version", expanded=False):
    st.write("Engine sentinel:", getattr(le, "PCE_DEBUG_SENTINEL", "MISSING"))
    st.write("Engine VERSION:", getattr(le, "VERSION", {}))

# ============================================================
# Guardrails + scrubbing
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
# Visual: Risk Continuum bar
# ============================================================
def render_risk_continuum_bar(level: int, sublevel: str | None = None) -> str:
    lvl = max(1, min(5, int(level or 1)))
    sub = f" ({sublevel})" if sublevel else ""
    labels = {
        1: "Minimal risk signal",
        2: "Emerging risk signals",
        3: "Actionable biologic risk",
        4: "Subclinical atherosclerosis present",
        5: "Very high risk / ASCVD intensity",
    }
    colors = {
        1: "rgba(59,130,246,0.10)",
        2: "rgba(16,185,129,0.10)",
        3: "rgba(245,158,11,0.12)",
        4: "rgba(249,115,22,0.12)",
        5: "rgba(239,68,68,0.12)",
    }
    segs = []
    for i in range(1, 6):
        active = (i == lvl)
        outline = "2px solid #111827" if active else "1px solid rgba(31,41,55,0.25)"
        shadow = "0 8px 20px rgba(0,0,0,0.18)" if active else "none"
        arrow = ""
        if active:
            arrow = """
<div style="display:flex;justify-content:center;margin-bottom:2px;">
  <div style="font-size:1.15rem;line-height:1;font-weight:900;color:#111827;">▼</div>
</div>
"""
        seg_html = f"""
<div style="flex:1; display:flex; flex-direction:column; align-items:stretch;">
  {arrow}
  <div style="
      padding:10px 10px;
      border:{outline};
      border-radius:12px;
      background:{colors[i]};
      box-shadow:{shadow};
      font-weight:{'900' if active else '700'};
      text-align:center;
      font-size:0.90rem;
      line-height:1.15;">
    <div>Level {i}</div>
    <div style="font-weight:600;font-size:0.78rem;color:rgba(31,41,55,0.75);margin-top:2px;">
      {labels[i]}
    </div>
  </div>
</div>
"""
        segs.append(textwrap.dedent(seg_html).strip())
    html = f"""
<div style="margin-top:8px;margin-bottom:12px;">
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px;">
    <div style="font-weight:900;font-size:1.05rem;">Risk Continuum</div>
    <div style="font-weight:800;color:rgba(31,41,55,0.70);font-size:0.92rem;">
      Current: Level {lvl}{sub}
    </div>
  </div>
  <div style="display:flex;gap:10px;align-items:flex-start;">
    {''.join(segs)}
  </div>
  <div style="display:flex;justify-content:space-between;margin-top:6px;color:rgba(31,41,55,0.65);font-size:0.82rem;">
    <div>Lower signal / lower urgency</div>
    <div>Higher signal / higher urgency</div>
  </div>
</div>
"""
    return textwrap.dedent(html).strip()

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

# ============================================================
# Polished EMR Copy Box
# ============================================================
def emr_copy_box(title: str, text: str, height_px: int = 440):
    uid = uuid.uuid4().hex[:10]
    safe_text = _html.escape(text or "")
    title_safe = _html.escape(title or "Clinical Report")
    components.html(
        f"""
<div style="border:1px solid rgba(31,41,55,0.12); border-radius:14px; padding:14px 14px; background:#ffffff;">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
    <div style="font-weight:900; font-size:14px; color:#111827;">{title_safe}</div>
    <button id="copyBtn_{uid}" style="
      border:1px solid rgba(31,41,55,0.18);
      background:#ffffff;
      border-radius:10px;
      padding:7px 12px;
      font-weight:800;
      cursor:pointer;
      color:#111827;
    ">Copy</button>
  </div>
  <textarea id="noteText_{uid}" readonly style="
    width:100%;
    height:{max(220, height_px - 90)}px;
    border:1px solid rgba(31,41,55,0.12);
    border-radius:12px;
    padding:12px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
    font-size:12.5px;
    line-height:1.35;
    color:#111827;
    background:#fbfbfb;
    resize: none;
    box-sizing: border-box;
  ">{safe_text}</textarea>
  <div id="copiedMsg_{uid}" style="margin-top:10px; color:rgba(31,41,55,0.65); font-size:12px; min-height:16px;"></div>
</div>
<script>
(function() {{
  const btn = document.getElementById("copyBtn_{uid}");
  const ta = document.getElementById("noteText_{uid}");
  const msg = document.getElementById("copiedMsg_{uid}");
  async function doCopy() {{
    try {{
      await navigator.clipboard.writeText(ta.value);
      msg.textContent = "Copied to clipboard.";
      setTimeout(() => msg.textContent = "", 1500);
    }} catch (e) {{
      try {{
        ta.focus();
        ta.select();
        const ok = document.execCommand("copy");
        msg.textContent = ok ? "Copied to clipboard." : "Copy failed — select all and copy manually.";
        setTimeout(() => msg.textContent = "", 2000);
      }} catch (e2) {{
        msg.textContent = "Copy failed — select all and copy manually.";
        setTimeout(() => msg.textContent = "", 2500);
      }}
    }}
  }}
  btn.addEventListener("click", doCopy);
}})();
</script>
        """,
        height=height_px,
    )

# ============================================================
# High-yield narrative
# ============================================================
def render_high_yield_report(out: dict) -> str:
    lvl = out.get("levels", {}) or {}
    rs = out.get("riskSignal", {}) or {}
    risk10 = out.get("pooledCohortEquations10yAscvdRisk", {}) or {}
    targets = out.get("targets", {}) or {}
    ev = (lvl.get("evidence") or {}) if isinstance(lvl.get("evidence"), dict) else {}
    drivers = scrub_list(out.get("drivers", []) or [])
    next_actions = scrub_list(out.get("nextActions", []) or [])
    asp = out.get("aspirin", {}) or {}
    ins = out.get("insights", {}) or {}
    prevent10 = out.get("prevent10", {}) or {}
    p_total = prevent10.get("total_cvd_10y_pct")
    p_ascvd = prevent10.get("ascvd_10y_pct")
    level = int(lvl.get("managementLevel") or lvl.get("postureLevel") or lvl.get("level") or 1)
    level = max(1, min(5, level))
    sub = lvl.get("sublevel")
    title = f"{SYSTEM_NAME} — Level {level}: {LEVEL_NAMES.get(level,'—')}" + (f" ({sub})" if sub else "")
    risk_pct = risk10.get("risk_pct")
    risk_line = f"{risk_pct}%" if risk_pct is not None else "—"
    risk_cat = risk10.get("category") or ""
    evidence_line = scrub_terms(ev.get("cac_status") or out.get("diseaseBurden") or "—")
    burden_line = scrub_terms(ev.get("burden_band") or "—")
    decision_conf = scrub_terms(lvl.get("decisionConfidence") or "—")
    rec_tag = scrub_terms(lvl.get("recommendationStrength") or "—")
    explainer = scrub_terms(lvl.get("explainer") or "")
    meaning = scrub_terms(lvl.get("meaning") or "")
    html = []
    html.append('<div class="block">')
    html.append(f'<div style="font-weight:900;font-size:1.05rem;margin-bottom:6px;">{title}</div>')
    html.append('<div class="block-title">Summary</div>')
    html.append(f"<div class='kvline'>{meaning or '—'}</div>")
    if explainer:
        html.append(f"<div class='kvline'><b>Level explainer:</b> {explainer}</div>")
    html.append(f"<div class='kvline'><b>Decision confidence:</b> {decision_conf}</div>")
    html.append(f"<div class='kvline'><b>Engine tag (debug):</b> {rec_tag}</div>")
    html.append('<div class="hr"></div>')
    html.append('<div class="block-title">Key metrics</div>')
    html.append(f"<div class='kvline'><b>RSS:</b> {rs.get('score','—')}/100 ({rs.get('band','—')})</div>")
    html.append(f"<div class='kvline'><b>PCE 10y:</b> {risk_line} {f'({risk_cat})' if risk_cat else ''}</div>")
    html.append(f"<div class='kvline'><b>PREVENT 10y:</b> total CVD {p_total if p_total is not None else '—'} / ASCVD {p_ascvd if p_ascvd is not None else '—'}</div>")
    html.append(f"<div class='kvline'><b>Evidence:</b> {evidence_line}</div>")
    html.append(f"<div class='kvline'><b>Burden:</b> {burden_line}</div>")
    html.append('<div class="hr"></div>')
    html.append('<div class="block-title">Plan & actions</div>')
    plan = scrub_terms(re.sub(r"^\s*(Recommended:|Consider:|Pending more data:)\s*", "", str(lvl.get("defaultPosture",""))).strip())
    html.append(f"<div class='kvline'><b>Plan:</b> {plan or '—'}</div>")
    if next_actions:
        html.append("<div class='kvline'><b>Next steps:</b></div>")
        html.append("<div class='kvline'>" + "<br>".join([f"• {a}" for a in next_actions[:3]]) + "</div>")
    html.append(f"<div class='kvline'><b>Aspirin:</b> {scrub_terms(asp.get('status','—'))}</div>")
    if ins.get("structural_clarification"):
        html.append(f"<div class='kvline'><span class='muted'>{scrub_terms(ins.get('structural_clarification'))}</span></div>")
    html.append('<div class="hr"></div>')
    html.append('<div class="block-title">Clinical context</div>')
    if drivers:
        html.append(f"<div class='kvline'><b>Risk driver:</b> {drivers[0]}</div>")
    if ins.get("phenotype_label"):
        html.append(f"<div class='kvline'><b>Phenotype:</b> {scrub_terms(ins.get('phenotype_label'))}</div>")
    if ins.get("decision_robustness"):
        html.append(
            f"<div class='kvline'><b>Decision robustness:</b> {scrub_terms(ins.get('decision_robustness'))}"
            + (f" — {scrub_terms(ins.get('decision_robustness_note',''))}" if ins.get("decision_robustness_note") else "")
            + "</div>"
        )
    if ev.get("cac_status") == "Unknown":
        html.append("<div class='kvline'><b>Structural status:</b> Unknown (CAC not performed)</div>")
    html.append("</div>")
    return "\n".join(html)

# ============================================================
# Parse & Apply Helpers
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
    def apply_num(src_key, state_key, coerce_fn, label, fallback_val=None):
        nonlocal applied, missing
        v = parsed.get(src_key)
        v2 = coerce_fn(v)
        if v2 is None:
            if fallback_val is not None:
                st.session_state[state_key] = fallback_val
            missing.append(label)
            return
        st.session_state[state_key] = v2
        applied.append(label)

    # Core numerics
    apply_num("age", "age_val", coerce_int, "Age")
    apply_num("sbp", "sbp_val", coerce_int, "Systolic BP")
    apply_num("tc", "tc_val", coerce_int, "Total Cholesterol")
    apply_num("hdl", "hdl_val", coerce_int, "HDL")
    apply_num("ldl", "ldl_val", coerce_int, "LDL")
    apply_num("apob", "apob_val", coerce_int, "ApoB")

    # Lp(a)
    lpa_v = coerce_float(parsed.get("lpa"))
    if lpa_v is not None:
        st.session_state["lpa_val"] = int(lpa_v)
        applied.append("Lp(a)")
    else:
        missing.append("Lp(a)")

    # Sex
    sex = parsed.get("sex")
    if sex in ("F", "M"):
        st.session_state["sex_val"] = sex
        applied.append("Gender")
    else:
        missing.append("Gender")

    # Lp(a) unit
    if parsed.get("lpa_unit") in ("nmol/L", "mg/dL"):
        st.session_state["lpa_unit_val"] = parsed["lpa_unit"]
        applied.append("Lp(a) unit")
    else:
        missing.append("Lp(a) unit")

    # A1c
    a1c_v = coerce_float(parsed.get("a1c"))
    if a1c_v is not None:
        st.session_state["a1c_val"] = float(a1c_v)
        applied.append("A1c")
    else:
        missing.append("A1c")

    # Smoking
    if parsed.get("smoker") is not None:
        st.session_state["smoking_val"] = "Yes" if bool(parsed["smoker"]) else "No"
        applied.append("Smoking")

    # Diabetes (trust parser first, then fallback to negation guard)
    diabetes_parsed = parsed.get("diabetes")
    if diabetes_parsed is not None:
        st.session_state["diabetes_choice_val"] = "Yes" if bool(diabetes_parsed) else "No"
        applied.append("Diabetes")
    else:
        # Fallback to negation guard
        diabetes_guard = diabetes_negation_guard(raw_txt)
        if diabetes_guard is not None:
            st.session_state["diabetes_choice_val"] = "Yes" if diabetes_guard else "No"
            applied.append("Diabetes (from negation guard)")
        else:
            missing.append("Diabetes")

    # BP treated
    if parsed.get("bpTreated") is not None:
        st.session_state["bp_treated_val"] = "Yes" if bool(parsed["bpTreated"]) else "No"
        applied.append("BP meds")
    else:
        missing.append("BP meds")

    # Race
    if parsed.get("africanAmerican") is not None:
        st.session_state["race_val"] = (
            "African American" if bool(parsed["africanAmerican"]) else "Other (use non-African American coefficients)"
        )
        applied.append("Race")

    # Family history
    fhx_txt = parsed.get("fhx_text")
    if fhx_txt:
        st.session_state["fhx_choice_val"] = fhx_txt
        applied.append("Premature family history")
    else:
        missing.append("Premature family history")

    # CAC
    if parsed.get("cac_not_done") is True:
        st.session_state["cac_known_val"] = "No"
        st.session_state["cac_val"] = 0
        applied.append("Calcium score (not done)")
    else:
        cac_v = coerce_int(parsed.get("cac"))
        if cac_v is not None:
            st.session_state["cac_known_val"] = "Yes"
            st.session_state["cac_val"] = int(cac_v)
            applied.append("Calcium score")
        else:
            st.session_state["cac_known_val"] = "No"
            st.session_state["cac_val"] = 0
            missing.append("Calcium score")

    # PREVENT fields
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

    # hsCRP + inflammatory flags
    h = parse_hscrp_from_text(raw_txt)
    if h is not None:
        st.session_state["hscrp_val"] = float(h)
        applied.append("hsCRP")
    infl = parse_inflammatory_flags_from_text(raw_txt)
    for k, v in infl.items():
        st.session_state[f"infl_{k}_val"] = bool(v)
        applied.append(k.upper())

    # De-dupe missing
    missing = list(dict.fromkeys(missing))
    return applied, missing

# ============================================================
# Session Defaults & Demo
# ============================================================
def reset_fields():
    defaults = {
        "age_val": 0, "sex_val": "F", "race_val": "Other (use non-African American coefficients)",
        "ascvd_val": "No", "fhx_choice_val": "None / Unknown", "sbp_val": 0,
        "bp_treated_val": "No", "smoking_val": "No", "diabetes_choice_val": "No",
        "a1c_val": 0.0, "tc_val": 0, "ldl_val": 0, "hdl_val": 0,
        "apob_val": 0, "lpa_val": 0, "lpa_unit_val": "nmol/L", "hscrp_val": 0.0,
        "cac_known_val": "No", "cac_val": 0, "bmi_val": 0.0, "egfr_val": 0.0,
        "lipid_lowering_val": "No", "demo_defaults_applied": False,
        "last_applied_msg": "", "last_missing_msg": ""
    }
    for k, v in defaults.items():
        st.session_state[k] = v
    for kk in ["ra", "psoriasis", "sle", "ibd", "hiv", "osa", "nafld"]:
        st.session_state[f"infl_{kk}_val"] = False
    for bk in ["bleed_gi", "bleed_nsaid", "bleed_anticoag", "bleed_disorder", "bleed_ich", "bleed_ckd"]:
        st.session_state[bk] = False

for key, default in [
    ("age_val", 0), ("sex_val", "F"), ("race_val", "Other (use non-African American coefficients)"),
    ("ascvd_val", "No"), ("fhx_choice_val", "None / Unknown"), ("sbp_val", 0),
    ("bp_treated_val", "No"), ("smoking_val", "No"), ("diabetes_choice_val", "No"),
    ("a1c_val", 0.0), ("tc_val", 0), ("ldl_val", 0), ("hdl_val", 0),
    ("apob_val", 0), ("lpa_val", 0), ("lpa_unit_val", "nmol/L"), ("hscrp_val", 0.0),
    ("cac_known_val", "No"), ("cac_val", 0), ("bmi_val", 0.0), ("egfr_val", 0.0),
    ("lipid_lowering_val", "No"), ("smartphrase_raw", ""), ("parsed_preview_cache", {}),
    ("last_applied_msg", ""), ("last_missing_msg", ""), ("demo_defaults_on", True),
    ("demo_defaults_applied", False)
]:
    st.session_state.setdefault(key, default)

for k in ["ra", "psoriasis", "sle", "ibd", "hiv", "osa", "nafld"]:
    st.session_state.setdefault(f"infl_{k}_val", False)

def apply_demo_defaults():
    st.session_state.update({
        "age_val": 55, "sex_val": "M", "race_val": "Other (use non-African American coefficients)",
        "ascvd_val": "No", "fhx_choice_val": "None / Unknown", "sbp_val": 128,
        "bp_treated_val": "No", "smoking_val": "No", "diabetes_choice_val": "No",
        "tc_val": 190, "hdl_val": 50, "ldl_val": 115, "apob_val": 92,
        "lpa_val": 90, "lpa_unit_val": "nmol/L", "a1c_val": 5.6, "hscrp_val": 1.2,
        "cac_known_val": "No", "cac_val": 0, "bmi_val": 28.0, "egfr_val": 85.0,
        "lipid_lowering_val": "No", "demo_defaults_applied": True
    })
    for kk in ["ra", "psoriasis", "sle", "ibd", "hiv", "osa", "nafld"]:
        st.session_state[f"infl_{kk}_val"] = False
    for bk in ["bleed_gi", "bleed_nsaid", "bleed_anticoag", "bleed_disorder", "bleed_ich", "bleed_ckd"]:
        st.session_state[bk] = False

# Sidebar Demo Controls
with st.sidebar:
    st.markdown("### Demo")
    demo_on = st.checkbox("Use demo defaults (auto-fill)", value=st.session_state["demo_defaults_on"])
    st.session_state["demo_defaults_on"] = demo_on
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Apply demo"):
            apply_demo_defaults()
            st.rerun()
    with c2:
        if st.button("Reset fields"):
            reset_fields()
            st.rerun()

if st.session_state["demo_defaults_on"] and not st.session_state["demo_defaults_applied"]:
    apply_demo_defaults()

# ============================================================
# SmartPhrase Ingest
# ============================================================
st.subheader("SmartPhrase ingest (optional)")

with st.expander("Paste Epic output to auto-fill fields", expanded=False):
    st.markdown(
        "<div class='small-help'>Paste rendered Epic output (SmartPhrase text, ASCVD block, lipid panel, etc). "
        "Click <strong>Parse & Apply</strong>. This will auto-fill as many fields as possible and explicitly flag what was not found.</div>",
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

    c1, c2, c3 = st.columns([1.2, 1.2, 2.2])

    with c1:
        if st.button("Parse & Apply", type="primary"):
            raw_txt = st.session_state.get("smartphrase_raw", "") or ""
            if not raw_txt.strip():
                st.warning("No text to parse — please paste something first.")
            else:
                parsed = parse_smartphrase(raw_txt)
                st.session_state["parsed_preview_cache"] = parsed
                
                applied, missing = apply_parsed_to_session(parsed, raw_txt)
                
                st.session_state["last_applied_msg"] = (
                    "Applied: " + (", ".join(applied) if applied else "None")
                )
                st.session_state["last_missing_msg"] = (
                    "Missing/unparsed: " + (", ".join(missing) if missing else "All good!")
                )
                st.rerun()

    with c2:
        def clear_text():
            st.session_state.smartphrase_raw = ""
            st.session_state.parsed_preview_cache = {}
            st.session_state.last_applied_msg = ""
            st.session_state.last_missing_msg = ""

        st.button("Clear pasted text", on_click=clear_text)

    with c3:
        st.caption("Parsed preview")
        parsed_preview = st.session_state.get("parsed_preview_cache", {})
        if parsed_preview:
            st.json(parsed_preview)
        else:
            st.info("Nothing parsed yet.")

    st.markdown("### Parse coverage (explicit)")
    parsed_preview = st.session_state.get("parsed_preview_cache", {})
    for key, label in TARGET_PARSE_FIELDS:
        ok = parsed_preview.get(key) is not None
        badge = "<span class='badge ok'>parsed</span>" if ok else "<span class='badge miss'>not found</span>"
        val = f": {parsed_preview.get(key)}" if ok else ""
        st.markdown(f"- **{label}** {badge}{val}", unsafe_allow_html=True)

    if st.session_state.get("last_applied_msg"):
        st.success(st.session_state["last_applied_msg"])
    if st.session_state.get("last_missing_msg"):
        st.warning(st.session_state["last_missing_msg"])

# ============================================================
# Main Form with Validation Warnings
# ============================================================
with st.form("risk_continuum_form"):
    st.subheader("Patient context")
    a1, a2, a3 = st.columns(3)
    with a1:
        age = st.number_input("Age (years)", 18, 120, step=1, key="age_val")
        if age < 30 or age > 79:
            st.warning("Age outside validated range (30–79 for PREVENT/PCE)")
        st.radio("Gender", ["F", "M"], horizontal=True, key="sex_val")
    with a2:
        race_options = ["Other (use non-African American coefficients)", "African American"]
        st.radio("Race (calculator)", race_options, horizontal=False, key="race_val")
    with a3:
        st.radio("ASCVD (clinical)", ["No", "Yes"], horizontal=True, key="ascvd_val")
    st.selectbox("Premature family history", FHX_OPTIONS, index=0, key="fhx_choice_val")
    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    st.subheader("Cardiometabolic profile")
    b1, b2, b3 = st.columns(3)
    with b1:
        sbp = st.number_input("Systolic BP (mmHg)", 50, 300, step=1, key="sbp_val")
        if sbp < 90 or sbp > 220:
            st.warning("SBP value looks unusual — please double-check")
        st.radio("On BP meds?", ["No", "Yes"], horizontal=True, key="bp_treated_val")
    with b2:
        st.radio("Smoking (current)", ["No", "Yes"], horizontal=True, key="smoking_val")
        st.radio("Diabetes (manual)", ["No", "Yes"], horizontal=True, key="diabetes_choice_val")
    with b3:
        a1c = st.number_input("A1c (%)", 0.0, 15.0, step=0.1, format="%.1f", key="a1c_val")
        if a1c >= 6.5:
            st.info("A1c ≥ 6.5% ⇒ Diabetes will be set to YES automatically.")
        if a1c > 15:
            st.warning("A1c >15% — verify value")
    b4, b5, b6 = st.columns(3)
    with b4:
        bmi = st.number_input("BMI (kg/m²) (for PREVENT)", 10.0, 80.0, step=0.1, format="%.1f", key="bmi_val")
        if bmi < 15 or bmi > 60:
            st.warning("BMI value looks unusual — please double-check")
    with b5:
        st.radio("On lipid-lowering therapy? (for PREVENT)", ["No", "Yes"], horizontal=True, key="lipid_lowering_val")
    with b6:
        st.caption("PREVENT requires BMI, eGFR, and lipid-therapy status.")
    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    st.subheader("Labs")
    c1, c2, c3 = st.columns(3)
    with c1:
        tc = st.number_input("Total cholesterol (mg/dL)", 50, 500, step=1, key="tc_val")
        if tc < 50 or tc > 400:
            st.warning("TC value looks unusual — please double-check")
        ldl = st.number_input("LDL-C (mg/dL)", 20, 400, step=1, key="ldl_val")
        if ldl < 20 or ldl > 300:
            st.warning("LDL value looks unusual — please double-check")
        hdl = st.number_input("HDL cholesterol (mg/dL)", 20, 300, step=1, key="hdl_val")
    with c2:
        apob = st.number_input("ApoB (mg/dL)", 20, 300, step=1, key="apob_val")
        if apob < 20 or apob > 250:
            st.warning("ApoB value looks unusual — please double-check")
        lpa = st.number_input("Lp(a) value", 0, 2000, step=1, key="lpa_val")
        st.radio("Lp(a) unit", ["nmol/L", "mg/dL"], horizontal=True, key="lpa_unit_val")
    with c3:
        hscrp = st.number_input("hsCRP (mg/L) (optional)", 0.0, 50.0, step=0.1, format="%.1f", key="hscrp_val")
        egfr = st.number_input("eGFR (mL/min/1.73m²) (for PREVENT)", 0.0, 200.0, step=1.0, format="%.0f", key="egfr_val")
        if egfr < 15 or egfr > 150:
            st.warning("eGFR value looks unusual — please double-check")
    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    st.subheader("Imaging")
    d1, d2 = st.columns([1, 2])
    with d1:
        st.radio("Calcium score available?", ["Yes", "No"], horizontal=True, key="cac_known_val")
    with d2:
        st.number_input(
            "Calcium score (Agatston)",
            min_value=0,
            max_value=5000,
            step=1,
            key="cac_val",
            disabled=st.session_state["cac_known_val"] == "No",
            help="If CAC is not available, set 'Calcium score available?' to No. The engine will ignore this value.",
        )
    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    st.subheader("Inflammatory states (optional)")
    e1, e2, e3 = st.columns(3)
    with e1:
        st.checkbox("Rheumatoid arthritis", key="infl_ra_val")
        st.checkbox("Psoriasis", key="infl_psoriasis_val")
    with e2:
        st.checkbox("SLE", key="infl_sle_val")
        st.checkbox("IBD", key="infl_ibd_val")
    with e3:
        st.checkbox("HIV", key="infl_hiv_val")
        st.checkbox("OSA", key="infl_osa_val")
        st.checkbox("NAFLD/MASLD", key="infl_nafld_val")

    with st.expander("Bleeding risk (for aspirin decision-support) — optional"):
        f1, f2, f3 = st.columns(3)
        with f1:
            st.checkbox("Prior GI bleed / ulcer", value=st.session_state.get("bleed_gi", False), key="bleed_gi")
            st.checkbox("Chronic NSAID/steroid use", value=st.session_state.get("bleed_nsaid", False), key="bleed_nsaid")
        with f2:
            st.checkbox("Anticoagulant use", value=st.session_state.get("bleed_anticoag", False), key="bleed_anticoag")
            st.checkbox("Bleeding disorder / thrombocytopenia", value=st.session_state.get("bleed_disorder", False), key="bleed_disorder")
        with f3:
            st.checkbox("Prior intracranial hemorrhage", value=st.session_state.get("bleed_ich", False), key="bleed_ich")
            st.checkbox("Advanced CKD / eGFR <45", value=st.session_state.get("bleed_ckd", False), key="bleed_ckd")

    show_json = st.checkbox("Show JSON (debug)", value=False)
    submitted = st.form_submit_button("Run", type="primary")

# ============================================================
# Cached Engine Call
# ============================================================
@st.cache_data(ttl=300)  # Cache for 5 minutes
def run_engine(data_tuple):
    patient = Patient(dict(data_tuple))
    return evaluate(patient)

# ============================================================
# Run & Tabs
# ============================================================
if not submitted:
    st.caption("Enter values (or use Demo defaults) and click Run.")
    st.stop()

# Required field checks
req_errors = []
if st.session_state["age_val"] <= 0:
    req_errors.append("Age is required (must be > 0).")
if st.session_state["sbp_val"] <= 0:
    req_errors.append("Systolic BP is required (must be > 0).")
if st.session_state["tc_val"] <= 0:
    req_errors.append("Total cholesterol is required (must be > 0).")
if st.session_state["hdl_val"] <= 0:
    req_errors.append("HDL is required (must be > 0).")
if req_errors:
    st.error("Please complete required fields:\n- " + "\n- ".join(req_errors))
    st.stop()

# Build patient data
age = st.session_state["age_val"]
sex = st.session_state["sex_val"]
race = st.session_state["race_val"]
ascvd = st.session_state["ascvd_val"]
fhx_choice = st.session_state["fhx_choice_val"]
sbp = st.session_state["sbp_val"]
bp_treated = st.session_state["bp_treated_val"]
smoking = st.session_state["smoking_val"]
diabetes_choice = st.session_state["diabetes_choice_val"]
a1c = st.session_state["a1c_val"]
tc = st.session_state["tc_val"]
ldl = st.session_state["ldl_val"]
hdl = st.session_state["hdl_val"]
apob = st.session_state["apob_val"]
lpa = st.session_state["lpa_val"]
lpa_unit = st.session_state["lpa_unit_val"]
hscrp = st.session_state["hscrp_val"]
cac_known = st.session_state["cac_known_val"]
cac_to_send = int(st.session_state["cac_val"]) if cac_known == "Yes" else None
bmi = st.session_state["bmi_val"]
egfr = st.session_state["egfr_val"]
lipid_lowering = st.session_state["lipid_lowering_val"]
diabetes_effective = True if (a1c and float(a1c) >= 6.5) else (diabetes_choice == "Yes")

data = {
    "age": int(age) if age > 0 else None,
    "sex": sex,
    "race": "black" if race == "African American" else "other",
    "ascvd": (ascvd == "Yes"),
    "fhx": fhx_to_bool(fhx_choice),
    "sbp": int(sbp) if sbp > 0 else None,
    "bp_treated": (bp_treated == "Yes"),
    "smoking": (smoking == "Yes"),
    "diabetes": diabetes_effective,
    "a1c": float(a1c) if a1c > 0 else None,
    "tc": int(tc) if tc > 0 else None,
    "ldl": int(ldl) if ldl > 0 else None,
    "hdl": int(hdl) if hdl > 0 else None,
    "apob": int(apob) if apob > 0 else None,
    "lpa": float(lpa) if lpa > 0 else None,
    "lpa_unit": lpa_unit,
    "hscrp": float(hscrp) if hscrp > 0 else None,
    "cac": cac_to_send,
    "ra": st.session_state.get("infl_ra_val", False),
    "psoriasis": st.session_state.get("infl_psoriasis_val", False),
    "sle": st.session_state.get("infl_sle_val", False),
    "ibd": st.session_state.get("infl_ibd_val", False),
    "hiv": st.session_state.get("infl_hiv_val", False),
    "osa": st.session_state.get("infl_osa_val", False),
    "nafld": st.session_state.get("infl_nafld_val", False),
    "bleed_gi": st.session_state.get("bleed_gi", False),
    "bleed_ich": st.session_state.get("bleed_ich", False),
    "bleed_anticoag": st.session_state.get("bleed_anticoag", False),
    "bleed_nsaid": st.session_state.get("bleed_nsaid", False),
    "bleed_disorder": st.session_state.get("bleed_disorder", False),
    "bleed_ckd": st.session_state.get("bleed_ckd", False),
    "bmi": float(bmi) if bmi > 0 else None,
    "egfr": float(egfr) if egfr > 0 else None,
    "lipid_lowering": (lipid_lowering == "Yes"),
}

data = {k: v for k, v in data.items() if v is not None}
patient = Patient(data)  # <-- Make sure this line exists and is NOT indented under an if
out = evaluate(patient)

# Quick text for debug
note_text = scrub_terms(render_quick_text(patient, out))  # <-- Now patient is defined
lvl = out.get("levels", {}) or {}
ev = lvl.get("evidence", {}) if isinstance(lvl.get("evidence"), dict) else {}
rs = out.get("riskSignal", {}) or {}
risk10 = out.get("pooledCohortEquations10yAscvdRisk", {}) or {}
prevent10 = out.get("prevent10", {}) or {}
asp = out.get("aspirin", {}) or {}
ins = out.get("insights", {}) or {}

level = int(lvl.get("managementLevel") or lvl.get("postureLevel") or lvl.get("level") or 1)
level = max(1, min(5, level))
sub = lvl.get("sublevel")
legend = lvl.get("legend") or FALLBACK_LEVEL_LEGEND

decision_conf = scrub_terms(lvl.get("decisionConfidence") or "—")

plan_raw = str(lvl.get("defaultPosture") or "")
plan_clean = re.sub(r"^\s*(Recommended:|Consider:|Pending more data:)\s*", "", plan_raw).strip()
plan_clean = scrub_terms(plan_clean)

next_actions = scrub_list(out.get("nextActions", []) or [])
drivers = scrub_list(out.get("drivers", []) or [])

t_pick = pick_dual_targets_ldl_first(out, data)
primary = t_pick["primary"]
apob_line = t_pick["secondary"]
apob_measured = t_pick["apob_measured"]
clinical_ascvd = bool(ev.get("clinical_ascvd"))

pce_line = f"{risk10.get('risk_pct')}%" if risk10.get("risk_pct") is not None else "—"
pce_cat = risk10.get("category") or ""
p_total = prevent10.get("total_cvd_10y_pct")
p_ascvd = prevent10.get("ascvd_10y_pct")
p_note = scrub_terms(prevent10.get("notes", ""))
asp_status = scrub_terms(asp.get("status", "Not assessed"))

anchors = out.get("anchors", {}) or {}
near_anchor = scrub_terms(anchors.get("nearTerm", {}).get("summary", "—"))
life_anchor = scrub_terms(anchors.get("lifetime", {}).get("summary", "—"))

# Show timestamp
if submitted:
    st.caption(f"Last calculation: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ============================================================
# Build EMR note
# ============================================================
def build_emr_note() -> str:
    lines = []
    lines.append("RISK CONTINUUM — CLINICAL REPORT")
    lines.append("-" * 64)
    lines.append(f"Level: {level}" + (f" ({sub})" if sub else "") + f" — {LEVEL_NAMES.get(level,'—')}")
    lines.append(f"Evidence: {scrub_terms(ev.get('cac_status','—'))} / Burden: {scrub_terms(ev.get('burden_band','—'))}")
    lines.append(f"Decision confidence: {decision_conf}")
    if ins.get("decision_robustness"):
        rob = scrub_terms(ins.get("decision_robustness"))
        rob_note = scrub_terms(ins.get("decision_robustness_note", ""))
        lines.append(f"Decision robustness: {rob}" + (f" — {rob_note}" if rob_note else ""))
    lines.append("")
    lines.append("KEY METRICS")
    lines.append(f"- RSS: {rs.get('score','—')}/100 ({rs.get('band','—')})")
    lines.append(f"- PCE 10y ASCVD: {pce_line} {pce_cat}".strip())
    lines.append(f"- PREVENT 10y: total CVD {p_total if p_total is not None else '—'}; ASCVD {p_ascvd if p_ascvd is not None else '—'}")
    if (p_total is None and p_ascvd is None) and p_note:
        lines.append(f" PREVENT note: {p_note}")
    lines.append("")
    lines.append("TARGETS")
    if primary:
        tgt = f"- {primary[0]} {primary[1]}"
        if apob_line:
            tgt += f"; {apob_line[0]} {apob_line[1]}"
        lines.append(tgt)
    else:
        lines.append("- —")
    lines.append("")
    lines.append("PLAN & ACTIONS")
    lines.append(f"- Plan: {plan_clean or '—'}")
    if next_actions:
        lines.append("- Next steps:")
        for a in next_actions[:3]:
            lines.append(f" • {a}")
    else:
        lines.append("- Next steps: —")
    lines.append(f"- Aspirin: {asp_status}")
    if ins.get("structural_clarification"):
        lines.append(f"- {scrub_terms(ins.get('structural_clarification'))}")
    lines.append("")
    lines.append("CLINICAL CONTEXT")
    if drivers:
        lines.append(f"- Risk driver: {drivers[0]}")
    if ins.get("phenotype_label"):
        lines.append(f"- Phenotype: {scrub_terms(ins.get('phenotype_label'))}")
    if ins.get("decision_robustness"):
        rob = scrub_terms(ins.get("decision_robustness"))
        rob_note = scrub_terms(ins.get("decision_robustness_note", ""))
        lines.append(f"Decision robustness: {rob}" + (f" — {rob_note}" if rob_note else ""))
    if ev.get("cac_status") == "Unknown":
        lines.append("- Structural status: Unknown (CAC not performed)")
    lines.append(f"- Anchors: Near-term: {near_anchor} | Lifetime: {life_anchor}")
    lines.append("")
    return "\n".join(lines)

emr_note = build_emr_note()

# ============================================================
# Tabs
# ============================================================
tab_report, tab_details, tab_debug = st.tabs(["Report", "Details", "Debug"])

with tab_report:
    st.markdown(render_risk_continuum_bar(level, sub), unsafe_allow_html=True)

    st.markdown(
        f"""
<div class="block">
  <div class="block-title">Snapshot</div>
  <div class="kvline"><b>Level:</b> {level}{f" ({sub})" if sub else ""} — {LEVEL_NAMES.get(level,'—')}</div>
  <div class="kvline"><b>Evidence:</b> {scrub_terms(ev.get('cac_status','—'))} / <b>Burden:</b> {scrub_terms(ev.get('burden_band','—'))}</div>
  <div class="kvline"><b>Decision confidence:</b> {decision_conf}</div>
  <div class="kvline"><b>Key metrics:</b> RSS {rs.get('score','—')}/100 ({rs.get('band','—')}) • PCE 10y {pce_line} {pce_cat}</div>
  <div class="kvline"><b>PREVENT 10y:</b> total CVD {p_total if p_total is not None else '—'} • ASCVD {p_ascvd if p_ascvd is not None else '—'}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    if (p_total is None and p_ascvd is None) and p_note:
        st.caption(f"PREVENT not calculated yet (coefficients pending implementation). Using PCE only for now.")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    st.markdown('<div class="block"><div class="block-title">Targets</div>', unsafe_allow_html=True)
    if primary:
        lipid_targets_line = f"{primary[0]} {primary[1]}"
        if apob_line:
            lipid_targets_line += f" • {apob_line[0]} {apob_line[1]}"
        st.markdown(f"<div class='kvline'><b>Lipid targets:</b> {lipid_targets_line}</div>", unsafe_allow_html=True)
        st.caption(guideline_anchor_note(level, clinical_ascvd))
        if apob_line and not apob_measured:
            st.caption("ApoB not measured here — optional add-on to check for discordance.")
    else:
        st.markdown("<div class='kvline'><b>Lipid targets:</b> —</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    st.markdown('<div class="block"><div class="block-title">Plan & actions</div></div>', unsafe_allow_html=True)
    st.markdown(f"**Plan:** {plan_clean or '—'}")
    if next_actions:
        st.markdown("**Next steps:**")
        for a in next_actions[:3]:
            st.markdown(f"- {a}")
    else:
        st.markdown("**Next steps:** —")
    st.markdown(f"**Aspirin:** {asp_status}")
    if ins.get("structural_clarification"):
        st.caption(scrub_terms(ins.get("structural_clarification")))

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    st.markdown('<div class="block"><div class="block-title">Clinical context</div></div>', unsafe_allow_html=True)
    if drivers:
        st.markdown(f"**Risk driver:** {drivers[0]}")
    if ins.get("phenotype_label"):
        st.markdown(f"**Phenotype:** {scrub_terms(ins.get('phenotype_label'))}")
    if ins.get("decision_robustness"):
        rob = scrub_terms(ins.get("decision_robustness"))
        rob_note = scrub_terms(ins.get("decision_robustness_note", ""))
        st.markdown(f"**Decision robustness:** {rob}" + (f" — {rob_note}" if rob_note else ""))
    if ev.get("cac_status") == "Unknown":
        st.markdown("**Structural status:** Unknown (CAC not performed)")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    st.markdown("### Clinical Report (copy/paste into EMR)")
    st.caption("Click **Copy**. Then paste into your EMR note.")
    emr_copy_box("Clinical Report (EMR paste)", emr_note, height_px=520)

    # Download button
    st.download_button(
        label="Download Report (Markdown)",
        data=emr_note,
        file_name="Risk_Continuum_Report.md",
        mime="text/markdown"
    )

with tab_details:
    st.subheader("Anchors (near-term vs lifetime)")
    st.markdown(f"**Near-term anchor:** {near_anchor}")
    st.markdown(f"**Lifetime anchor:** {life_anchor}")
    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    st.subheader("Aspirin (detail)")
    asp_why = scrub_terms(short_why(asp.get("rationale", []), max_items=5))
    st.write(f"**{asp_status}**" + (f" — **Why:** {asp_why}" if asp_why else ""))
    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    st.subheader("PREVENT (details)")
    if p_total is not None or p_ascvd is not None:
        st.markdown(f"**10-year total CVD:** {p_total}%")
        st.markdown(f"**10-year ASCVD:** {p_ascvd}%")
    else:
        st.caption(p_note or "PREVENT not calculated (coefficients pending).")
    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    with st.expander("High-yield narrative (optional)", expanded=False):
        st.markdown(render_high_yield_report(out), unsafe_allow_html=True)

    with st.expander("How Levels work (legend)", expanded=False):
        for item in (lvl.get("legend") or FALLBACK_LEVEL_LEGEND):
            st.write(f"• {scrub_terms(item)}")

with tab_debug:
    st.subheader("Engine quick output (raw text)")
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


