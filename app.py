# app.py (Risk Continuum — v2.8 clinician-clean layout)
#
# FULL, UPDATED VERSION (no "Overview" tab)
# - Tabs: Report | Details | Debug
# - SmartPhrase ingest: Parse & Apply (inline, no callbacks/ordering bugs)
# - Parse & Apply is robust:
#     • Resets CAC when not done/missing (prevents carryover)
#     • Uses parser outputs: sbp, diabetes, fhx_text, cac_not_done
#     • Avoids diabetes false-positives (no negation-guard fallback)
# - Imaging block moved OUTSIDE the form so CAC enable/disable is live
# - Engine caching (5 min TTL) via data_json key (safe + deterministic)
# - Last calculation timestamp
# - Aspirin shows "status — explanation" (engine provides asp["explanation"])
# - Polished Clinical Report Box with a real COPY button (no downloads)
# - PREVENT always visible, labeled explicitly as "population model"
# - Adds a short PREVENT explainer: values are 10-year risk percentages from a population model
#
# Requirements:
# - smartphrase_ingest.parser.parse_smartphrase returns keys like:
#     age, sex, sbp, tc, hdl, ldl, apob, lpa, lpa_unit, a1c,
#     smoker, diabetes, bpTreated, africanAmerican,
#     bmi, egfr, lipidLowering,
#     fhx_text, cac_not_done, (optional) cac
#
# NOTE: Use spaces (4) for indentation. Avoid tabs.

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

PREVENT_EXPLAINER = (
    "**PREVENT is a population event-risk estimate (10-year probability, in %).** "
    "“Total CVD” includes ASCVD **plus** other major cardiovascular outcomes (e.g., heart failure). "
    "It does **not** measure plaque; use CAC/ApoB/Lp(a) to refine biologic/structural risk."
)

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
# Polished EMR Copy Box (Copy button)
# ============================================================
def emr_copy_box(title: str, text: str, height_px: int = 520):
    uid = uuid.uuid4().hex[:10]
    safe_text = _html.escape(text or "")
    title_safe = _html.escape(title or "Clinical Report")

    components.html(
        f"""
<div style="border:1px solid rgba(31,41,55,0.12); border-radius:14px; padding:14px; background:#ffffff;">
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
    height:{max(240, height_px - 90)}px;
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
  const ta  = document.getElementById("noteText_{uid}");
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
# Parse & Apply wiring
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
    ("cac_not_done", "CAC not done flag"),
    ("fhx_text", "Family history"),
    ("a1c", "A1c"),
    ("ascvd_10y", "ASCVD 10-year risk (if present)"),
    ("bmi", "BMI (PREVENT)"),
    ("egfr", "eGFR (PREVENT)"),
    ("lipidLowering", "Lipid-lowering therapy (PREVENT)"),
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

    if parsed.get("smoker") is not None:
        st.session_state["smoking_val"] = "Yes" if bool(parsed["smoker"]) else "No"
        applied.append("Smoking")

    if parsed.get("diabetes") is not None:
        st.session_state["diabetes_choice_val"] = "Yes" if bool(parsed["diabetes"]) else "No"
        applied.append("Diabetes")
    else:
        missing.append("Diabetes")

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

    fhx_txt = parsed.get("fhx_text")
    if fhx_txt:
        st.session_state["fhx_choice_val"] = fhx_txt
        applied.append("Premature family history")
    else:
        missing.append("Premature family history")

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

    missing = list(dict.fromkeys(missing))
    return applied, missing

# ============================================================
# Session defaults + demo controls
# ============================================================
def reset_fields():
    defaults = {
        "age_val": 0,
        "sex_val": "F",
        "race_val": "Other (use non-African American coefficients)",
        "ascvd_val": "No",
        "fhx_choice_val": "None / Unknown",
        "sbp_val": 0,
        "bp_treated_val": "No",
        "smoking_val": "No",
        "diabetes_choice_val": "No",
        "a1c_val": 0.0,
        "tc_val": 0,
        "ldl_val": 0,
        "hdl_val": 0,
        "apob_val": 0,
        "lpa_val": 0,
        "lpa_unit_val": "nmol/L",
        "hscrp_val": 0.0,
        "cac_known_val": "No",
        "cac_val": 0,
        "bmi_val": 0.0,
        "egfr_val": 0.0,
        "lipid_lowering_val": "No",
        "demo_defaults_applied": False,
        "last_applied_msg": "",
        "last_missing_msg": "",
        "parsed_preview_cache": {},
        "smartphrase_raw": "",
    }
    for k, v in defaults.items():
        st.session_state[k] = v

    for kk in ["ra", "psoriasis", "sle", "ibd", "hiv", "osa", "nafld"]:
        st.session_state[f"infl_{kk}_val"] = False

    for bk in ["bleed_gi", "bleed_nsaid", "bleed_anticoag", "bleed_disorder", "bleed_ich", "bleed_ckd"]:
        st.session_state[bk] = False

def apply_demo_defaults():
    st.session_state.update({
        "age_val": 55,
        "sex_val": "M",
        "race_val": "Other (use non-African American coefficients)",
        "ascvd_val": "No",
        "fhx_choice_val": "Father with premature ASCVD (MI/stroke/PCI/CABG/PAD) <55",
        "sbp_val": 128,
        "bp_treated_val": "No",
        "smoking_val": "No",
        "diabetes_choice_val": "No",
        "tc_val": 190,
        "hdl_val": 50,
        "ldl_val": 115,
        "apob_val": 92,
        "lpa_val": 90,
        "lpa_unit_val": "nmol/L",
        "a1c_val": 5.8,
        "hscrp_val": 1.2,
        "cac_known_val": "No",
        "cac_val": 0,
        "bmi_val": 28.0,
        "egfr_val": 85.0,
        "lipid_lowering_val": "No",
        "demo_defaults_applied": True,
    })
    for kk in ["ra", "psoriasis", "sle", "ibd", "hiv", "osa", "nafld"]:
        st.session_state[f"infl_{kk}_val"] = False

for key, default in [
    ("age_val", 0),
    ("sex_val", "F"),
    ("race_val", "Other (use non-African American coefficients)"),
    ("ascvd_val", "No"),
    ("fhx_choice_val", "None / Unknown"),
    ("sbp_val", 0),
    ("bp_treated_val", "No"),
    ("smoking_val", "No"),
    ("diabetes_choice_val", "No"),
    ("a1c_val", 0.0),
    ("tc_val", 0),
    ("ldl_val", 0),
    ("hdl_val", 0),
    ("apob_val", 0),
    ("lpa_val", 0),
    ("lpa_unit_val", "nmol/L"),
    ("hscrp_val", 0.0),
    ("cac_known_val", "No"),
    ("cac_val", 0),
    ("bmi_val", 0.0),
    ("egfr_val", 0.0),
    ("lipid_lowering_val", "No"),
    ("smartphrase_raw", ""),
    ("parsed_preview_cache", {}),
    ("last_applied_msg", ""),
    ("last_missing_msg", ""),
    ("demo_defaults_on", True),
    ("demo_defaults_applied", False),
]:
    st.session_state.setdefault(key, default)

for k in ["ra", "psoriasis", "sle", "ibd", "hiv", "osa", "nafld"]:
    st.session_state.setdefault(f"infl_{k}_val", False)
for bk in ["bleed_gi", "bleed_nsaid", "bleed_anticoag", "bleed_disorder", "bleed_ich", "bleed_ckd"]:
    st.session_state.setdefault(bk, False)

with st.sidebar:
    st.markdown("### Demo")
    st.session_state["demo_defaults_on"] = st.checkbox(
        "Use demo defaults (auto-fill)",
        value=st.session_state["demo_defaults_on"],
    )

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
# SmartPhrase ingest
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
                st.warning("No text to parse — paste something first.")
            else:
                parsed = parse_smartphrase(raw_txt)
                st.session_state["parsed_preview_cache"] = parsed

                applied, missing = apply_parsed_to_session(parsed, raw_txt)
                st.session_state["last_applied_msg"] = "Applied: " + (", ".join(applied) if applied else "None")
                st.session_state["last_missing_msg"] = "Missing/unparsed: " + (", ".join(missing) if missing else "All good!")
                st.rerun()

    with c2:
        if st.button("Clear pasted text"):
            st.session_state["smartphrase_raw"] = ""
            st.session_state["parsed_preview_cache"] = {}
            st.session_state["last_applied_msg"] = ""
            st.session_state["last_missing_msg"] = ""
            st.rerun()

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
# Imaging (OUTSIDE the form so enable/disable is live)
# ============================================================
st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
st.subheader("Imaging")

d1, d2 = st.columns([1, 2])
with d1:
    st.radio(
        "Calcium score available?",
        ["Yes", "No"],
        horizontal=True,
        key="cac_known_val",
    )

with d2:
    st.number_input(
        "Calcium score (Agatston)",
        min_value=0,
        max_value=5000,
        step=1,
        key="cac_val",
        disabled=(st.session_state.get("cac_known_val", "No") == "No"),
        help="Enable by setting 'Calcium score available?' to Yes. If No, the engine ignores the value.",
    )

# ============================================================
# Main form
# ============================================================
with st.form("risk_continuum_form"):
    st.subheader("Patient context")

    a1, a2, a3 = st.columns(3)
    with a1:
        st.number_input("Age (years)", 18, 120, step=1, key="age_val")
        st.radio("Gender", ["F", "M"], horizontal=True, key="sex_val")
    with a2:
        st.radio(
            "Race (calculator)",
            ["Other (use non-African American coefficients)", "African American"],
            horizontal=False,
            key="race_val",
        )
    with a3:
        st.radio("ASCVD (clinical)", ["No", "Yes"], horizontal=True, key="ascvd_val")

    st.selectbox("Premature family history", FHX_OPTIONS, index=0, key="fhx_choice_val")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Cardiometabolic profile")

    b1, b2, b3 = st.columns(3)
    with b1:
        st.number_input("Systolic BP (mmHg)", 50, 300, step=1, key="sbp_val")
        st.radio("On BP meds?", ["No", "Yes"], horizontal=True, key="bp_treated_val")
    with b2:
        st.radio("Smoking (current)", ["No", "Yes"], horizontal=True, key="smoking_val")
        st.radio("Diabetes (manual)", ["No", "Yes"], horizontal=True, key="diabetes_choice_val")
    with b3:
        a1c = st.number_input("A1c (%)", 0.0, 15.0, step=0.1, format="%.1f", key="a1c_val")
        if a1c >= 6.5:
            st.info("A1c ≥ 6.5% ⇒ Diabetes will be set to YES automatically.")

    b4, b5, b6 = st.columns(3)
    with b4:
        st.number_input("BMI (kg/m²) (for PREVENT)", 0.0, 80.0, step=0.1, format="%.1f", key="bmi_val")
    with b5:
        st.radio("On lipid-lowering therapy? (for PREVENT)", ["No", "Yes"], horizontal=True, key="lipid_lowering_val")
    with b6:
        st.caption("PREVENT requires eGFR and lipid-therapy status. (Population model output is a %.)")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Labs")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.number_input("Total cholesterol (mg/dL)", 0, 500, step=1, key="tc_val")
        st.number_input("LDL-C (mg/dL)", 0, 400, step=1, key="ldl_val")
        st.number_input("HDL cholesterol (mg/dL)", 0, 300, step=1, key="hdl_val")
    with c2:
        st.number_input("ApoB (mg/dL)", 0, 300, step=1, key="apob_val")
        st.number_input("Lp(a) value", 0, 2000, step=1, key="lpa_val")
        st.radio("Lp(a) unit", ["nmol/L", "mg/dL"], horizontal=True, key="lpa_unit_val")
    with c3:
        st.number_input("hsCRP (mg/L) (optional)", 0.0, 50.0, step=0.1, format="%.1f", key="hscrp_val")
        st.number_input("eGFR (mL/min/1.73m²) (for PREVENT)", 0.0, 200.0, step=1.0, format="%.0f", key="egfr_val")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("PREVENT extras (optional)")

    p1, p2 = st.columns(2)
    with p1:
        st.number_input(
            "Urine albumin-to-creatinine ratio (UACR, mg/g)",
            min_value=0.0,
            max_value=10000.0,
            step=1.0,
            format="%.0f",
            key="uacr_val",
            help="Optional PREVENT input. Leave 0 if not available.",
        )
    with p2:
        st.number_input(
            "Social Deprivation Index (SDI) decile (1–10)",
            min_value=0,
            max_value=10,
            step=1,
            key="sdi_decile_val",
            help="Optional PREVENT input. Use decile 1–10; leave 0 if not available.",
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
# Cached engine call
# ============================================================
@st.cache_data(ttl=300)
def run_engine(data_json: str):
    data = json.loads(data_json)
    patient = Patient(data)
    return evaluate(patient)

# ============================================================
# Run
# ============================================================
if not submitted:
    st.caption("Enter values (or use Demo defaults) and click Run.")
    st.stop()

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

# Gentle hint for PREVENT (population model) calculation
if st.session_state.get("egfr_val", 0) <= 0:
    st.warning("PREVENT (population model) needs eGFR > 0 to calculate. Enter eGFR to enable PREVENT output.")

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
    "age": int(age),
    "sex": sex,
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
    "ra": bool(st.session_state.get("infl_ra_val", False)),
    "psoriasis": bool(st.session_state.get("infl_psoriasis_val", False)),
    "sle": bool(st.session_state.get("infl_sle_val", False)),
    "ibd": bool(st.session_state.get("infl_ibd_val", False)),
    "hiv": bool(st.session_state.get("infl_hiv_val", False)),
    "osa": bool(st.session_state.get("infl_osa_val", False)),
    "nafld": bool(st.session_state.get("infl_nafld_val", False)),
    "bleed_gi": bool(st.session_state.get("bleed_gi", False)),
    "bleed_ich": bool(st.session_state.get("bleed_ich", False)),
    "bleed_anticoag": bool(st.session_state.get("bleed_anticoag", False)),
    "bleed_nsaid": bool(st.session_state.get("bleed_nsaid", False)),
    "bleed_disorder": bool(st.session_state.get("bleed_disorder", False)),
    "bleed_ckd": bool(st.session_state.get("bleed_ckd", False)),
    "bmi": float(bmi) if bmi and bmi > 0 else None,
    "egfr": float(egfr) if egfr and egfr > 0 else None,
    "lipid_lowering": (lipid_lowering == "Yes"),
    "uacr": float(st.session_state.get("uacr_val", 0)) if st.session_state.get("uacr_val", 0) > 0 else None,
    "sdi_decile": int(st.session_state.get("sdi_decile_val", 0)) if 1 <= int(st.session_state.get("sdi_decile_val", 0) or 0) <= 10 else None,
}
data = {k: v for k, v in data.items() if v is not None}

data_json = json.dumps(data, sort_keys=True)
out = run_engine(data_json)
patient = Patient(data)

note_text = scrub_terms(render_quick_text(patient, out))

lvl = out.get("levels", {}) or {}
ev = (lvl.get("evidence") or {}) if isinstance(lvl.get("evidence"), dict) else {}
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
clinical_ascvd = bool(ev.get("clinical_ascvd")) if isinstance(ev, dict) else False

pce_line = f"{risk10.get('risk_pct')}%" if risk10.get("risk_pct") is not None else "—"
pce_cat = risk10.get("category") or ""

p_total = prevent10.get("total_cvd_10y_pct")
p_ascvd = prevent10.get("ascvd_10y_pct")
p_note = scrub_terms(prevent10.get("notes", ""))

asp_status = scrub_terms(asp.get("status", "Not assessed"))
asp_expl = scrub_terms(asp.get("explanation", ""))

anchors = out.get("anchors", {}) or {}
near_anchor = scrub_terms((anchors.get("nearTerm") or {}).get("summary", "—"))
life_anchor = scrub_terms((anchors.get("lifetime") or {}).get("summary", "—"))

st.caption(f"Last calculation: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ============================================================
# EMR Note text (for copy box)
# ============================================================
PREVENT_EXPLAINER = "(PREVENT estimates 10-year population event risk (%); total CVD includes ASCVD + heart failure and complements plaque/biology-based risk assessment.)"



def build_emr_note() -> str:
    lines = []

    lines.append("RISK CONTINUUM — CLINICAL REPORT")
    lines.append("-" * 64)

    lines.append(
        f"Level: {level}"
        + (f" ({sub})" if sub else "")
        + f" — {LEVEL_NAMES.get(level,'—')}"
    )

    lines.append(
        f"Evidence: {scrub_terms(ev.get('cac_status','—'))} / "
        f"Burden: {scrub_terms(ev.get('burden_band','—'))}"
    )

    lines.append(f"Decision confidence: {decision_conf}")

    if ins.get("decision_robustness"):
        rob = scrub_terms(ins.get("decision_robustness"))
        rob_note = scrub_terms(ins.get("decision_robustness_note", ""))
        if rob_note:
            lines.append(f"Decision robustness: {rob} — {rob_note}")
        else:
            lines.append(f"Decision robustness: {rob}")

    # --------------------------------------------------------
    lines.append("")
    lines.append("KEY METRICS")

    lines.append(
        f"- RSS: {rs.get('score','—')}/100 ({rs.get('band','—')})"
    )

    lines.append(
        f"- PCE 10y ASCVD: {pce_line} {pce_cat}".strip()
    )

    lines.append(
        f"- PREVENT (population model) 10y: "
        f"total CVD {p_total if p_total is not None else '—'}%; "
        f"ASCVD {p_ascvd if p_ascvd is not None else '—'}%"
    )

    if (p_total is None and p_ascvd is None) and p_note:
        lines.append(f"  PREVENT note: {p_note}")

    lines.append(f"  {PREVENT_EXPLAINER}")

    # --------------------------------------------------------
    lines.append("")
    lines.append("TARGETS")

    if primary:
        tgt = f"- {primary[0]} {primary[1]}"
        if apob_line:
            tgt += f"; {apob_line[0]} {apob_line[1]}"
        lines.append(tgt)
    else:
        lines.append("- —")

    # --------------------------------------------------------
    lines.append("")
    lines.append("PLAN & ACTIONS")

    lines.append(f"- Plan: {plan_clean or '—'}")

    if next_actions:
        lines.append("- Next steps:")
        for a in next_actions[:3]:
            lines.append(f"  • {a}")
    else:
        lines.append("- Next steps: —")

    if asp_expl:
        lines.append(f"- Aspirin: {asp_status} — {asp_expl}")
    else:
        lines.append(f"- Aspirin: {asp_status}")

    if ins.get("structural_clarification"):
        lines.append(f"- {scrub_terms(ins.get('structural_clarification'))}")

    # --------------------------------------------------------
    lines.append("")
    lines.append("CLINICAL CONTEXT")

    if drivers:
        lines.append(f"- Risk driver: {drivers[0]}")

    if ins.get("phenotype_label"):
        lines.append(f"- Phenotype: {scrub_terms(ins.get('phenotype_label'))}")

    if ev.get("cac_status") == "Unknown":
        lines.append("- Structural status: Unknown (CAC not performed)")

    lines.append(
        f"- Anchors: Near-term: {near_anchor} | Lifetime: {life_anchor}"
    )

    lines.append("")
    return "\n".join(lines)


# ============================================================
# Tabs
# ============================================================
tab_report, tab_details, tab_debug = st.tabs(["Report", "Details", "Debug"])

# ----------------------------
# REPORT TAB
# ----------------------------
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
  <div class="kvline"><b>PREVENT (population model) 10y:</b> total CVD {p_total if p_total is not None else '—'} • ASCVD {p_ascvd if p_ascvd is not None else '—'}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.caption(PREVENT_EXPLAINER)
    if (p_total is None and p_ascvd is None) and p_note:
        st.caption(f"PREVENT (population model): {p_note}")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    # Targets
    st.markdown('<div class="block"><div class="block-title">Targets</div>', unsafe_allow_html=True)
    if primary:
        lipid_targets_line = f"{primary[0]} {primary[1]}"
        if apob_line:
            lipid_targets_line += f" • {apob_line[0]} {apob_line[1]}"
        st.markdown(
            f"<div class='kvline'><b>Lipid targets:</b> {lipid_targets_line}</div>",
            unsafe_allow_html=True,
        )
        st.caption(guideline_anchor_note(level, clinical_ascvd))
        if apob_line and not apob_measured:
            st.caption("ApoB not measured here — optional add-on to check for discordance.")
    else:
        st.markdown("<div class='kvline'><b>Lipid targets:</b> —</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    # Plan & actions
    st.markdown('<div class="block"><div class="block-title">Plan & actions</div></div>', unsafe_allow_html=True)
    st.markdown(f"**Plan:** {plan_clean or '—'}")

    if next_actions:
        st.markdown("**Next steps:**")
        for a in next_actions[:3]:
            st.markdown(f"- {a}")
    else:
        st.markdown("**Next steps:** —")

    if asp_expl:
        st.markdown(f"**Aspirin:** {asp_status} — {asp_expl}")
    else:
        st.markdown(f"**Aspirin:** {asp_status}")

    if ins.get("structural_clarification"):
        st.caption(scrub_terms(ins.get("structural_clarification")))

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    # Clinical context
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

    # ----------------------------
    # EMR COPY BOX (MUST BE INSIDE tab_report)
    # ----------------------------
    st.markdown("### Clinical Report (copy/paste into EMR)")
    st.caption("Click **Copy**, then paste into the EMR note.")
    emr_copy_box("Clinical Report (EMR paste)", build_emr_note(), height_px=560)

# ----------------------------
# DETAILS TAB
# ----------------------------
with tab_details:
    st.subheader("Anchors (near-term vs lifetime)")
    st.markdown(f"**Near-term anchor:** {near_anchor}")
    st.markdown(f"**Lifetime anchor:** {life_anchor}")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    st.subheader("Aspirin (detail)")
    asp_why = scrub_terms(short_why(asp.get("rationale", []), max_items=5))
    if asp_expl:
        st.write(f"**{asp_status}** — {asp_expl}" + (f" **Why (bullets):** {asp_why}" if asp_why else ""))
    else:
        st.write(f"**{asp_status}**" + (f" — **Why:** {asp_why}" if asp_why else ""))

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    st.subheader("PREVENT (population model) — details")
    st.caption(PREVENT_EXPLAINER)
    if p_total is not None or p_ascvd is not None:
        st.markdown(f"**10-year total CVD:** {p_total}%")
        st.markdown(f"**10-year ASCVD:** {p_ascvd}%")
    else:
        st.caption(p_note or "PREVENT not calculated.")

    with st.expander("How Levels work (legend)", expanded=False):
        for item in legend:
            st.write(f"• {scrub_terms(item)}")

# ----------------------------
# DEBUG TAB
# ----------------------------
with tab_debug:
    st.subheader("Engine quick output (raw text)")
    st.code(note_text, language="text")

    st.subheader("Trace (audit trail)")
    st.json(out.get("trace", []))

    if show_json:
        st.subheader("JSON (debug)")
        st.json(out)

st.caption(
    f"Versions: {VERSION.get('levels','')} | {VERSION.get('riskSignal','')} | "
    f"{VERSION.get('riskCalc','')} | {VERSION.get('aspirin','')} | "
    f"{VERSION.get('prevent','')}. No storage intended."
)









