from __future__ import annotations

from typing import Any, Dict, List
import html


def _esc(x: Any) -> str:
    return html.escape(str(x), quote=True)


def render_rss_column_html(out: Dict[str, Any]) -> str:
    """
    RSS tower only (render-only).
    Requires engine to provide:
      out["riskSignal"]["score"], ["band"], and ["components"] list of {label, points}.
    """
    rs = (out or {}).get("riskSignal") or {}
    score = rs.get("score", None)
    band = rs.get("band", "—")
    comps_raw = rs.get("components") or []

    # Normalize components
    comps: List[Dict[str, Any]] = []
    total_points = 0
    for c in comps_raw:
        if not isinstance(c, dict):
            continue
        label = str(c.get("label") or "").strip()
        pts = c.get("points", 0)
        try:
            pts_i = int(round(float(pts)))
        except Exception:
            pts_i = 0
        if pts_i < 0:
            pts_i = 0
        if not label:
            continue
        comps.append({"label": label, "points": pts_i})
        total_points += pts_i

    # Prefer engine total score if valid, otherwise fall back to sum of components (clamped)
    score_i = None
    try:
        score_i = int(round(float(score)))
    except Exception:
        score_i = None

    if score_i is None:
        score_i = max(0, min(100, int(total_points)))
    else:
        score_i = max(0, min(100, int(score_i)))

    # If no components, show a strict, non-misleading empty state
    if not comps:
        return f"""
<style>
  .rssT-wrap {{
    border: 1px solid rgba(31,41,55,0.14);
    border-radius: 16px;
    background: #ffffff;
    box-shadow: 0 10px 30px rgba(0,0,0,0.06);
    padding: 14px 14px;
  }}
  .rssT-title {{
    font-variant-caps: all-small-caps;
    letter-spacing: 0.14em;
    font-weight: 975;
    font-size: 0.98rem;
    color: rgba(17,24,39,0.90);
    margin-bottom: 6px;
  }}
  .rssT-note {{
    color: rgba(31,41,55,0.72);
    font-size: 0.86rem;
    line-height: 1.25;
  }}
</style>
<div class="rssT-wrap">
  <div class="rssT-title">Risk Signal Score (RSS)</div>
  <div class="rssT-note">Tower unavailable (RSS components not provided by engine).</div>
</div>
""".strip()

    # Tower rendering: top-to-bottom stacking, heights proportional to points
    # Compute segment heights in percent of tower height (100 = full height)
    # We only stack up to 100 points visually. If sum >100, we clamp display but keep labels.
    remaining = 100
    segs: List[Dict[str, Any]] = []
    for c in comps:
        pts = int(c["points"])
        show_pts = min(pts, remaining) if remaining > 0 else 0
        remaining -= show_pts
        segs.append({"label": c["label"], "points": pts, "show_points": show_pts})

    # Build segment divs from bottom to top
    # We generate in reverse so first segments end up at bottom visually
    seg_divs = ""
    for s in reversed(segs):
        h = max(0, min(100, int(s["show_points"])))
        if h <= 0:
            continue
        seg_divs += f"""
<div class="rssT-seg" style="height:{h}%" title="{_esc(s['label'])}: {_esc(s['points'])} points">
  <div class="rssT-seg-label">{_esc(s['label'])}</div>
  <div class="rssT-seg-pts">{_esc(s['points'])}</div>
</div>
""".strip()

    # Legend list (still tower-only: labels + points; no status/basis/missing)
    legend_items = ""
    for s in segs:
        legend_items += f"""
<div class="rssT-legend-row">
  <div class="rssT-legend-label">{_esc(s['label'])}</div>
  <div class="rssT-legend-pts">{_esc(s['points'])}</div>
</div>
""".strip()

    return f"""
<style>
  .rssT-wrap {{
    border: 1px solid rgba(31,41,55,0.14);
    border-radius: 16px;
    background: linear-gradient(180deg, #ffffff 0%, #fbfbfc 100%);
    box-shadow: 0 10px 30px rgba(0,0,0,0.06);
    padding: 14px 14px;
  }}

  .rssT-head {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 8px;
  }}

  .rssT-title {{
    font-variant-caps: all-small-caps;
    letter-spacing: 0.14em;
    font-weight: 975;
    font-size: 0.98rem;
    color: rgba(17,24,39,0.90);
  }}

  .rssT-chip {{
    font-weight: 950;
    font-size: 0.86rem;
    padding: 3px 10px;
    border-radius: 999px;
    border: 1px solid rgba(31,41,55,0.14);
    background: rgba(59,130,246,0.06);
    color: rgba(17,24,39,0.92);
    white-space: nowrap;
  }}

  .rssT-score {{
    margin-top: 2px;
    font-weight: 975;
    font-size: 2.0rem;
    line-height: 1.0;
    color: #111827;
  }}

  .rssT-score small {{
    font-weight: 900;
    font-size: 0.9rem;
    color: rgba(31,41,55,0.62);
    margin-left: 6px;
  }}

  .rssT-body {{
    display: grid;
    grid-template-columns: 0.9fr 1.1fr;
    gap: 12px;
    align-items: start;
    margin-top: 10px;
  }}

  .rssT-tower {{
    height: 260px;
    border-radius: 12px;
    border: 1px solid rgba(31,41,55,0.14);
    background: #ffffff;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
  }}

  .rssT-seg {{
    width: 100%;
    border-top: 1px solid rgba(31,41,55,0.10);
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 10px;
    box-sizing: border-box;
    background: rgba(59,130,246,0.10);
  }}

  .rssT-seg-label {{
    font-size: 0.82rem;
    font-weight: 900;
    color: rgba(17,24,39,0.88);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 170px;
  }}

  .rssT-seg-pts {{
    font-size: 0.82rem;
    font-weight: 950;
    color: rgba(31,41,55,0.78);
    margin-left: 10px;
  }}

  .rssT-legend {{
    border: 1px solid rgba(31,41,55,0.10);
    border-radius: 12px;
    background: #ffffff;
    padding: 10px 10px;
  }}

  .rssT-legend-title {{
    font-variant-caps: all-small-caps;
    letter-spacing: 0.10em;
    font-weight: 975;
    font-size: 0.82rem;
    color: rgba(17,24,39,0.82);
    margin-bottom: 8px;
  }}

  .rssT-legend-row {{
    display: flex;
    justify-content: space-between;
    gap: 10px;
    padding: 6px 0;
    border-bottom: 1px solid rgba(31,41,55,0.06);
  }}

  .rssT-legend-row:last-child {{
    border-bottom: 0;
  }}

  .rssT-legend-label {{
    font-size: 0.84rem;
    color: rgba(17,24,39,0.86);
    font-weight: 900;
  }}

  .rssT-legend-pts {{
    font-size: 0.84rem;
    color: rgba(31,41,55,0.72);
    font-weight: 950;
  }}
</style>

<div class="rssT-wrap">
  <div class="rssT-head">
    <div class="rssT-title">Risk Signal Score (RSS)</div>
    <div class="rssT-chip">{_esc(band)}</div>
  </div>

  <div class="rssT-score">{_esc(score_i)}<small>/100</small></div>

  <div class="rssT-body">
    <div class="rssT-tower">
      {seg_divs}
    </div>

    <div class="rssT-legend">
      <div class="rssT-legend-title">Point contributors</div>
      {legend_items}
    </div>
  </div>
</div>
""".strip()

