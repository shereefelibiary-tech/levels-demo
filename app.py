import json
import re
import streamlit as st

from smartphrase_ingest.parser import parse_smartphrase
from levels_engine import Patient, evaluate, render_compact_text, render_full_text, VERSION, short_why

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
  font-size: 1.10rem;
  font-weight: 900;
  margin: 0 0 10px 0;
}

.section { margin-top: 12px; }
.section-title {
  font-variant-caps: all-small-caps;
  letter-spacing: 0.08em;
  font-weight: 900;
  font-size: 0.82rem;
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

.crit {
  display:flex; gap:8px; flex-wrap:wrap;
  margin-top: 8px;
}
.crit-pill {
  display:inline-block;
  padding:6px 10px;
  border-radius: 999px;
  border:1px solid rgba(31,41,55,0.14);
  background:#fff;
  font-size:0.85rem;
  font-weight:800;
}
.crit-ok { border-color: rgba(16,185,129,0.35); background: rgba(16,185,129,0.08); }
.crit-miss { border-color: rgba(245,158,11,0.35); background: rgba(245,158,11,0.10); }

</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    f"""
<div class="header-card">
  <div class="header-title">LEVELS™ {VERSION["levels"]} — De-identified Demo</div>
  <p class="header-sub">SmartPhrase paste → auto-fill • compact professional output • no storage intended</p>
</div>
""",
    unsafe_allow_html=True,
)

st.info("De-identified use only. Do not enter patient identifiers.")

# ============================================================
# Reset button (robust callback-based)
# ============================================================
def reset_form_state():
    # Remove all non-internal keys safely
    for k in list(st.session_state.keys()):
        if k.startswith("_"):
            continue
        del st.session_state[k]
    st.session_state["_reset_done"] = True

top_c1, top_c2 = st.columns([1, 4])
with top_c1:
    st.button("Reset form", type="secondary", on_click=reset_form_state)
with top_c2:
    st.caption("Tip: if a widget ever looks wrong after an update, click Reset form.")

if st.session_state.get("_reset_done"):
    st.success("Form reset.")
    del st.session_state["_reset_done"]

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
    return any(re.search(pat, s, re.IGNORECASE) for pat in PHI_PATTERNS)

# ============================================================
# Parsing enhancements (parser + regex fallback)
# ============================================================
def _rx_first(patterns: List[str], text: str, flags=re.IGNORECASE):
    for pat in patterns:
        m = re.search(pat, text, flags)
        if m:
            return m
    return None

def _to_int(x) -> Optional[int]:
    try:
        return int(round(float(str(x).strip())))
    except:
        return None

def _to_float(x) -> Optional[float]:
    try:
        return float(str(x).strip())
    except:
        return None

def regex_extract_smartphrase(text: str) -> Dict[str, Any]:
    """
    Backup extractor for common Epic-ish text formats.
    Only returns keys it confidently finds.
    """
    t = text or ""
    out: Dict[str, Any] = {}

    # Age
    m = _rx_first([r"\bAGE[:\s]+(\d{2,3})\b", r"\b(\d{2,3})\s*y/?o\b", r"\bAge\s+(\d{2,3})\b"], t)
    if m: out["age"] = _to_int(m.group(1))

    # Sex
    m = _rx_first([r"\bSEX[:\s]+(M|F)\b", r"\b(\d{2,3})\s*(M|F)\b", r"\b(\d{2,3})\s*(male|female)\b"], t)
    if m:
        sx = m.group(1) if len(m.groups()) == 1 else m.group(len(m.groups()))
        out["sex"] = str(sx).strip().upper()[0]

    # Race (only Black vs other)
    if re.search(r"\bblack\b|\bafrican[-\s]?american\b", t, re.IGNORECASE):
        out["africanAmerican"] = True

    # SBP (try explicit, then BP 128/78)
    m = _rx_first([r"\bSBP[:\s]+(\d{2,3})\b", r"\bSystolic\s*BP[:\s]+(\d{2,3})\b"], t)
    if m:
        out["sbp"] = _to_int(m.group(1))
    else:
        m2 = _rx_first([r"\bBP[:\s]+(\d{2,3})\s*/\s*\d{2,3}\b", r"\b(\d{2,3})\s*/\s*\d{2,3}\b"], t)
        if m2:
            out["sbp"] = _to_int(m2.group(1))

    # Lipids
    m = _rx_first([r"\b(TC|TOTAL\s*CHOLESTEROL)[:\s]+(\d{2,3})\b", r"\bTotal\s*Cholesterol[:\s]+(\d{2,3})\b"], t)
    if m:
        out["tc"] = _to_int(m.group(m.lastindex))

    m = _rx_first([r"\bHDL[:\s]+(\d{2,3})\b"], t)
    if m:
        out["hdl"] = _to_int(m.group(1))

    m = _rx_first([r"\bLDL[-\s]*C?\b[:\s]+(\d{2,3})\b", r"\bLDL\b[:\s]+(\d{2,3})\b"], t)
    if m:
        out["ldl"] = _to_int(m.group(1))

    m = _rx_first([r"\bApoB\b[:\s]+(\d{2,3})\b", r"\bAPOB\b[:\s]+(\d{2,3})\b"], t)
    if m:
        out["apob"] = _to_int(m.group(1))

    # Lp(a) and units
    m = _rx_first([r"\bLp\(a\)\b[:\s]+([\d.]+)\s*(nmol/L|mg/dL)?", r"\bLPA\b[:\s]+([\d.]+)\s*(nmol/L|mg/dL)?"], t)
    if m:
        out["lpa"] = _to_int(m.group(1))
        unit = m.group(2)
        if unit:
            out["lpa_unit"] = unit

    # Explicit unit line
    m = _rx_first([r"\bLPA\s*UNIT[:\s]+(nmol/L|mg/dL)\b", r"\bLp\(a\)\s*unit[:\s]+(nmol/L|mg/dL)\b"], t)
    if m:
        out["lpa_unit"] = m.group(1)

    # Calcium Score (CAC)
    m = _rx_first([
        r"\bCALCIUM\s*SCORE[:\s]+(\d{1,4})\b",
        r"\bCoronary.*Calcium.*[:=]\s*(\d{1,4})\b",
        r"\bCAC\b[:=\s]+(\d{1,4})\b",
        r"\bAgatston[:\s]+(\d{1,4})\b",
    ], t)
    if m:
        out["cac"] = _to_int(m.group(1))

    # ASCVD 10y (if present)
    m = _rx_first([r"\bASCVD\s*10[-\s]*year[:\s]+([\d.]+)\s*%?", r"\b10[-\s]*year\s*ASCVD\s*risk[:\s]+([\d.]+)\s*%?"], t)
    if m:
        out["ascvd_10y"] = _to_float(m.group(1))

    # A1c
    m = _rx_first([r"\bA1C\b[:\s]+([\d.]+)\b", r"\bHbA1c\b[:\s]+([\d.]+)\b"], t)
    if m:
        out["a1c"] = _to_float(m.group(1))

    # hsCRP
    m = _rx_first([r"\bhs\s*CRP\b[:\s]+([\d.]+)\b", r"\bhscrp\b[:\s]+([\d.]+)\b"], t)
    if m:
        out["hscrp"] = _to_float(m.group(1))

    # Smoker / diabetes / BP treated (very light heuristics)
    if re.search(r"\b(smoker|smoking)\b.*\b(yes|current)\b", t, re.IGNORECASE):
        out["smoker"] = True
    elif re.search(r"\bnon[-\s]?smoker\b|\bdenies smoking\b", t, re.IGNORECASE):
        out["smoker"] = False

    if re.search(r"\bdiabetes\b.*\b(yes|type\s*2|t2)\b", t, re.IGNORECASE):
        out["diabetes"] = True
    elif re.search(r"\bno (known )?diabetes\b|\bdenies diabetes\b", t, re.IGNORECASE):
        out["diabetes"] = False

    if re.search(r"\b(on|takes)\b.*\b(bp meds|antihypertensive|amlodipine|lisinopril|losartan|valsartan|hctz|chlorthalidone|metoprolol)\b", t, re.IGNORECASE):
        out["bpTreated"] = True
    elif re.search(r"\bnot on bp meds\b|\bno bp meds\b", t, re.IGNORECASE):
        out["bpTreated"] = False

    # Clean None
    return {k: v for k, v in out.items() if v is not None}

def merged_parse(text: str) -> Dict[str, Any]:
    """
    Merge parse_smartphrase() + regex fallback.
    Parser wins; regex fills missing.
    """
    base = parse_smartphrase(text or "") if (text or "").strip() else {}
    fallback = regex_extract_smartphrase(text or "")
    merged = dict(fallback)
    merged.update({k: v for k, v in base.items() if v is not None})
    return merged

# ==========

