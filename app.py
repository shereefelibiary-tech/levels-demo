import json
import re
import streamlit as st
from typing import Dict, Any, List, Optional

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
    r

