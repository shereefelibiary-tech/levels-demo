# app.py (Risk Continuum — v2.8 clinician-clean layout)
# FULL, UPDATED VERSION (no "Overview" tab)
#
# Tabs: Report | Decision Framework | Details
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
from rc_viz.rss.rss_column import render_rss_column_html


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
st.caption("DEPLOY CHECK: engine control patch active")

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


def _tidy_emr_plan_section(note: str) -> str:
    """
    Keep Plan concise and clinician-friendly without altering any computed outputs.
    - Collapse duplicate high-level treatment bullets (Management + Lipid-lowering therapy).
    - Order Plan bullets consistently.
    - Avoid duplicate CAC rationale in Context when already present in Plan.
    """
    if not note:
        return note or ""

    lines = note.splitlines()
    plan_idx = next((i for i, ln in enumerate(lines) if ln.strip().lower() == "plan:"), None)
    if plan_idx is None:
        return note

    def _is_bullet(ln: str) -> bool:
        return bool(re.match(r"^\s*[-•]\s+", ln or ""))

    start = plan_idx + 1
    end = start
    while end < len(lines):
        ln = lines[end]
        stripped = ln.strip()
        if stripped.lower().startswith("context:"):
            break
        if stripped and (not _is_bullet(ln)):
            break
        end += 1

    plan_lines = lines[start:end]
    bullets = [ln for ln in plan_lines if _is_bullet(ln)]
    if not bullets:
        return note

    mgmt_idx = lipid_idx = None
    mgmt_text = lipid_text = ""
    parsed = []

    for idx, bullet in enumerate(bullets):
        txt = re.sub(r"^\s*[-•]\s+", "", bullet).strip()
        parsed.append(txt)
        low = txt.lower()
        if mgmt_idx is None and low.startswith("management:"):
            mgmt_idx = idx
            mgmt_text = txt.split(":", 1)[1].strip()
        if lipid_idx is None and low.startswith("lipid-lowering therapy:"):
            lipid_idx = idx
            lipid_text = txt.split(":", 1)[1].strip()

    if mgmt_idx is not None and lipid_idx is not None:
        mg = mgmt_text.rstrip(" .")
        lip = lipid_text.rstrip(" .")
        lip_clause = lip if lip.lower().startswith("lipid-lowering therapy") else f"lipid-lowering therapy {lip}".strip()
        combined = f"{mg}; {lip_clause}."
        parsed = [p for i, p in enumerate(parsed) if i not in {mgmt_idx, lipid_idx}]
        parsed.insert(0, combined[:1].upper() + combined[1:])

    def _cat(text: str) -> int:
        t = text.lower()
        if t.startswith("treatment ") or t.startswith("management:") or t.startswith("lipid-lowering therapy"):
            return 0
        if "apob" in t or "driver" in t:
            return 1
        if "aspirin" in t:
            return 2
        if "cac" in t or "coronary calcium" in t:
            return 3
        return 4

    parsed = [p for _, p in sorted(enumerate(parsed), key=lambda x: (_cat(x[1]), x[0]))]
    new_bullets = [f"- {p}" for p in parsed]

    has_plan_cac = any(("cac" in p.lower() or "coronary calcium" in p.lower()) for p in parsed)
    if has_plan_cac:
        for i, ln in enumerate(lines):
            if ln.strip().lower().startswith("context:") and "|" in ln and "cac" in ln.lower():
                head, tail = ln.split(":", 1)
                parts = [p.strip() for p in tail.split("|")]
                parts = [p for p in parts if "cac" not in p.lower() and "coronary calcium" not in p.lower()]
                lines[i] = f"{head}: {' | '.join(parts)}" if parts else f"{head}:"

    lines[start:end] = new_bullets
    return "\n".join(lines)


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
    ("uacr", "UACR (PREVENT)"),
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
    "clear_smartphrase_on_rerun": False,
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

    if st.session_state.get("clear_smartphrase_on_rerun", False):
        st.session_state["smartphrase_raw"] = ""
        st.session_state["clear_smartphrase_on_rerun"] = False

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

                if parsed.get("uacr") is not None:
                    st.session_state["uacr_val"] = float(parsed["uacr"])

                st.session_state["last_applied_msg"] = "Applied: " + (", ".join(applied) if applied else "None")
                st.session_state["last_missing_msg"] = "Missing/unparsed: " + (", ".join(missing) if missing else "All good!")
                st.rerun()

    with c2:
        if st.button("Clear pasted text"):
            st.session_state["clear_smartphrase_on_rerun"] = True
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
# Engine note (fail-soft if render_quick_text is missing)
_note_fn = getattr(le, "render_quick_text", None)
if callable(_note_fn):
    note_text = _note_fn(patient, out)
else:
    # Minimal fallback so the app never hard-crashes if the engine function is missing
    lvl0 = (out.get("levels") or {})
    note_text = (
        "RISK CONTINUUM — CLINICAL REPORT\n"
        "------------------------------------------------------------\n"
        f"Level: {lvl0.get('label', lvl0.get('meaning', '—'))}\n"
        f"Plaque: {lvl0.get('plaqueEvidence', '—')} | Burden: {lvl0.get('plaqueBurden', '—')}\n"
    )

note_text = scrub_terms(note_text)

lvl = out.get("levels", {}) or {}
ev = (lvl.get("evidence") or {}) if isinstance(lvl.get("evidence"), dict) else {}
# Plaque present flag (derived from engine evidence; app does not infer thresholds)
plaque_present = None
try:
    cs = str(ev.get("cac_status", "")).strip().lower()
    if "cac = 0" in cs:
        plaque_present = False
    elif "cac positive" in cs:
        plaque_present = True
except Exception:
    plaque_present = None

rs = out.get("riskSignal", {}) or {}
risk10 = out.get("pooledCohortEquations10yAscvdRisk", {}) or {}
prevent10 = out.get("prevent10", {}) or {}
asp = out.get("aspirin", {}) or {}
ins = out.get("insights", {}) or {}

ckm_copy = (ins.get("ckm_copy") or {}) if isinstance(ins, dict) else {}
ckm_context = (ins.get("ckm_context") or {}) if isinstance(ins, dict) else {}
ckd_copy = (ins.get("ckd_copy") or {}) if isinstance(ins, dict) else {}

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

def _DEPRECATED_render_criteria_table_compact(*, out: dict, patient_data: dict) -> str:

    """
    Engine-driven criteria table (single source of truth = engine output).
    - Does NOT re-classify LDL/ApoB/A1c/hsCRP/Lp(a) locally.
    - Uses engine level/sublevel + engine triggers + engine plaque/risk context.
    - Uses patient_data only for displaying measured values (not for deciding "major/mild").

    Call site (replace your current call):
      st.markdown(render_criteria_table_compact(out=out, patient_data=data), unsafe_allow_html=True)
    """
    import html as _html

    def _normalize_space(s: str) -> str:
        return " ".join((s or "").strip().split())

    def _fmt_num(x, decimals=0):
        if x is None:
            return None
        try:
            fx = float(x)
        except Exception:
            return None
        if decimals <= 0:
            return str(int(round(fx)))
        return f"{fx:.{decimals}f}"

    def _fmt_val_unit(num_str: str | None, unit: str | None) -> str | None:
        if not num_str:
            return None
        u = (unit or "").strip()
        return f"{num_str} {u}".strip() if u else num_str

    def _truthy(x) -> bool:
        return bool(x is True)

    lvl = (out or {}).get("levels") or {}
    sub = (lvl.get("sublevel") or "").strip()
    triggers = lvl.get("triggers") or []
    triggers = [str(t).strip() for t in triggers if str(t).strip()]

    evidence = (lvl.get("evidence") or {}) if isinstance(lvl.get("evidence"), dict) else {}
    plaque_status = str(evidence.get("cac_status") or "").strip().lower()
    plaque_known = ("cac = 0" in plaque_status) or ("cac positive" in plaque_status) or (evidence.get("cac_value") is not None)

    risk10 = (out or {}).get("ascvdPce10yRisk") or (out or {}).get("pooledCohortEquations10yAscvdRisk") or {}
    rp = risk10.get("risk_pct")
    try:
        pce_pct = float(rp) if rp is not None else None
    except Exception:
        pce_pct = None

    # -----------------------------
    # Determine engine "signal class" from trigger strings
    # (Still engine-driven: we only interpret the engine's trigger labels.)
    # -----------------------------
    def _class_from_trigger(t: str) -> str:
        tl = t.lower()

        major_markers = (
            "apob≥",
            "ldl≥",
            "lp(a) elevated",
            "inflammation present",
            "diabetes-range",
            "smoking",
            "clinical ascvd",
            "cac ",
        )
        mild_markers = (
            "apob 80",
            "ldl 100",
            "ldl 130–159",
            "prediabetes",
            "a1c 6.2–6.4",
            "hscrp≥2",
            "premature family history",
        )

        if any(m in tl for m in major_markers):
            return "major"
        if any(m in tl for m in mild_markers):
            return "mild"
        return "signal"

    def _domain_for_trigger(t: str) -> str | None:
        tl = t.lower()
        if "apob" in tl or "ldl" in tl:
            return "Atherogenic burden"
        if "a1c" in tl or "prediabetes" in tl or "diabetes" in tl:
            return "Glycemia"
        if "hscrp" in tl or "inflammation" in tl or "ra" in tl or "psoriasis" in tl or "sle" in tl or "ibd" in tl or "hiv" in tl or "osa" in tl or "nafld" in tl:
            return "Inflammation"
        if "lp(a)" in tl or "lpa" in tl or "family history" in tl:
            return "Genetics"
        if "smoking" in tl:
            return "Smoking"
        if "cac" in tl:
            return "Plaque"
        return None

    # Only triggers that map to our display domains
    trig_by_domain: dict[str, list[str]] = {
        "Atherogenic burden": [],
        "Glycemia": [],
        "Inflammation": [],
        "Genetics": [],
        "Smoking": [],
    }
    for t in triggers:
        d = _domain_for_trigger(t)
        if d in trig_by_domain:
            trig_by_domain[d].append(t)

    # -----------------------------
    # Build per-domain display rows (values from patient_data only)
    # -----------------------------
    apob_v = patient_data.get("apob")
    ldl_v = patient_data.get("ldl")
    a1c_v = patient_data.get("a1c")
    hscrp_v = patient_data.get("hscrp")
    lpa_v = patient_data.get("lpa")
    lpa_unit = patient_data.get("lpa_unit")
    smoker_v = patient_data.get("smoking")
    diabetes_v = patient_data.get("diabetes")

    def _cell(text: str, *, muted=False, ring=False) -> str:
        cls = "rc2-cell"
        if muted:
            cls += " rc2-muted"
        if ring:
            cls += " rc2-ring"
        return f"<div class='{cls}'>{text}</div>"

    def _tag_html(tag: str | None) -> str:
        if tag == "major":
            return "<span class='rc2-tag'>major</span>"
        if tag == "mild":
            return "<span class='rc2-tag'>mild</span>"
        if tag == "signal":
            return "<span class='rc2-tag'>signal</span>"
        return ""

    def _domain_header(name: str, note: str | None, active: bool) -> str:
        a = " rc2-domain-active" if active else ""
        rn = f"<div class='rc2-domain-note'>{_html.escape(note)}</div>" if note else "<div></div>"
        return f"""
<div class="rc2-domain{a}">
  <div class="rc2-domain-title">{_html.escape(name)}</div>
  {rn}
</div>
"""

    def _patient_value_text(domain: str) -> str:
        if domain == "Atherogenic burden":
            if apob_v is not None:
                return _fmt_val_unit(_fmt_num(apob_v, 0), "mg/dL") or "—"
            if ldl_v is not None:
                return _fmt_val_unit(_fmt_num(ldl_v, 0), "mg/dL") or "—"
            return "Unmeasured"
        if domain == "Glycemia":
            if _truthy(diabetes_v):
                if a1c_v is not None:
                    return _fmt_val_unit(_fmt_num(a1c_v, 1), "%") or "Diabetes=true"
                return "Diabetes=true"
            if a1c_v is not None:
                return _fmt_val_unit(_fmt_num(a1c_v, 1), "%") or "—"
            return "Unmeasured"
        if domain == "Inflammation":
            if hscrp_v is not None:
                return _fmt_val_unit(_fmt_num(hscrp_v, 1), "mg/L") or "—"
            return "Unmeasured"
        if domain == "Genetics":
            if lpa_v is not None and str(lpa_unit or "").strip() in ("nmol/L", "mg/dL"):
                return _fmt_val_unit(_fmt_num(lpa_v, 0), str(lpa_unit).strip()) or "—"
            return "Unmeasured"
        if domain == "Smoking":
            if smoker_v is True:
                return "Yes"
            if smoker_v is False:
                return "No"
            return "Unmeasured"
        return "—"

    def _domain_condition_text(domain: str) -> str:
        # Do NOT encode thresholds here (engine-driven only). Keep short, descriptive.
        if domain == "Atherogenic burden":
            if apob_v is not None:
                return "ApoB (preferred marker)"
            return "LDL-C (ApoB unmeasured)"
        if domain == "Glycemia":
            return "A1c / diabetes status"
        if domain == "Inflammation":
            return "hsCRP (and inflammatory states)"
        if domain == "Genetics":
            return "Lp(a) / inherited risk"
        if domain == "Smoking":
            return "Current smoking"
        return "—"

    def _domain_effect(domain: str) -> tuple[str, str | None, bool]:
        """
        Returns (effect_label, tag, ring)
        Engine-driven:
          - If the engine has a trigger in that domain → effect is signal (mild/major based on trigger label).
          - If no engine trigger → effect is "—" (even if value is present).
        """
        ts = trig_by_domain.get(domain) or []
        if not ts:
            return "—", None, False

        # choose strongest label among triggers
        cls_rank = {"major": 3, "mild": 2, "signal": 1}
        best_cls = "signal"
        best_rank = 0
        for t in ts:
            c = _class_from_trigger(t)
            r = cls_rank.get(c, 0)
            if r > best_rank:
                best_rank = r
                best_cls = c

        if best_cls == "major":
            return "Major driver", "major", True
        if best_cls == "mild":
            return "Mild signal", "mild", True
        return "Signal", "signal", True

    def _domain_note(domain: str) -> str | None:
        if domain == "Atherogenic burden" and apob_v is None:
            return "LDL used (ApoB unmeasured)"
        if domain == "Genetics" and (lpa_v is None or str(lpa_unit or "").strip() not in ("nmol/L", "mg/dL")):
            return None
        return None

    domains_order = ["Atherogenic burden", "Glycemia", "Inflammation", "Genetics", "Smoking"]

    rows_html: list[str] = []

    # Header chip: best available patient value among domains with engine triggers
    def _chip_text() -> str:
        for d in domains_order:
            if trig_by_domain.get(d):
                pv = _patient_value_text(d)
                if pv and pv != "Unmeasured" and pv != "—":
                    if d == "Atherogenic burden":
                        if apob_v is not None:
                            return f"ApoB {pv}"
                        if ldl_v is not None:
                            return f"LDL-C {pv}"
                    if d == "Glycemia":
                        return f"A1c {pv}" if "Diabetes=true" not in pv else "Diabetes"
                    if d == "Inflammation":
                        return f"hsCRP {pv}"
                    if d == "Genetics":
                        return f"Lp(a) {pv}"
                    if d == "Smoking":
                        return "Smoking Yes" if pv == "Yes" else ""
        # fall back to atherogenic measured value (if any)
        if apob_v is not None:
            return f"ApoB {_patient_value_text('Atherogenic burden')}"
        if ldl_v is not None:
            return f"LDL-C {_patient_value_text('Atherogenic burden')}"
        return ""

    chip_txt = _chip_text()
    chip_html = f"<span class='fig-chip'>{_html.escape(chip_txt)}</span>" if chip_txt else ""

    # Active signals line: only when engine says a domain is active (triggered)
    active_bits: list[str] = []
    for d in domains_order:
        ts = trig_by_domain.get(d) or []
        if not ts:
            continue
        pv = _patient_value_text(d)
        eff, tag, _ring = _domain_effect(d)
        if pv and pv != "Unmeasured" and pv != "—":
            label = ""
            if d == "Atherogenic burden":
                label = "ApoB" if apob_v is not None else "LDL-C"
            elif d == "Glycemia":
                label = "A1c" if "Diabetes=true" not in pv else "Diabetes"
            elif d == "Inflammation":
                label = "hsCRP"
            elif d == "Genetics":
                label = "Lp(a)"
            elif d == "Smoking":
                label = "Smoking"
            eff_short = "Major driver" if tag == "major" else ("Mild signal" if tag == "mild" else "Signal")
            if label:
                active_bits.append(f"{label} {pv} ({eff_short})")
        else:
            # If triggered but unmeasured, keep quiet; avoid duplicate "Unmeasured" noise
            pass

    active_bits_clean: list[str] = []
    seen_a = set()
    for s in active_bits:
        k = s.strip().lower()
        if k and k not in seen_a:
            seen_a.add(k)
            active_bits_clean.append(s)

    signal_summary = ""
    if active_bits_clean:
        signal_summary = (
            "<div class='rc2-inline-note'><b>Active signals:</b> "
            + _html.escape(" • ".join(active_bits_clean))
            + "</div>"
        )

    # Other domains: show only supportive measured context that is not an active trigger (avoid “Smoking No”)
    other_bits: list[str] = []

    if hscrp_v is not None and not trig_by_domain.get("Inflammation"):
        other_bits.append(f"hsCRP {_fmt_val_unit(_fmt_num(hscrp_v, 1), 'mg/L')}")

    if smoker_v is True and not trig_by_domain.get("Smoking"):
        other_bits.append("Smoking Yes")

    other_line = ""
    if other_bits:
        other_line = (
            "<div class='rc2-inline-note'><b>Other domains:</b> "
            + _html.escape(" • ".join(other_bits))
            + "</div>"
        )

    # Build rows (one row per domain, but only show domains that are triggered OR clinically central)
    # Always show Atherogenic + Glycemia. Show others if triggered or measured.
    def _should_show_domain(d: str) -> bool:
        if d in ("Atherogenic burden", "Glycemia"):
            return True
        if trig_by_domain.get(d):
            return True
        pv = _patient_value_text(d)
        return pv not in ("Unmeasured", "—")

    for d in domains_order:
        if not _should_show_domain(d):
            continue

        pv = _patient_value_text(d)
        cond = _domain_condition_text(d)
        eff, tag, ring = _domain_effect(d)
        note = _domain_note(d)
        active = bool(trig_by_domain.get(d))

        rows_html.append(_domain_header(d, note, active=active))

        patient_text = str(pv).strip()
        patient_is_unmeasured = (patient_text == "Unmeasured")
        patient_cell = _cell(
            (_html.escape(patient_text) if patient_text else "—"),
            muted=patient_is_unmeasured,
            ring=bool(ring and (not patient_is_unmeasured)),
        )
        if patient_is_unmeasured:
            patient_cell = patient_cell.replace("Unmeasured", "<i>Unmeasured</i>")

        effect_text = _html.escape(str(eff or "—"))
        effect = f"{effect_text} {_tag_html(tag)}".strip()

        marker_label = "—"
        if d == "Atherogenic burden":
            marker_label = "ApoB" if apob_v is not None else "LDL-C"
        elif d == "Glycemia":
            marker_label = "A1c"
        elif d == "Inflammation":
            marker_label = "hsCRP"
        elif d == "Genetics":
            marker_label = "Lp(a)"
        elif d == "Smoking":
            marker_label = "Smoking"

        rows_html.append(f"""
<div class="rc2-row">
  {_cell(_html.escape(marker_label))}
  {_cell(_html.escape(cond))}
  {patient_cell}
  <div class="rc2-cell">{effect}</div>
</div>
""")

    # -----------------------------
    # Final HTML (no dev-copy, no duplicate unmeasured lines)
    # -----------------------------
    html = f"""
<style>
  .rc2-wrap {{
    border: 1px solid rgba(31,41,55,0.12);
    border-radius: 12px;
    background: #fff;
    padding: 12px 14px;
    font-size: 0.92rem;
    line-height: 1.25;
    margin-top: 10px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.06);
  }}

  .rc2-inline-note {{
    margin-top: 6px;
    color: rgba(31,41,55,0.68);
    font-size: 0.84rem;
    line-height: 1.25;
  }}
  .rc2-inline-note b {{
    font-weight: 900;
    color: rgba(17,24,39,0.82);
  }}

  .rc2-gridhead {{
    display: grid;
    grid-template-columns: 1.05fr 1.30fr 0.95fr 1.10fr;
    gap: 8px;
    padding: 7px 0;
    border-bottom: 1px solid rgba(31,41,55,0.10);
    color: rgba(31,41,55,0.65);
    font-size: 0.82rem;
    font-weight: 900;
    margin-top: 8px;
  }}

  .rc2-domain {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-top: 10px;
    padding-top: 8px;
    border-top: 1px solid rgba(31,41,55,0.08);
  }}
  .rc2-domain-title {{
    font-weight: 950;
    color: #111827;
    font-size: 0.88rem;
  }}
  .rc2-domain-note {{
    color: rgba(31,41,55,0.60);
    font-size: 0.82rem;
    font-weight: 800;
  }}
  .rc2-domain-active {{
    background: rgba(59,130,246,0.04);
    border-radius: 10px;
    padding: 6px 8px;
    border: 1px solid rgba(59,130,246,0.12);
  }}

  .rc2-row {{
    display: grid;
    grid-template-columns: 1.05fr 1.30fr 0.95fr 1.10fr;
    gap: 8px;
    padding: 6px 0;
    border-bottom: 1px solid rgba(31,41,55,0.06);
    align-items: start;
  }}

  .rc2-cell {{
    margin: 0;
    padding: 0;
    color: #111827;
  }}
  .rc2-muted {{
    color: rgba(31,41,55,0.55);
  }}

  .rc2-ring {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    border: 2px solid rgba(59,130,246,0.85);
    background: rgba(59,130,246,0.08);
    font-weight: 950;
    width: fit-content;
  }}

  .rc2-tag {{
    display: inline-block;
    margin-left: 6px;
    font-size: 0.74rem;
    padding: 2px 8px;
    border-radius: 999px;
    border: 1px solid rgba(31,41,55,0.16);
    background: #fff;
    font-weight: 950;
    color: rgba(31,41,55,0.80);
    vertical-align: middle;
  }}

  .fig-title-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 6px;
  }}

  .fig-title {{
    font-variant-caps: all-small-caps;
    letter-spacing: 0.14em;
    font-weight: 975;
    font-size: 1.08rem;
    color: rgba(17,24,39,0.90);
  }}

  .fig-chip {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    border: 2px solid rgba(59,130,246,0.85);
    background: rgba(59,130,246,0.08);
    font-weight: 950;
    font-size: 0.84rem;
    color: #111827;
    white-space: nowrap;
  }}
</style>

<div class="rc2-wrap">
  <div class="fig-title-row">
    <div class="fig-title">Where this patient falls</div>
    {chip_html}
  </div>

  {signal_summary}
  {other_line}

  <div class="rc2-gridhead">
    <div>Marker</div><div>Context</div><div>Patient</div><div>Level effect</div>
  </div>

  {''.join(rows_html)}
</div>
"""
    return html.strip()

# ============================================================
# CKM Vertical Rail helpers
# ============================================================
import re

def _format_ckd_stage_label_from_egfr(egfr_v: float | None) -> str:
    """
    Returns "CKD3a (eGFR 59)" using KDIGO G categories.
    """
    if egfr_v is None:
        return "CKD — unknown"
    try:
        v = float(egfr_v)
    except Exception:
        return "CKD — unknown"

    egfr_int = int(round(v))

    if v >= 90:
        stage = "CKD1"
    elif v >= 60:
        stage = "CKD2"
    elif v >= 45:
        stage = "CKD3a"
    elif v >= 30:
        stage = "CKD3b"
    elif v >= 15:
        stage = "CKD4"
    else:
        stage = "CKD5"

    return f"{stage} (eGFR {egfr_int})"


def _extract_ckm_stage_num(out: dict) -> int | None:
    """
    Parses 'Stage X' from insights.ckm_copy.headline or from other CKM copy fields if present.
    Returns stage number or None.
    """
    try:
        ins = out.get("insights") or {}

        # prefer headline
        head = (ins.get("ckm_copy") or {}).get("headline") or ""
        m = re.search(r"\bStage\s+(\d)\b", str(head))
        if m:
            return int(m.group(1))

        # fallback: sometimes stored under ckm_context/headline-like fields
        head2 = (ins.get("ckm_context") or {}).get("headline") or ""
        m2 = re.search(r"\bStage\s+(\d)\b", str(head2))
        if m2:
            return int(m2.group(1))

        return None
    except Exception:
        return None


def _ckm_stage_snapshot_explanation(stage_num: int | None, ckm_copy: dict, ckm_context: dict, data: dict) -> str:
    """
    Patient-specific explanation for Snapshot CKM line.
    """
    if stage_num not in (1, 2, 3):
        return ""

    driver = ""
    try:
        driver = str((ckm_copy or {}).get("driver") or "").strip().lower()
    except Exception:
        driver = ""

    ckm_ctx = ckm_context if isinstance(ckm_context, dict) else {}
    vals = (ckm_ctx.get("values") or {}) if isinstance(ckm_ctx.get("values"), dict) else {}

    reasons: list[str] = []

    egfr_v = vals.get("egfr", data.get("egfr"))
    ascvd_v = data.get("ascvd")
    diabetes_v = data.get("diabetes")
    a1c_v = vals.get("a1c", data.get("a1c"))
    bmi_v = vals.get("bmi", data.get("bmi"))
    sbp_v = vals.get("sbp", data.get("sbp"))
    bp_treated_v = data.get("bp_treated")

    if stage_num == 3:
        if ascvd_v is True or "ascvd" in driver:
            reasons.append("ASCVD is present")
        try:
            if (egfr_v is not None) and float(egfr_v) < 60:
                reasons.append(f"eGFR {int(round(float(egfr_v)))} (<60)")
        except Exception:
            pass
        if ckm_ctx.get("ckd_present") and not any("eGFR" in r for r in reasons):
            reasons.append(str(ckm_ctx.get("ckd_stage") or "CKD present"))

        if reasons:
            return "clinical disease layer: " + "; ".join(reasons)
        return "clinical disease layer is present"

    if stage_num == 2:
        if diabetes_v is True:
            reasons.append("diabetes = yes")
        try:
            if a1c_v is not None and float(a1c_v) >= 6.5:
                reasons.append(f"A1c {float(a1c_v):.1f}%")
            elif a1c_v is not None and float(a1c_v) >= 6.2:
                reasons.append(f"A1c {float(a1c_v):.1f}% (near diabetes threshold)")
        except Exception:
            pass
        if reasons:
            return "metabolic disease layer: " + "; ".join(reasons)
        return "metabolic disease layer is present"

    try:
        if bmi_v is not None and float(bmi_v) >= 30:
            reasons.append(f"BMI {float(bmi_v):.1f}")
    except Exception:
        pass

    try:
        if sbp_v is not None and float(sbp_v) >= 130:
            reasons.append(f"SBP {int(round(float(sbp_v)))}")
    except Exception:
        pass

    if bp_treated_v is True:
        reasons.append("BP treated")

    if str(ckm_ctx.get("metabolic_state") or "").lower() in ("prediabetes", "near diabetes threshold (6.2–6.4)"):
        reasons.append(str(ckm_ctx.get("metabolic_state")))

    try:
        if data.get("apob") is not None and float(data.get("apob")) > 0:
            reasons.append(f"ApoB {int(round(float(data.get('apob'))))}")
        elif data.get("ldl") is not None:
            reasons.append(f"LDL-C {int(round(float(data.get('ldl'))))}")
    except Exception:
        pass

    if reasons:
        return "risk-factor layer: " + "; ".join(reasons[:3])
    return "risk-factor layer is present"


def render_ckm_vertical_rail_html(active_stage: int | None) -> str:
    def stage_class(stage: int) -> str:
        return "ckm-stage is-active" if active_stage == stage else "ckm-stage"

    return f"""
<style>
  .ckm-card {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter,
                 "Helvetica Neue", Arial, sans-serif;
    border: 1px solid rgba(31,41,55,0.14);
    border-radius: 16px;
    background: linear-gradient(180deg, #ffffff 0%, #fbfbfc 100%);
    box-shadow: 0 10px 30px rgba(0,0,0,0.06);
    padding: 14px 16px;
    width: 230px;
    box-sizing: border-box;
  }}

  .ckm-header {{
    font-weight: 975;
    font-size: 0.96rem;
    letter-spacing: -0.01em;
    color: #111827;
    margin-bottom: 10px;
  }}

  .ckm-subheader {{
    font-size: 0.70rem;
    font-weight: 900;
    letter-spacing: 0.14em;
    color: rgba(31,41,55,0.55);
    margin-bottom: 12px;
    text-transform: uppercase;
  }}

  .ckm-stack {{
    display: flex;
    flex-direction: column;
    gap: 10px;
    position: relative;
    padding-left: 18px;
  }}

  .ckm-stack::before {{
    content: "";
    position: absolute;
    left: 6px;
    top: 8px;
    bottom: 8px;
    width: 2px;
    background: rgba(31,41,55,0.18);
    border-radius: 2px;
  }}

  .ckm-stage {{
    display: flex;
    gap: 10px;
    align-items: center;
    padding: 6px 8px;
    border-radius: 12px;
  }}

  .ckm-dot {{
    width: 12px;
    height: 12px;
    border-radius: 999px;
    border: 2px solid rgba(31,41,55,0.35);
    background: #ffffff;
    box-sizing: border-box;
    z-index: 1;
    flex-shrink: 0;
  }}

  .ckm-label {{
    display: flex;
    flex-direction: column;
    line-height: 1.2;
  }}

  .ckm-stage-name {{
    font-size: 0.86rem;
    font-weight: 900;
    color: rgba(31,41,55,0.70);
  }}

  .ckm-stage-desc {{
    font-size: 0.74rem;
    font-weight: 700;
    color: rgba(31,41,55,0.55);
    margin-top: 2px;
  }}

  .ckm-stage.is-active {{
    background: rgba(59,130,246,0.06);
    border: 1px solid rgba(59,130,246,0.22);
  }}

  .ckm-stage.is-active .ckm-dot {{
    border-color: rgba(59,130,246,0.85);
    background: rgba(59,130,246,0.85);
    box-shadow: 0 0 0 3px rgba(59,130,246,0.16);
  }}

  .ckm-stage.is-active .ckm-stage-name {{
    color: #111827;
    font-weight: 975;
  }}

  .ckm-stage.is-active .ckm-stage-desc {{
    color: rgba(31,41,55,0.80);
  }}
</style>

<div class="ckm-card" role="group" aria-label="Cardio-Kidney-Metabolic syndrome stage">
  <div class="ckm-header">Cardio-Kidney-Metabolic (CKM)</div>
  <div class="ckm-subheader">Syndrome stage</div>

  <div class="ckm-stack">
    <div class="{stage_class(3)}" title="Stage 3: Clinical cardiovascular disease, heart failure, or advanced CKD.">
      <div class="ckm-dot"></div>
      <div class="ckm-label">
        <div class="ckm-stage-name">Stage 3</div>
        <div class="ckm-stage-desc">Clinical disease / CKD</div>
      </div>
    </div>

    <div class="{stage_class(2)}" title="Stage 2: Metabolic disease (e.g., diabetes) accelerating risk independent of plaque burden.">
      <div class="ckm-dot"></div>
      <div class="ckm-label">
        <div class="ckm-stage-name">Stage 2</div>
        <div class="ckm-stage-desc">Metabolic disease</div>
      </div>
    </div>

    <div class="{stage_class(1)}" title="Stage 1: Risk factors such as obesity, elevated BP, or dysglycemia.">
      <div class="ckm-dot"></div>
      <div class="ckm-label">
        <div class="ckm-stage-name">Stage 1</div>
        <div class="ckm-stage-desc">Risk factors</div>
      </div>
    </div>

    <div class="{stage_class(0)}" title="Stage 0: No CKM drivers identified.">
      <div class="ckm-dot"></div>
      <div class="ckm-label">
        <div class="ckm-stage-name">Stage 0</div>
        <div class="ckm-stage-desc">None identified</div>
      </div>
    </div>
  </div>
</div>
"""

# ============================================================
# Tabs
# ============================================================
tab_report, tab_framework, tab_details = st.tabs(
    ["Report", "Decision Framework", "Details"]
)

# ------------------------------------------------------------
# REPORT TAB
# ------------------------------------------------------------
with tab_report:
    # --- CKM vertical rail + Risk Continuum bar + RSS (side-by-side) ---
    active_ckm_stage = _extract_ckm_stage_num(out)

    left, mid, right = st.columns([3.2, 1.25, 1.05], gap="small")

    with left:
        st.markdown(render_risk_continuum_bar(level, sub), unsafe_allow_html=True)

    with mid:
        components.html(render_rss_column_html(out), height=420)

    with right:
        components.html(render_ckm_vertical_rail_html(active_ckm_stage), height=360)

    stab_line = f"{decision_stability}" + (
        f" — {decision_stability_note}" if decision_stability_note else ""
    )

    # --- CKM inline line for Snapshot (engine-independent; derived from stage + eGFR) ---
    _egfr_v = None
    try:
        _egfr_v = float(data.get("egfr")) if data.get("egfr") is not None else None
    except Exception:
        _egfr_v = None

    _ckd_label = _format_ckd_stage_label_from_egfr(_egfr_v)

    _ckm_stage_num = active_ckm_stage  # already computed above via _extract_ckm_stage_num(out)

    _ckm_label = ""
    if _ckm_stage_num is None:
        _ckm_label = ""
    else:
        # Add "(CKD-driven risk)" only when CKM Stage 3 is paired with CKD stage ≥3a (eGFR < 60).
        _ckd_driven = False
        try:
            _ckd_driven = (_ckm_stage_num == 3) and (_egfr_v is not None) and (float(_egfr_v) < 60)
        except Exception:
            _ckd_driven = False

        _ckm_label = f"Stage {_ckm_stage_num}" + (" (CKD-driven risk)" if _ckd_driven else "")

    _ckm_stage_why = _ckm_stage_snapshot_explanation(_ckm_stage_num, ckm_copy, ckm_context, data)
    if _ckm_stage_why:
        _ckm_label = f"{_ckm_label} — {_ckm_stage_why}" if _ckm_label else ""

    # Show CKD label ONLY when eGFR < 60 (avoid noisy CKD2 alongside Stage 1)
    if not (_egfr_v is not None and float(_egfr_v) < 60):
        _ckd_label = ""

    _ckmckd_line = ""
    if _ckm_label and _ckd_label:
        _ckmckd_line = f"{_ckm_label} | {_ckd_label}"
    elif _ckm_label:
        _ckmckd_line = _ckm_label
    elif _ckd_label and _ckd_label != "CKD — unknown":
        _ckmckd_line = _ckd_label

    # Suppress CKM once plaque is assessed or posture is plaque-driven (Level 4+)
    try:
        _plaque_assessed = (plaque_present in (True, False)) or (int(level or 0) >= 4)
    except Exception:
        _plaque_assessed = (int(level or 0) >= 4)

    if _plaque_assessed:
        _ckmckd_line = ""

    st.markdown(
        f"""
<div class="block">
  <div class="block-title">Snapshot</div>

  <div class="kvline"><b>Level:</b>
    {level}{f" ({sub})" if sub else ""} — {LEVEL_NAMES.get(level,'—')}
  </div>

  {f"<div class='kvline'><b>CKM:</b> {_html.escape(_ckmckd_line)}</div>" if _ckmckd_line else ""}

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

# Tight criteria table (rings) + Where this patient falls
# Prefer engine-owned HTML, but fall back to in-app renderers if missing.
_ins = (out.get("insights") or {})
if not isinstance(_ins, dict):
    _ins = {}
    out["insights"] = _ins

# If an adapter layer stripped engine-owned HTML/version, rehydrate from le.evaluate(patient) (only when missing).
_need_criteria = not bool((_ins.get("criteria_table_html") or "").strip())
_need_falls = not bool((_ins.get("where_patient_falls_html") or "").strip())
_need_version = not bool(out.get("version"))

if _need_criteria or _need_falls or _need_version:
    try:
        _engine_out = le.evaluate(patient)
        if isinstance(_engine_out, dict):
            _engine_ins = _engine_out.get("insights") or {}
            if isinstance(_engine_ins, dict):
                if _need_criteria:
                    _ins["criteria_table_html"] = str(_engine_ins.get("criteria_table_html") or "")
                if _need_falls:
                    _ins["where_patient_falls_html"] = str(_engine_ins.get("where_patient_falls_html") or "")
            if _need_version:
                _v = _engine_out.get("version")
                out["version"] = _v if isinstance(_v, dict) else {}
    except Exception:
        # Silent: do not break report rendering
        pass

def _call_with_supported_kwargs(fn, kwargs: dict):
    import inspect

    sig = inspect.signature(fn)
    params = sig.parameters
    accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    if accepts_var_kw:
        return fn(**kwargs)

    filtered = {k: v for k, v in kwargs.items() if k in params}
    return fn(**filtered)

_criteria_html = (_ins.get("criteria_table_html") or "").strip()

if _criteria_html:
    st.markdown(_criteria_html, unsafe_allow_html=True)
else:
    # Fallback renderer (older path) — safe kw filtering prevents TypeError drift.
    _kw = {
        "apob_v": data.get("apob"),
        "ldl_v": data.get("ldl"),
        "nonhdl_v": data.get("nonhdl"),
        "hdl_v": data.get("hdl"),
        "tc_v": data.get("tc"),
        "tg_v": data.get("tg"),
        "a1c_v": data.get("a1c"),
        "sbp_v": data.get("sbp"),
        "dbp_v": data.get("dbp"),
        "egfr_v": data.get("egfr"),
        "uacr_v": data.get("uacr"),
        "bmi_v": data.get("bmi"),
        "diabetes_v": bool(data.get("diabetes")),
        "htn_v": bool(data.get("htn")),
        "smoker_v": bool(data.get("smoker")),
        "level": level,
        "sub": sub,
        "out": out,
        "ev": ev,
        "data": data,
    }
    try:
        if "render_criteria_table_compact" in globals() and callable(globals()["render_criteria_table_compact"]):
            _html_out = _call_with_supported_kwargs(globals()["render_criteria_table_compact"], _kw)
            if isinstance(_html_out, str) and _html_out.strip():
                st.markdown(_html_out, unsafe_allow_html=True)
            else:
                st.markdown(
                    "<div class='compact-caption'>Criteria table unavailable (renderer returned empty).</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                "<div class='compact-caption'>Criteria table unavailable (renderer function not found).</div>",
                unsafe_allow_html=True,
            )
    except Exception as _e:
        st.markdown(
            "<div class='compact-caption'>Criteria table unavailable (fallback renderer error).</div>",
            unsafe_allow_html=True,
        )
        st.exception(_e)

# NOTE: Second table intentionally suppressed (do not render where_patient_falls_html).
# (It can still exist in out["insights"] for debugging or future use.)

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

# PCE vs PREVENT divergence (engine-gated)
rmm = (out.get("insights") or {}).get("risk_model_mismatch") or {}
if rmm.get("status") == "ok" and bool(rmm.get("should_surface")):
    rmm_label = _html.escape(str(rmm.get("label") or "Model divergence"))
    try:
        _delta = abs(float(rmm.get("delta_points")))
        rmm_delta_line = f"Absolute difference: {_delta:.1f} percentage points"
    except Exception:
        rmm_delta_line = ""
    rmm_detail = _html.escape(str(rmm.get("explainer_clinical") or ""))

    st.markdown(
        f"""
<div class="block compact">
  <div class="block-title compact">Risk model alignment (PCE vs PREVENT)</div>
  <div class="kvline compact">{rmm_label}</div>
  {f"<div class='kvline compact inline-muted'>{_html.escape(rmm_delta_line)}</div>" if rmm_delta_line else ""}
  {f"<div class='kvline compact inline-muted'>{rmm_detail}</div>" if rmm_detail else ""}
</div>
""",
        unsafe_allow_html=True,
    )

# Structural clarification (engine-gated)
struct_clar = (out.get("insights") or {}).get("structural_clarification")
if str(struct_clar or "").strip():
    st.markdown(
        f"""
<div class="block compact">
  <div class="block-title compact">Structural clarification</div>
  <div class="kvline compact">{_html.escape(str(struct_clar))}</div>
</div>
""",
        unsafe_allow_html=True,
    )

# CKM/CKD context (engine-gated; display-only)
if ckm_copy.get("headline") or ckd_copy.get("headline"):
    st.markdown(
        f"""
<div class="block compact">
  <div class="block-title compact">CKM/CKD context</div>
  {f"<div class='kvline compact'>{_html.escape(ckm_copy.get('headline',''))}</div>" if ckm_copy.get("headline") else ""}
  {f"<div class='kvline compact inline-muted'>{_html.escape(ckm_copy.get('detail',''))}</div>" if ckm_copy.get("detail") else ""}
  {f"<div class='kvline compact'>{_html.escape(ckd_copy.get('headline',''))}</div>" if ckd_copy.get("headline") else ""}
  {f"<div class='kvline compact inline-muted'>{_html.escape(ckd_copy.get('detail',''))}</div>" if ckd_copy.get("detail") else ""}
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
    cac_head_raw = str(cac_copy.get("headline") or "Coronary calcium: —").strip()
    cac_head_raw = re.sub(r"(?i)^\s*coronary\s+calcium\s*:\s*", "", cac_head_raw)
    # Action card is intentionally concise: keep core meaning, drop explanatory parenthetical.
    cac_head_raw = cac_head_raw.replace(" (not a treatment escalation)", "")
    cac_head = _html.escape(cac_head_raw)
    cac_det = _html.escape(cac_copy.get("detail") or "")
    cac_ref = _html.escape(cac_copy.get("referral") or "")

    cac_block = (
        f"<div class='kvline compact'>{cac_head}</div>"
        + (f"<div class='kvline compact inline-muted'>{cac_det}</div>" if cac_det else "")
        + (f"<div class='kvline compact inline-muted'>{cac_ref}</div>" if cac_ref else "")
    )

    asp_copy = (out.get("insights") or {}).get("aspirin_copy") or {}
    asp_head_raw = str(asp_copy.get("headline") or f"Aspirin: {asp_line}").strip()
    asp_head_raw = re.sub(r"(?i)^\s*aspirin\s*:\s*", "", asp_head_raw)
    asp_head = _html.escape(asp_head_raw)

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

# Ensure rec_action exists here (Action card computes it too, but later)
rec_action = recommended_action_line_unified(out, fallback=plan_clean)

note_for_emr = ""
_note_err = None

# 1) Try to render from the current (possibly v4-adapted) output
try:
    note_for_emr = le.render_quick_text(patient, out) or ""
except Exception as _e:
    _note_err = _e
    note_for_emr = ""

# 2) If empty or failed, rehydrate from the legacy engine output (same strategy as tables)
if not str(note_for_emr).strip():
    try:
        _engine_out_for_note = le.evaluate(patient)
        note_for_emr = le.render_quick_text(patient, _engine_out_for_note) or ""
    except Exception as _e2:
        _note_err = _note_err or _e2
        note_for_emr = ""

# 3) Final formatting + unified Management line injection
note_for_emr = scrub_terms(note_for_emr)
note_for_emr = _inject_management_line_into_note(note_for_emr, rec_action)
note_for_emr = _tidy_emr_plan_section(note_for_emr)

# 4) Fallback visibility if still empty (do not break rendering)
if not str(note_for_emr).strip():
    st.markdown(
        "<div class='compact-caption'>EMR note unavailable (render_quick_text returned empty).</div>",
        unsafe_allow_html=True,
    )
    if _note_err is not None:
        st.exception(_note_err)

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
# Footer
# ------------------------------------------------------------
st.caption(
    f"Versions: {VERSION.get('levels','')} | {VERSION.get('riskSignal','')} | "
    f"{VERSION.get('riskCalc','')} | {VERSION.get('aspirin','')} | "
    f"{VERSION.get('prevent','')}. No storage intended."
)













































































































































