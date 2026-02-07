from __future__ import annotations

from typing import Any, Dict, List
import html


def _esc(x: Any) -> str:
    return html.escape(str(x), quote=True)


def render_rss_column_html(out: Dict[str, Any]) -> str:
    """
    RSS column (render-only).
    Uses engine-owned values: riskSignal.score/band/note + basis/is_complete/missing/plaque_assessed.
    Does not recompute RSS and does not infer actions.
    """
    rs = (out or {}).get("riskSignal") or {}

    score = rs.get("score", "—")
    band = rs.get("band", "—")
    note = str(rs.get("note") or "").strip() or "Biologic + plaque signal (not event probability)."

    basis = str(rs.get("basis") or "Unknown").strip()
    is_complete = bool(rs.get("is_complete") is True)
    plaque_assessed = bool(rs.get("plaque_assessed") is True)

    missing_raw = rs.get("missing") or []
    missing: List[str] = [str(x).strip() for x in missing_raw if str(x).strip()]

    # Status line (locked)
    if is_complete and plaque_assessed:
        status_line = "Status: Complete (tracking-ready) • Plaque assessed"
    elif is_complete and (not plaque_assessed):
        status_line = "Status: Complete (tracking-ready) • Plaque unmeasured"
    else:
        status_line = "Status: Provisional (key clarifiers missing)"

    # Basis line (prevents LDL→ApoB confusion)
    if basis == "ApoB":
        basis_line = "Basis: ApoB (preferred marker)"
    elif basis == "LDL":
        basis_line = "Basis: LDL-C (ApoB unmeasured)"
    else:
        basis_line = "Basis: Unknown (ApoB/LDL unavailable)"

    missing_html = ""
    if missing:
        items = "".join(f"<li>{_esc(m)}</li>" for m in missing)
        missing_html = f"""
<div class="rss-subhead">Missing clarifiers</div>
<ul class="rss-list">{items}</ul>
""".strip()

    return f"""
<style>
  .rss-card {{
    border: 1px solid rgba(31,41,55,0.14);
    border-radius: 16px;
    background: linear-gradient(180deg, #ffffff 0%, #fbfbfc 100%);
    box-shadow: 0 10px 30px rgba(0,0,0,0.06);
    padding: 14px 14px;
    margin-top: 0px;
  }}
  .rss-title {{
    font-variant-caps: all-small-caps;
    letter-spacing: 0.14em;
    font-weight: 975;
    font-size: 0.98rem;
    color: rgba(17,24,39,0.90);
    margin-bottom: 6px;
  }}
  .rss-score-row {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
    margin: 6px 0 10px 0;
  }}
  .rss-score {{
    font-weight: 975;
    font-size: 2.2rem;
    color: #111827;
    line-height: 1.0;
  }}
  .rss-outof {{
    font-weight: 900;
    font-size: 0.95rem;
    color: rgba(31,41,55,0.62);
    margin-left: 6px;
  }}
  .rss-band {{
    font-weight: 950;
    font-size: 0.92rem;
    padding: 4px 10px;
    border-radius: 999px;
    border: 1px solid rgba(31,41,55,0.14);
    background: rgba(59,130,246,0.06);
    color: rgba(17,24,39,0.92);
    white-space: nowrap;
  }}
  .rss-note {{
    color: rgba(31,41,55,0.70);
    font-size: 0.86rem;
    line-height: 1.25;
    margin-bottom: 10px;
  }}
  .rss-meta {{
    color: rgba(31,41,55,0.70);
    font-size: 0.84rem;
    line-height: 1.25;
    margin-bottom: 8px;
  }}
  .rss-meta b {{
    color: rgba(17,24,39,0.85);
    font-weight: 950;
  }}
  .rss-subhead {{
    margin-top: 8px;
    font-weight: 950;
    font-size: 0.82rem;
    color: rgba(17,24,39,0.80);
    letter-spacing: 0.06em;
    font-variant-caps: all-small-caps;
  }}
  .rss-list {{
    margin: 6px 0 0 18px;
    padding: 0;
    color: rgba(31,41,55,0.72);
    font-size: 0.84rem;
    line-height: 1.25;
  }}
</style>

<div class="rss-card">
  <div class="rss-title">Risk Signal Score (RSS)</div>

  <div class="rss-score-row">
    <div>
      <span class="rss-score">{_esc(score)}</span>
      <span class="rss-outof">/100</span>
    </div>
    <div class="rss-band">{_esc(band)}</div>
  </div>

  <div class="rss-note">{_esc(note)}</div>

  <div class="rss-meta"><b>{_esc(status_line)}</b></div>
  <div class="rss-meta">{_esc(basis_line)}</div>

  {missing_html}
</div>
""".strip()
