# app.py (Risk Continuum — v2.8 clinician-clean layout)
# FULL, UPDATED VERSION (no "Overview" tab)
#
# Tabs: Report | Decision Framework | Details | Debug
# SmartPhrase ingest: Parse & Apply (inline)
# Imaging moved OUTSIDE form so CAC enable/disable is live
# Polished EMR copy box with COPY button (no downloads)
# PREVENT always visible, labeled explicitly as population model, shown with % everywhere
# PREVENT extras: UACR + SDI decile (optional)

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
from levels_engine import Patient, VERSION, short_why
from levels_output_adapter import evaluate_unified


# ============================================================
# Guardrails + scrubbing (must be defined before first use)
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
    return any(re.search(pat, s, re.IGNORECASE) for pat in PHI_PATTERNS)

def scrub_terms(s: str) -> str:
    if not s:
        return s
    s = re.sub(r"\brisk\s+drift\b", "Emerging risk", s, flags=re.IGNORECASE)
    s = re.sub(r"\bdrift\b", "Emerging risk", s, flags=re.IGNORECASE)
    s = re.sub(r"\bposture\b", "level", s, flags=re.IGNORECASE)
    s = re.sub(r"\brobustness\b", "stability", s, flags=re.IGNORECASE)
    return s

def scrub_list(xs):
    if not xs:
        return xs
    return [scrub_terms(str(x)) for x in xs]

get_level_definition_payload = getattr(le, "get_level_definition_payload", None)

def safe_level_def(level_num: int, sublevel: str | None = None) -> dict:
    fn = get_level_definition_payload
    if not callable(fn):
        return {}
    try:
        return fn(level_num, sublevel=sublevel)
    except TypeError:
        # if engine uses a different signature
        try:
            return fn(level_num, sublevel)
        except Exception:
            return {}
    except Exception:
        return {}


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

# ✅ One definition only
PREVENT_EXPLAINER = (
    "PREVENT estimates 10-year population event risk (%); total CVD includes ASCVD plus heart failure "
    "and complements plaque/biology-based risk assessment."
)
# ============================================================
# Page + styling
# ============================================================
st.set_page_config(page_title="Risk Continuum", layout="wide")

st.markdown(
    """
<style>

/* ============================================================
   THEME TOKENS (single source of truth)
   ============================================================ */
:root{
  --rc-text: #111827;
  --rc-muted: rgba(17,24,39,0.62);
  --rc-muted2: rgba(17,24,39,0.48);
  --rc-line: rgba(31,41,55,0.12);
  --rc-line-strong: rgba(31,41,55,0.18);
  --rc-surface: #ffffff;
  --rc-surface2: #fbfbfc;
  --rc-bg: #f6f7fb;

  --rc-radius-lg: 16px;
  --rc-radius-md: 12px;

  --rc-shadow: 0 10px 30px rgba(0,0,0,0.06);
  --rc-shadow2: 0 8px 22px rgba(0,0,0,0.08);

  /* Accent used sparingly (chips/underline) */
  --rc-accent: rgba(59,130,246,0.85);
  --rc-accent-bg: rgba(59,130,246,0.08);
}

/* ============================================================
   BASE TYPOGRAPHY (SAFE)
   ============================================================ */
html, body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter,
               "Helvetica Neue", Arial, sans-serif;
  color: var(--rc-text);
  background: var(--rc-bg);
}

/* Apply font to app root only (DO NOT use .stApp *) */
.stApp {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter,
               "Helvetica Neue", Arial, sans-serif;
  color: var(--rc-text);
  background: var(--rc-bg);
}

/* Apply font only to safe text elements (NO div/span) */
.stApp :is(
  p, label, li, ul, ol,
  h1, h2, h3, h4, h5, h6
) {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter,
               "Helvetica Neue", Arial, sans-serif;
  color: var(--rc-text);
}

/* Preserve Material icon fonts explicitly */
.material-icons,
.material-symbols-outlined,
[class*="material-icons"],
[class*="material-symbols"] {
  font-family: "Material Icons", "Material Symbols Outlined", sans-serif !important;
}

/* ============================================================
   HEADING SCALE (readable, clinician-grade)
   ============================================================ */
.stApp h2 { /* st.subheader */
  font-size: 1.28rem;
  font-weight: 950;
  letter-spacing: -0.012em;
  margin: 0.85rem 0 0.40rem 0;
}
.stApp h3 { /* markdown ### */
  font-size: 1.08rem;
  font-weight: 900;
  letter-spacing: -0.006em;
  margin: 0.60rem 0 0.30rem 0;
}

/* ============================================================
   LAYOUT + SPACING
   ============================================================ */
.block-container {
  padding-top: 2.35rem;
  padding-bottom: 1.0rem;
}

/* Streamlit vertical block spacing */
div[data-testid="stVerticalBlock"] {
  gap: 0.70rem;
}

div[data-testid="stMarkdownContainer"] p { margin: 0.28rem 0; }
div[data-testid="stMarkdownContainer"] ul { margin: 0.28rem 0 0.28rem 1.1rem; }
div[data-testid="stMarkdownContainer"] li { margin: 0.10rem 0; }

.hr {
  margin: 12px 0;
  border-top: 1px solid var(--rc-line);
}

/* ============================================================
   HEADER CARD
   ============================================================ */
.header-card {
  background: linear-gradient(180deg, var(--rc-surface) 0%, var(--rc-surface2) 100%);
  border: 1px solid var(--rc-line);
  border-radius: var(--rc-radius-lg);
  padding: 18px 20px;
  margin-bottom: 12px;
  box-shadow: var(--rc-shadow);
}

.header-title {
  font-size: 1.50rem;
  font-weight: 975;
  letter-spacing: -0.018em;
  margin: 0 0 6px 0;
}

.header-sub {
  color: var(--rc-muted);
  font-size: 0.95rem;
  margin: 0;
}

/* ============================================================
   CARDS / BLOCKS
   ============================================================ */
.block {
  border: 1px solid var(--rc-line);
  border-radius: var(--rc-radius-lg);
  background: var(--rc-surface);
  padding: 14px 16px;
  font-size: 0.95rem;
  line-height: 1.38;
  box-shadow: var(--rc-shadow);
}

.block + .block { margin-top: 10px; }

/* ============================================================
   PRIMARY SECTION TITLES (Snapshot, Action, Targets, etc.)
   ============================================================ */
.block-title {
  font-variant-caps: all-small-caps;
  letter-spacing: 0.14em;
  font-weight: 975;
  font-size: 1.18rem;            /* ⬆️ bigger */
  color: rgba(17,24,39,0.92);    /* ⬆️ higher contrast */
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(31,41,55,0.18);
  position: relative;
}

/* subtle anchor underline (very “premium”, not loud) */
.block-title::before {
  content: "";
  position: absolute;
  left: 0;
  bottom: -1px;
  width: 38px;
  height: 2px;
  background: var(--rc-accent);
  border-radius: 2px;
  opacity: 0.9;
}

.kvline { margin: 6px 0; line-height: 1.35; }
.kvline b { font-weight: 950; }

/* Compact blocks */
.block.compact {
  padding: 11px 12px;
  border-radius: var(--rc-radius-md);
  font-size: 0.91rem;
  line-height: 1.28;
  box-shadow: var(--rc-shadow2);
}

/* Compact cards (secondary but readable) */
.block-title.compact {
  font-size: 1.00rem;            /* ⬆️ bigger */
  font-weight: 950;
  letter-spacing: 0.12em;
  color: rgba(17,24,39,0.82);
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid rgba(31,41,55,0.12);
  position: relative;
}

/* no accent underline on compact */
.block-title.compact::before { display: none; }

.kvline.compact { margin: 4px 0; line-height: 1.22; }

.compact-caption {
  margin-top: 6px;
  color: var(--rc-muted);
  font-size: 0.84rem;
  line-height: 1.25;
}

.inline-muted {
  color: var(--rc-muted2);
  font-size: 0.86rem;
}

/* ============================================================
   FIGURE-STYLE TITLE ROW (for “Where this patient falls”)
   ============================================================ */
.fig-title-row{
  display:flex;
  justify-content:space-between;
  align-items:baseline;
  gap:10px;
  margin-bottom:6px;
}

.fig-title{
  font-variant-caps: all-small-caps;
  letter-spacing: 0.14em;
  font-weight: 975;
  font-size: 1.08rem;             /* matches section feel */
  color: rgba(17,24,39,0.90);
}

.fig-chip{
  display:inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  border: 2px solid var(--rc-accent);
  background: var(--rc-accent-bg);
  font-weight: 950;
  font-size: 0.84rem;
  color: var(--rc-text);
  white-space: nowrap;
}

.fig-cap{
  margin: 0 0 10px 0;
  color: var(--rc-muted);
  font-size: 0.84rem;
  line-height: 1.25;
}

/* ============================================================
   BADGES
   ============================================================ */
.badge {
  display: inline-block;
  padding: 2px 9px;
  border-radius: 999px;
  border: 1px solid var(--rc-line-strong);
  background: rgba(255,255,255,0.65);
  backdrop-filter: blur(4px);
  font-size: 0.82rem;
  margin-left: 6px;
}

.ok {
  border-color: rgba(16,185,129,0.30);
  background: rgba(16,185,129,0.08);
}

.miss {
  border-color: rgba(245,158,11,0.30);
  background: rgba(245,158,11,0.10);
}

/* ============================================================
   TABLES (SAFE)
   ============================================================ */
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.92rem;
  line-height: 1.25;
}

table th,
table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--rc-line);
  text-align: left;
  vertical-align: top;
}

table th {
  background: #f9fafb;
  font-weight: 800;
  border-bottom: 2px solid var(--rc-line-strong);
}

/* Decision Framework (iframe tables) */
.components-html table,
.components-html th,
.components-html td {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter,
               "Helvetica Neue", Arial, sans-serif !important;
  font-size: 0.92rem !important;
  line-height: 1.25 !important;
  color: var(--rc-text) !important;
}

.components-html { margin-top: 4px !important; margin-bottom: 4px !important; }
.components-html + .components-html { margin-top: 6px !important; }

/* ============================================================
   EXPANDERS
   ============================================================ */
div[data-testid="stExpander"] div[role="button"] {
  padding-top: 0.38rem;
  padding-bottom: 0.38rem;
}

/* ============================================================
   INPUT WIDGET FIXES (NO OVERLAP)
   ============================================================ */
div[data-baseweb="input"] input,
div[data-baseweb="textarea"] textarea {
  font-size: 0.95rem !important;
  line-height: 1.25 !important;
  padding: 0.48rem 0.58rem !important;
}

div[data-baseweb="input"],
div[data-baseweb="textarea"] {
  min-height: 2.55rem !important;
}

div[data-baseweb="input"] input,
div[data-baseweb="textarea"] textarea {
  height: 2.55rem !important;
}

div[data-baseweb="input"] > div { align-items: center !important; }

div[data-baseweb="select"] > div {
  font-size: 0.95rem !important;
  line-height: 1.25 !important;
}

div[data-testid="stRadio"] label,
div[data-testid="stCheckbox"] label {
  line-height: 1.25 !important;
}

</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# Header card (title + version)
# ============================================================
st.markdown(
    f"""
<div class="header-card">
  <div class="header-title">{SYSTEM_NAME} {VERSION.get("levels","")}</div>
  <p class="header-sub">
    De-identified Demo • SmartPhrase paste → auto-fill • Levels 1–5 (+ sublevels)
  </p>
</div>
""",
    unsafe_allow_html=True,
)

st.info("De-identified use only. Do not enter patient identifiers.")

# ============================================================
# Normalized extractors + action helpers (single source of truth)
# ============================================================


def extract_management_plan(levels: dict) -> str:
    return str((levels.get("managementPlan") or levels.get("defaultPosture") or "")).strip()

def extract_decision_stability(levels: dict, insights: dict):
    band = levels.get("decisionStability") or insights.get("decision_stability") or "—"
    note = levels.get("decisionStabilityNote") or insights.get("decision_stability_note") or ""
    return scrub_terms(band), scrub_terms(note)

def extract_aspirin_line(asp: dict) -> str:
    raw = scrub_terms(asp.get("status", "Not assessed"))
    l = raw.lower()
    if l.startswith("avoid"):
        return "Not indicated"
    if l.startswith("consider"):
        return "Consider (shared decision)"
    if l.startswith("secondary prevention"):
        return "Secondary prevention (if no contraindication)"
    return raw or "—"
# ============================================================
# Unified Action (single source of truth for Action card + EMR note)
# ============================================================

def recommended_action_line_unified(out: dict, fallback: str = "") -> str:
    """
    Prefer engine's recommended_action_line(out) if present.
    Fall back to managementPlan/defaultPosture if missing.
    """
    # 1) Engine-provided helper (best)
    try:
        fn = getattr(le, "recommended_action_line", None)
        if callable(fn):
            s = str(fn(out) or "").strip()
            if s:
                return scrub_terms(s)
    except Exception:
        pass

    # 2) Fallback to plan/posture text (still deterministic)
    s = str(fallback or "").strip()
    return scrub_terms(s) if s else "—"


def _inject_management_line_into_note(note: str, action_line: str) -> str:
    """
    Replace any existing 'Management:' line in the EMR note with the unified action line.
    Works with bullet or non-bullet forms.
    """
    if not note:
        return note or ""

    action_line = (action_line or "").strip()
    if not action_line:
        return note

    action_clean = action_line.rstrip().rstrip(".")

    pat = re.compile(r"(?mi)^(?P<prefix>\s*(?:[-•]\s*)?)Management:\s*.*$")
    repl = r"\g<prefix>Management: " + action_clean

    if pat.search(note):
        return pat.sub(repl, note, count=1)

    # If no Management line exists, try to add it under "Plan:" (fail-soft)
    pat_plan = re.compile(r"(?mi)^(Plan:\s*)$")
    if pat_plan.search(note):
        return pat_plan.sub(r"\1\n- Management: " + action_clean, note, count=1)

    return note


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
        st.session_state["lpa_val"] = float(lpa_v)
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
DEFAULTS = {
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
    "lpa_val": 0.0,
    "lpa_unit_val": "nmol/L",
    "hscrp_val": 0.0,
    "cac_known_val": "No",
    "cac_val": 0,
    "bmi_val": 0.0,
    "egfr_val": 0.0,
    "lipid_lowering_val": "No",
    "uacr_val": 0.0,
    "sdi_decile_val": 0,
    "smartphrase_raw": "",
    "parsed_preview_cache": {},
    "last_applied_msg": "",
    "last_missing_msg": "",
    "demo_defaults_on": True,
    "demo_defaults_applied": False,
}

# --- initialize session state (MUST be before any widgets) ---
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)

for k in ["ra", "psoriasis", "sle", "ibd", "hiv", "osa", "nafld"]:
    st.session_state.setdefault(f"infl_{k}_val", False)

for bk in ["bleed_gi", "bleed_nsaid", "bleed_anticoag", "bleed_disorder", "bleed_ich", "bleed_ckd"]:
    st.session_state.setdefault(bk, False)


def reset_fields():
    for k, v in DEFAULTS.items():
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
        "lpa_val": 90.0,
        "lpa_unit_val": "nmol/L",
        "a1c_val": 5.8,
        "hscrp_val": 1.2,
        "cac_known_val": "No",
        "cac_val": 0,
        "bmi_val": 28.0,
        "egfr_val": 85.0,
        "lipid_lowering_val": "No",
        "uacr_val": 0.0,
        "sdi_decile_val": 0,
        "demo_defaults_applied": True,
    })
    for kk in ["ra", "psoriasis", "sle", "ibd", "hiv", "osa", "nafld"]:
        st.session_state[f"infl_{kk}_val"] = False


# --- sidebar: demo controls ---
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


# --- sidebar: dev controls ---
with st.sidebar:
    st.markdown("### Dev")
    DEV_DISABLE_CACHE = st.checkbox("Disable cache (dev)", value=True)
    if st.button("Clear cache now"):
        st.cache_data.clear()
        st.rerun()

# ============================================================
# Engine version selector
# ============================================================
ENGINE_VERSION = "v4"  # options: "legacy" | "v4"

# ============================================================
# Engine call (dev-friendly caching)
# ============================================================
ENGINE_CACHE_SALT = (
    str(getattr(le, "PCE_DEBUG_SENTINEL", "no_sentinel"))
    + "|"
    + str(VERSION.get("levels", ""))
    + "|"
    + str(ENGINE_VERSION)
)


ENGINE_VERSION = "v4"  # switch here: "legacy" or "v4"

def run_engine_uncached(data_json: str):
    data_in = json.loads(data_json)
    p = Patient(data_in)
    return evaluate_unified(p, engine_version=ENGINE_VERSION)

@st.cache_data(ttl=300)
def run_engine_cached(data_json: str, cache_salt: str):
    data_in = json.loads(data_json)
    p = Patient(data_in)
    return evaluate_unified(p, engine_version=ENGINE_VERSION)


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
# Imaging (outside form)
# ============================================================
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
out = run_engine_uncached(data_json) if DEV_DISABLE_CACHE else run_engine_cached(data_json, ENGINE_CACHE_SALT)

patient = Patient(data)
note_text = le.render_quick_text(patient, out)
note_text = scrub_terms(note_text)

lvl = out.get("levels", {}) or {}
ev = (lvl.get("evidence") or {}) if isinstance(lvl.get("evidence"), dict) else {}
rs = out.get("riskSignal", {}) or {}
risk10 = out.get("pooledCohortEquations10yAscvdRisk", {}) or {}
prevent10 = out.get("prevent10", {}) or {}
asp = out.get("aspirin", {}) or {}
ins = out.get("insights", {}) or {}

ckm_copy = (ins.get("ckm_copy") or {}) if isinstance(ins, dict) else {}

level = int(lvl.get("managementLevel") or lvl.get("postureLevel") or lvl.get("level") or 1)
level = max(1, min(5, level))
sub = lvl.get("sublevel")
legend = lvl.get("legend") or FALLBACK_LEVEL_LEGEND

decision_conf = scrub_terms(lvl.get("decisionConfidence") or "—")
decision_stability, decision_stability_note = extract_decision_stability(lvl, ins)

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

anchors = out.get("anchors", {}) or {}
near_anchor = scrub_terms((anchors.get("nearTerm") or {}).get("summary", "—"))
life_anchor = scrub_terms((anchors.get("lifetime") or {}).get("summary", "—"))

plan_raw = extract_management_plan(lvl)
plan_clean = re.sub(r"^\s*(Recommended:|Consider:|Pending more data:)\s*", "", plan_raw).strip()
plan_clean = scrub_terms(plan_clean)

asp_line = extract_aspirin_line(asp)
asp_expl = scrub_terms(asp.get("explanation", ""))  # Details tab only
asp_status_raw = scrub_terms(asp.get("status", "Not assessed"))

st.caption(f"Last calculation: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def _plaque_unmeasured(ev_dict: dict) -> bool:
    cs = str(ev_dict.get("cac_status", "")).strip().lower()
    return ("unknown" in cs) or ("no structural" in cs) or ("unmeasured" in cs)

# ============================================================
# Tight criteria table (with circles) — UPDATED (no drift)
# - Patient value appears ONLY in the matching row (no duplication)
# - Non-matching threshold rows show a blank patient cell (not "—")
# - LDL section still behaves: shown as reference unless ApoB not measured
# ============================================================
def render_criteria_table_compact(
    *,
    apob_v,
    ldl_v,
    a1c_v,
    hscrp_v,
    lpa_v,
    lpa_unit_v,
    smoker_v,
    diabetes_v,
) -> str:
    def _fmt_num(x, decimals=0):
        if x is None:
            return "—"
        try:
            fx = float(x)
        except Exception:
            return "—"
        if decimals <= 0:
            return str(int(round(fx)))
        return f"{fx:.{decimals}f}"

    def _in_range(v, lo=None, hi=None):
        if v is None:
            return False
        try:
            v = float(v)
        except Exception:
            return False
        if lo is not None and v < lo:
            return False
        if hi is not None and v > hi:
            return False
        return True

    apob_measured = apob_v is not None
    use_ldl = (not apob_measured) and (ldl_v is not None)

    # ------------------------------------------------------------
    # Atherogenic
    # ------------------------------------------------------------
    apob_mild  = apob_measured and _in_range(apob_v, 80, 99)
    apob_major = apob_measured and _in_range(apob_v, 100, None)

    ldl_mild  = use_ldl and _in_range(ldl_v, 100, 129)
    ldl_major = use_ldl and _in_range(ldl_v, 130, None)

    # ------------------------------------------------------------
    # Glycemia
    # ------------------------------------------------------------
    a1c_mild1 = _in_range(a1c_v, 5.7, 6.1)
    a1c_mild2 = _in_range(a1c_v, 6.2, 6.4)
    a1c_major = bool(diabetes_v) or _in_range(a1c_v, 6.5, None)

    # ------------------------------------------------------------
    # Inflammation
    # ------------------------------------------------------------
    hscrp_mild = _in_range(hscrp_v, 2.0, None)

    # ------------------------------------------------------------
    # Genetics
    # ------------------------------------------------------------
    lpa_present = (lpa_v is not None and lpa_unit_v in ("nmol/L", "mg/dL"))
    lpa_major = False
    if lpa_present:
        if lpa_unit_v == "nmol/L":
            lpa_major = _in_range(lpa_v, 125, None)
        else:
            lpa_major = _in_range(lpa_v, 50, None)

    # ------------------------------------------------------------
    # Smoking
    # ------------------------------------------------------------
    smoking_major = bool(smoker_v)

    dom_athero = bool(apob_mild or apob_major or ldl_mild or ldl_major)
    dom_gly    = bool(a1c_mild1 or a1c_mild2 or a1c_major)
    dom_infl   = bool(hscrp_mild)
    dom_gen    = bool(lpa_major)
    dom_smoke  = bool(smoking_major)

    # ------------------------------------------------------------
    # Cell builders
    # ------------------------------------------------------------
    def _cell(text, *, ring=False, muted=False, tag=None):
        cls = "rc2-cell"
        if muted:
            cls += " rc2-muted"
        if ring:
            cls += " rc2-ring"
        tag_html = f"<span class='rc2-tag'>{tag}</span>" if tag else ""
        return f"<div class='{cls}'>{text}{tag_html}</div>"

    def _patient_cell(value_text: str, match: bool):
        """
        Show patient value only in the matching row.
        Non-matching rows show a blank patient cell (reference-only),
        which prevents the same value from appearing in multiple rows.
        """
        if match:
            return _cell(value_text, ring=True, muted=False)
        return _cell("&nbsp;", muted=True)  # blank but keeps row height stable

    def _domain_header(name, active=False, right_note=""):
        a = " rc2-domain-active" if active else ""
        rn = f"<div class='rc2-domain-note'>{right_note}</div>" if right_note else "<div></div>"
        return f"""
<div class="rc2-domain{a}">
  <div class="rc2-domain-title">{name}</div>
  {rn}
</div>
"""

    # ------------------------------------------------------------
    # Active chip text: the strongest matching row
    # ------------------------------------------------------------
    def _active_chip_text() -> str:
        if apob_measured and apob_v is not None and (apob_mild or apob_major):
            return f"ApoB {_fmt_num(apob_v)} mg/dL"
        if (not apob_measured) and (ldl_v is not None) and (ldl_mild or ldl_major):
            return f"LDL-C {_fmt_num(ldl_v)} mg/dL"

        if a1c_v is not None and (a1c_mild1 or a1c_mild2 or a1c_major):
            return f"A1c {_fmt_num(a1c_v, decimals=1)}%"

        if hscrp_v is not None and hscrp_mild:
            return f"hsCRP {_fmt_num(hscrp_v, decimals=1)} mg/L"

        if lpa_present and lpa_major:
            return f"Lp(a) {_fmt_num(lpa_v)} {lpa_unit_v}"

        if smoking_major:
            return "Smoking: Yes"

        # fallback context (measured values, no match)
        if apob_measured and apob_v is not None:
            return f"ApoB {_fmt_num(apob_v)} mg/dL"
        if a1c_v is not None:
            return f"A1c {_fmt_num(a1c_v, decimals=1)}%"
        if lpa_present:
            return f"Lp(a) {_fmt_num(lpa_v)} {lpa_unit_v}"
        if hscrp_v is not None:
            return f"hsCRP {_fmt_num(hscrp_v, decimals=1)} mg/L"
        if smoker_v is not None:
            return "Smoking: Yes" if smoker_v else "Smoking: No"
        return ""

    # ------------------------------------------------------------
    # Figure header (title + chip + caption)
    # ------------------------------------------------------------
    active_txt = _active_chip_text()
    chip_html = f"<span class='fig-chip'>{active_txt}</span>" if active_txt else ""

    fig_header = f"""
<div class="fig-title-row">
  <div class="fig-title">Where this patient falls</div>
  {chip_html}
</div>
<div class="fig-cap">Circled row shows the patient’s matching range; other rows are reference thresholds.</div>
"""

    # ------------------------------------------------------------
    # ATHEROGENIC BURDEN
    # ------------------------------------------------------------
    athero_rows = []

    if apob_measured:
        apob_txt = f"{_fmt_num(apob_v)} mg/dL"
        athero_rows.append(f"""
<div class="rc2-row">
  {_cell("ApoB")}
  {_cell("80–99 mg/dL")}
  {_patient_cell(apob_txt, apob_mild)}
  {_cell("Mild signal", tag="mild")}
</div>
<div class="rc2-row">
  {_cell("")}
  {_cell("≥100 mg/dL")}
  {_patient_cell(apob_txt, apob_major)}
  {_cell("Major driver", tag="major")}
</div>
""")
    else:
        athero_rows.append(f"""
<div class="rc2-row">
  {_cell("ApoB")}
  {_cell("—")}
  {_cell("—", muted=True)}
  {_cell("Not measured", muted=True)}
</div>
""")

    ldl_txt = f"{_fmt_num(ldl_v)} mg/dL" if ldl_v is not None else "—"

    if use_ldl:
        athero_rows.append(f"""
<div class="rc2-row">
  {_cell("LDL-C")}
  {_cell("100–129 mg/dL")}
  {_patient_cell(ldl_txt, ldl_mild)}
  {_cell("Mild signal", tag="mild")}
</div>
<div class="rc2-row">
  {_cell("")}
  {_cell("≥130 mg/dL")}
  {_patient_cell(ldl_txt, ldl_major)}
  {_cell("Major driver", tag="major")}
</div>
""")
    else:
        # ApoB measured OR LDL missing: show LDL as reference-only context
        athero_rows.append(f"""
<div class="rc2-row">
  {_cell("LDL-C")}
  {_cell("—")}
  {_cell(ldl_txt if ldl_v is not None else "—", muted=True)}
  {_cell("Used only if ApoB not measured", muted=True)}
</div>
""")

    athero_block = _domain_header(
        "Atherogenic burden",
        active=dom_athero,
        right_note=("ApoB preferred" if apob_measured else ("LDL used (ApoB not measured)" if ldl_v is not None else "ApoB preferred")),
    ) + "\n".join(athero_rows)

    # ------------------------------------------------------------
    # GLYCEMIA
    # ------------------------------------------------------------
    a1c_txt = f"{_fmt_num(a1c_v, decimals=1)}%" if a1c_v is not None else "—"

    gly_block = _domain_header("Glycemia", active=dom_gly) + f"""
<div class="rc2-row">
  {_cell("A1c")}
  {_cell("5.7–6.1%")}
  {_patient_cell(a1c_txt, a1c_mild1)}
  {_cell("Mild signal", tag="mild")}
</div>
<div class="rc2-row">
  {_cell("")}
  {_cell("6.2–6.4%")}
  {_patient_cell(a1c_txt, a1c_mild2)}
  {_cell("Near boundary", tag="mild")}
</div>
<div class="rc2-row">
  {_cell("")}
  {_cell("≥6.5% or diabetes = true")}
  {_patient_cell(a1c_txt, a1c_major)}
  {_cell("Major driver", tag="major")}
</div>
"""

    # ------------------------------------------------------------
    # INFLAMMATION
    # ------------------------------------------------------------
    hscrp_txt = f"{_fmt_num(hscrp_v, decimals=1)} mg/L" if hscrp_v is not None else "—"

    infl_block = _domain_header("Inflammation", active=dom_infl) + f"""
<div class="rc2-row">
  {_cell("hsCRP")}
  {_cell("≥2.0 mg/L")}
  {_patient_cell(hscrp_txt, hscrp_mild)}
  {_cell("Mild signal", tag="mild")}
</div>
"""

    # ------------------------------------------------------------
    # GENETICS
    # ------------------------------------------------------------
    lpa_txt = f"{_fmt_num(lpa_v)} {lpa_unit_v}" if lpa_present else "—"

    gen_block = _domain_header("Genetics", active=dom_gen) + f"""
<div class="rc2-row">
  {_cell("Lp(a)")}
  {_cell("≥125 nmol/L or ≥50 mg/dL")}
  {_patient_cell(lpa_txt, lpa_major)}
  {_cell("Major driver", tag="major", muted=(not lpa_major))}
</div>
"""

    # ------------------------------------------------------------
    # SMOKING
    # ------------------------------------------------------------
    smoke_txt = "Yes" if smoking_major else "No"

    smoke_block = _domain_header("Smoking", active=dom_smoke) + f"""
<div class="rc2-row">
  {_cell("Smoking")}
  {_cell("Current smoking")}
  {_cell(smoke_txt, ring=smoking_major, muted=(not smoking_major))}
  {_cell("Major driver" if smoking_major else "—", tag=("major" if smoking_major else None), muted=(not smoking_major))}
</div>
"""

    # ------------------------------------------------------------
    # HTML + local CSS
    # ------------------------------------------------------------
    html = f"""
<style>
  .rc2-wrap {{
    border:1px solid rgba(31,41,55,0.12);
    border-radius:12px;
    background:#fff;
    padding:12px 14px;
    font-size:0.92rem;
    line-height:1.25;
    margin-top:10px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.06);
  }}
  .rc2-gridhead {{
    display:grid;
    grid-template-columns: 1.05fr 1.15fr 0.95fr 1.25fr;
    gap:8px;
    padding:7px 0;
    border-bottom:1px solid rgba(31,41,55,0.10);
    color:rgba(31,41,55,0.65);
    font-size:0.82rem;
    font-weight:900;
  }}
  .rc2-domain {{
    display:flex;
    justify-content:space-between;
    align-items:baseline;
    margin-top:10px;
    padding-top:8px;
    border-top:1px solid rgba(31,41,55,0.08);
  }}
  .rc2-domain-title {{ font-weight:950; color:#111827; font-size:0.88rem; }}
  .rc2-domain-note {{ color:rgba(31,41,55,0.60); font-size:0.82rem; font-weight:800; }}
  .rc2-domain-active {{
    background: rgba(59,130,246,0.04);
    border-radius:10px;
    padding:6px 8px;
    border:1px solid rgba(59,130,246,0.12);
  }}
  .rc2-row {{
    display:grid;
    grid-template-columns: 1.05fr 1.15fr 0.95fr 1.25fr;
    gap:8px;
    padding:6px 0;
    border-bottom:1px solid rgba(31,41,55,0.06);
    align-items:start;
  }}
  .rc2-row:last-child {{ border-bottom:none; }}
  .rc2-cell {{ margin:0; padding:0; color:#111827; }}
  .rc2-muted {{ color:rgba(31,41,55,0.55); }}
  .rc2-ring {{
    display:inline-block;
    padding:2px 8px;
    border-radius:999px;
    border:2px solid rgba(59,130,246,0.85);
    background: rgba(59,130,246,0.08);
    font-weight:950;
    width: fit-content;
  }}
  .rc2-tag {{
    display:inline-block;
    margin-left:6px;
    font-size:0.74rem;
    padding:2px 8px;
    border-radius:999px;
    border:1px solid rgba(31,41,55,0.16);
    background:#fff;
    font-weight:950;
    color:rgba(31,41,55,0.80);
    vertical-align:middle;
  }}
</style>

<div class="rc2-wrap">
  {fig_header}

  <div class="rc2-gridhead">
    <div>Marker</div><div>Range / condition</div><div>Patient</div><div>Level effect</div>
  </div>

  {athero_block}
  {gly_block}
  {infl_block}
  {gen_block}
  {smoke_block}
</div>
"""
    return html



# ============================================================
# Tabs
# ============================================================
tab_report, tab_framework, tab_details, tab_debug = st.tabs(
    ["Report", "Decision Framework", "Details", "Debug"]
)

# ------------------------------------------------------------
# REPORT TAB
# ------------------------------------------------------------
with tab_report:
    st.markdown(render_risk_continuum_bar(level, sub), unsafe_allow_html=True)

    stab_line = f"{decision_stability}" + (f" — {decision_stability_note}" if decision_stability_note else "")

    st.markdown(
        f"""
<div class="block">
  <div class="block-title">Snapshot</div>

  <div class="kvline"><b>Level:</b>
    {level}{f" ({sub})" if sub else ""} — {LEVEL_NAMES.get(level,'—')}
  </div>

  <div class="kvline">
    <b>Plaque status:</b> {scrub_terms(ev.get('cac_status','—'))}
    &nbsp; <b>Plaque burden:</b> {scrub_terms(ev.get('burden_band','—'))}
  </div>

  <div class="kvline">
    <b>Decision confidence:</b> {decision_conf}
    &nbsp; <b>Decision stability:</b> {stab_line}
  </div>

  <div class="kvline">
    <b>Key metrics:</b>
    RSS {rs.get('score','—')}/100 ({rs.get('band','—')})
    • ASCVD PCE (10y) {pce_line} {pce_cat}
  </div>

  <div class="kvline">
    <b>PREVENT (10y, population model):</b>
    total CVD {f"{p_total}%" if p_total is not None else '—'}
    • ASCVD {f"{p_ascvd}%" if p_ascvd is not None else '—'}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"<div class='compact-caption'>{_html.escape(PREVENT_EXPLAINER)}</div>",
        unsafe_allow_html=True
    )
    if (p_total is None and p_ascvd is None) and p_note:
        st.markdown(
            f"<div class='compact-caption'>PREVENT: {_html.escape(p_note)}</div>",
            unsafe_allow_html=True
        )

    # Tight criteria table (rings)
    st.markdown(
        render_criteria_table_compact(
            apob_v=data.get("apob"),
            ldl_v=data.get("ldl"),
            a1c_v=data.get("a1c"),
            hscrp_v=data.get("hscrp"),
            lpa_v=data.get("lpa"),
            lpa_unit_v=data.get("lpa_unit"),
            smoker_v=bool(data.get("smoking")),
            diabetes_v=bool(data.get("diabetes")),
        ),
        unsafe_allow_html=True,
    )

    # Secondary insights (engine-gated)
    rd = (out.get("insights") or {}).get("risk_driver_pattern") or {}
    if rd.get("should_surface"):
        st.markdown(
            f"""
<div class="block compact">
  <div class="block-title compact">Secondary insights</div>
  <div class="kvline compact">{_html.escape(rd.get("headline",""))}</div>
  <div class="kvline compact inline-muted">{_html.escape(rd.get("detail",""))}</div>
</div>
""",
            unsafe_allow_html=True,
        )

    # CKM context (engine-gated; display-only)
    if ckm_copy.get("headline"):
        st.markdown(
            f"""
<div class="block compact">
  <div class="block-title compact">CKM context</div>
  <div class="kvline compact">{_html.escape(ckm_copy.get("headline",""))}</div>
  {f"<div class='kvline compact inline-muted'>{_html.escape(ckm_copy.get('detail',''))}</div>" if ckm_copy.get("detail") else ""}
</div>
""",
            unsafe_allow_html=True,
        )

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    col_t, col_m = st.columns([1.05, 1.35], gap="small")

    # Targets
    with col_t:
        if primary:
            lipid_targets_line = f"{primary[0]} {primary[1]}"
            if apob_line:
                lipid_targets_line += f" • {apob_line[0]} {apob_line[1]}"

            anchor = guideline_anchor_note(level, clinical_ascvd)
            apob_note = (
                "ApoB not measured — optional add-on if discordance suspected."
                if apob_line and not apob_measured
                else ""
            )

            st.markdown(
                f"""
<div class="block compact">
  <div class="block-title compact">Targets (if treated)</div>
  <div class="kvline compact"><b>Targets:</b> {_html.escape(lipid_targets_line)}</div>
  <div class="compact-caption">{_html.escape(anchor)}</div>
  {f"<div class='compact-caption'>{_html.escape(apob_note)}</div>" if apob_note else ""}
</div>
""",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
<div class="block compact">
  <div class="block-title compact">Targets (if treated)</div>
  <div class="kvline compact"><b>Targets:</b> —</div>
</div>
""",
                unsafe_allow_html=True,
            )

    # Action
    with col_m:
        rec_action = recommended_action_line_unified(out, fallback=plan_clean)

        cac_copy = (out.get("insights") or {}).get("cac_copy") or {}
        cac_head = _html.escape(cac_copy.get("headline") or "Coronary calcium: —")
        cac_det = _html.escape(cac_copy.get("detail") or "")
        cac_ref = _html.escape(cac_copy.get("referral") or "")

        cac_block = (
            f"<div class='kvline compact'>{cac_head}</div>"
            + (f"<div class='kvline compact inline-muted'>{cac_det}</div>" if cac_det else "")
            + (f"<div class='kvline compact inline-muted'>{cac_ref}</div>" if cac_ref else "")
        )

        asp_copy = (out.get("insights") or {}).get("aspirin_copy") or {}
        asp_head = _html.escape(asp_copy.get("headline") or f"Aspirin: {asp_line}")

        st.markdown(
            f"""
<div class="block compact">
  <div class="block-title compact">Action</div>

  <div class="kvline compact"><b>Recommended action:</b></div>
  <div class="kvline compact">{_html.escape(rec_action)}</div>

  <div class="kvline compact" style="margin-top:6px;"><b>Coronary calcium:</b></div>
  {cac_block}

  <div class="kvline compact" style="margin-top:6px;"><b>Aspirin:</b></div>
  <div class="kvline compact">{asp_head}</div>
</div>
""",
            unsafe_allow_html=True,
        )

    # EMR note  ✅ MUST stay inside tab_report
    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("EMR note (copy/paste)")

    note_for_emr = le.render_quick_text(patient, out)
    note_for_emr = scrub_terms(note_for_emr)
    note_for_emr = _inject_management_line_into_note(note_for_emr, rec_action)

    # Optional: append CKM context to EMR note (string-safe)
    if ckm_copy.get("headline"):
        note_for_emr += "\n\nCKM context:\n" + str(ckm_copy.get("headline"))
        if ckm_copy.get("detail"):
            note_for_emr += "\n" + str(ckm_copy.get("detail"))

    emr_copy_box("Risk Continuum — EMR Note", note_for_emr, height_px=520)

# ------------------------------------------------------------
# DECISION FRAMEWORK TAB (no giant second table)
# ------------------------------------------------------------
with tab_framework:
    st.subheader("How Levels Are Specified")
    st.caption(
        "Levels are assigned based on biologic signal strength, plaque status, and convergence of risk — "
        "not by forced treatment rules."
    )

    st.markdown("### This patient")
    this_def = safe_level_def(level, sub)
    if this_def:
        title = this_def.get("sublevel_name") or this_def.get("level_name") or "—"
        desc = this_def.get("sublevel_definition") or this_def.get("level_definition") or "—"
        st.markdown(f"**Assigned:** Level {level}" + (f" ({sub})" if sub else "") + f" — {title}")
        st.write(desc)
    else:
        st.info("Engine definitions not available (get_level_definition_payload not found).")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)

    components.html(
        """
<div style="overflow-x:auto;">
  <table style="width:100%; border-collapse:collapse; font-size:0.92rem; border:1px solid rgba(31,41,55,0.12);">
    <thead>
      <tr style="background:#f9fafb;">
        <th style="text-align:left; padding:10px; border-bottom:2px solid rgba(31,41,55,0.18);">Level</th>
        <th style="text-align:left; padding:10px; border-bottom:2px solid rgba(31,41,55,0.18);">Risk state</th>
        <th style="text-align:left; padding:10px; border-bottom:2px solid rgba(31,41,55,0.18);">Medication posture</th>
      </tr>
    </thead>
    <tbody>
      <tr><td style="padding:10px; border-bottom:1px solid rgba(31,41,55,0.12);"><b>1</b></td>
          <td style="padding:10px; border-bottom:1px solid rgba(31,41,55,0.12);">Minimal risk signal</td>
          <td style="padding:10px; border-bottom:1px solid rgba(31,41,55,0.12);">Do not treat</td></tr>
      <tr><td style="padding:10px; border-bottom:1px solid rgba(31,41,55,0.12);"><b>2A/2B</b></td>
          <td style="padding:10px; border-bottom:1px solid rgba(31,41,55,0.12);">Emerging risk signals</td>
          <td style="padding:10px; border-bottom:1px solid rgba(31,41,55,0.12);">Preference-sensitive</td></tr>
      <tr><td style="padding:10px; border-bottom:1px solid rgba(31,41,55,0.12);"><b>3A/3B</b></td>
          <td style="padding:10px; border-bottom:1px solid rgba(31,41,55,0.12);">Actionable biologic risk</td>
          <td style="padding:10px; border-bottom:1px solid rgba(31,41,55,0.12);">Treatment reasonable / favored</td></tr>
      <tr><td style="padding:10px; border-bottom:1px solid rgba(31,41,55,0.12);"><b>4</b></td>
          <td style="padding:10px; border-bottom:1px solid rgba(31,41,55,0.12);">Subclinical atherosclerosis present</td>
          <td style="padding:10px; border-bottom:1px solid rgba(31,41,55,0.12);">Treat (target-driven)</td></tr>
      <tr><td style="padding:10px;"><b>5</b></td>
          <td style="padding:10px;">Very high risk / ASCVD intensity</td>
          <td style="padding:10px;">Treat (secondary prevention)</td></tr>
    </tbody>
  </table>
</div>
""",
        height=360,
    )

# ------------------------------------------------------------
# DETAILS TAB
# ------------------------------------------------------------
with tab_details:
    st.subheader("Anchors (near-term vs lifetime)")
    st.markdown(f"**Near-term anchor:** {near_anchor}")
    st.markdown(f"**Lifetime anchor:** {life_anchor}")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Coronary calcium (engine rationale)")
    cs = (out.get("insights") or {}).get("cac_decision_support") or {}

    if cs:
        st.write("**Engine signal:** See rationale below (internal decision-support).")
    else:
        st.write("**Engine signal:** —")

    if cs.get("rationale"):
        st.write(f"**Rationale:** {scrub_terms(cs.get('rationale'))}")
    if cs.get("message"):
        st.write(f"**Use:** {scrub_terms(cs.get('message'))}")
    if cs.get("tag"):
        st.caption(f"Tag: {cs.get('tag')}")

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Decision stability (detail)")
    st.markdown(
        f"**{decision_stability}**"
        + (f" — {decision_stability_note}" if decision_stability_note else "")
    )

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("Aspirin (detail)")
    asp_why = scrub_terms(short_why(asp.get("rationale", []), max_items=5))
    st.write(
        f"**{asp_status_raw}**"
        + (f" — {asp_expl}" if asp_expl else "")
        + (f" **Why:** {asp_why}" if asp_why else "")
    )

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

    st.markdown('<div class="hr"></div>', unsafe_allow_html=True)
    st.subheader("CKM context (detail)")
    ckm = (out.get("insights") or {}).get("ckm_context") or {}
    if ckm:
        st.json(ckm)
    else:
        st.write("—")

# ------------------------------------------------------------
# DEBUG TAB
# ------------------------------------------------------------
with tab_debug:
    st.subheader("Engine quick output (raw text)")
    st.code(note_text, language="text")

    st.subheader("Trace (audit trail)")
    st.json(out.get("trace", []))

    if show_json:
        st.subheader("JSON (debug)")
        st.json(out)

# ------------------------------------------------------------
# Footer
# ------------------------------------------------------------
st.caption(
    f"Versions: {VERSION.get('levels','')} | {VERSION.get('riskSignal','')} | "
    f"{VERSION.get('riskCalc','')} | {VERSION.get('aspirin','')} | "
    f"{VERSION.get('prevent','')}. No storage intended."
)



































































































