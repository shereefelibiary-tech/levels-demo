from __future__ import annotations

from typing import Any, Dict, List
import html


def _esc(x: Any) -> str:
    return html.escape(str(x), quote=True)


def render_rss_column_html(out: Dict[str, Any]) -> str:
    """
    RSS tower only (render-only).
    Requires engine to provide:
      out["riskSignal"]["score"], ["band"], and ["components"] list of {key,label,points}.
    """
    rs = (out or {}).get("riskSignal") or {}
    score = rs.get("score", None)
    band = rs.get("band", "—")
    comps_raw = rs.get("components") or []

    # Color mapping by engine-owned key (stable, no drift)
    color_by_key = {
        "burden": "#b91c1c",        # red
        "athero": "#2563eb",        # blue
        "genetics": "#7c3aed",      # purple
        "inflammation": "#f59e0b",  # amber
        "metabolic": "#16a34a",     # green
    }

    # Normalize components
    comps: List[Dict[str, Any]] = []
    total_points = 0
    for c in comps_raw:
        if not isinstance(c, dict):
            continue
        key = str(c.get("key") or "").strip()
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
        comps.append({"key": key, "label": label, "points": pts_i})
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

    if not comps:
        return f"""
<div style="border:1px solid rgba(31,41,55,0.14); border-radius:16px; background:#fff; padding:14px;">
  <div style="font-variant-caps:all-small-caps; letter-spacing:0.14em; font-weight:975;">
    Risk Signal Score (RSS)
  </div>
  <div style="margin-top:8px; color:rgba(31,41,55,0.72); font-size:0.9rem;">
    Tower unavailable (RSS components not provided by engine).
  </div>
</div>
""".strip()

    # Tower geometry
    tower_height_px = 260
    min_seg_px = 14  # ensures small point segments are still visible/clickable

    # Use display points capped at 100 (visual scale)
    remaining = 100
    segs: List[Dict[str, Any]] = []
    for c in comps:
        pts = int(c["points"])
        show_pts = min(pts, remaining) if remaining > 0 else 0
        remaining -= show_pts
        segs.append(
            {
                "key": c.get("key") or "",
                "label": c["label"],
                "points": pts,
                "show_points": show_pts,
                "color": color_by_key.get(c.get("key") or "", "#64748b"),  # slate fallback
            }
        )

    # Convert show_points -> pixels. Guarantee min pixel height for non-zero show_points.
    # If min heights overflow the tower, we scale them down proportionally.
    raw_px = []
    for s in segs:
        if s["show_points"] <= 0:
            raw_px.append(0)
        else:
            px = int(round((s["show_points"] / 100.0) * tower_height_px))
            raw_px.append(max(px, min_seg_px))

    sum_px = sum(raw_px)
    if sum_px > tower_height_px and sum_px > 0:
        scale = tower_height_px / float(sum_px)
        raw_px = [int(max(1, round(px * scale))) if px > 0 else 0 for px in raw_px]

    # Build segment divs from bottom to top
    seg_divs = ""
    for s, px in zip(reversed(segs), reversed(raw_px)):
        if px <= 0:
            continue
        seg_divs += f"""
<div class="rssT-seg" style="height:{px}px; background:{_esc(s['color'])};"
     title="{_esc(s['label'])}: {_esc(s['points'])} points">
    <div class="rssT-seg-pts">{_esc(s['points'])}</div>

</div>
""".strip()

    # Legend list (tower-only)
    legend_items = ""
    for s in segs:
        swatch = f"<span class='rssT-swatch' style='background:{_esc(s['color'])};'></span>"
        legend_items += f"""
<div class="rssT-legend-row">
  <div class="rssT-legend-left">{swatch}<span>{_esc(s['label'])}</span></div>
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
    margin-bottom: 6px;
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
    grid-template-columns: 0.95fr 1.05fr;
    gap: 12px;
    align-items: start;
    margin-top: 10px;
  }}

  .rssT-tower {{
    height: {tower_height_px}px;
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
    border-top: 1px solid rgba(255,255,255,0.35);
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 10px;
    box-sizing: border-box;
  }}

  .rssT-seg-label {{
    font-size: 0.82rem;
    font-weight: 950;
    color: rgba(255,255,255,0.95);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 175px;
    text-shadow: 0 1px 0 rgba(0,0,0,0.15);
  }}

  .rssT-seg-pts {{
    font-size: 0.82rem;
    font-weight: 950;
    color: rgba(255,255,255,0.95);
    margin-left: 10px;
    text-shadow: 0 1px 0 rgba(0,0,0,0.15);
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
    align-items: center;
  }}

  .rssT-legend-row:last-child {{
    border-bottom: 0;
  }}

  .rssT-legend-left {{
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.84rem;
    color: rgba(17,24,39,0.86);
    font-weight: 900;
    min-width: 0;
  }}

  .rssT-swatch {{
    width: 12px;
    height: 12px;
    border-radius: 3px;
    border: 1px solid rgba(31,41,55,0.12);
    flex: 0 0 auto;
  }}

  .rssT-legend-pts {{
    font-size: 0.84rem;
    color: rgba(31,41,55,0.72);
    font-weight: 950;
    flex: 0 0 auto;
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


