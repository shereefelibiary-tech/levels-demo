def render_rss_column_html(out: dict) -> str:
    """
    RSS column (engine-owned values; UI-only rendering).
    Shows: RSS score/band + basis + completeness + missing clarifiers.
    Safe: does not infer, does not recompute, does not change actions.
    """
    rs = (out or {}).get("riskSignal") or {}
    score = rs.get("score", "—")
    band = rs.get("band", "—")
    note = (rs.get("note") or "").strip()

    basis = (rs.get("basis") or "Unknown").strip()
    is_complete = bool(rs.get("is_complete") is True)
    plaque_assessed = bool(rs.get("plaque_assessed") is True)
    missing = rs.get("missing") or []
    missing = [str(x).strip() for x in missing if str(x).strip()]

    # Title line
    title = "Risk Signal Score (RSS)"
    subtitle = "Biologic + plaque signal (not event probability)."

    # Completeness language (locked, non-judgmental)
    if is_complete and plaque_assessed:
        comp_line = "Status: Complete (tracking-ready) • Plaque assessed"
    elif is_complete and (not plaque_assessed):
        comp_line = "Status: Complete (tracking-ready) • Plaque unmeasured"
    else:
        comp_line = "Status: Provisional (key clarifiers missing)"

    # Basis line (prevents LDL→ApoB confusion)
    if basis == "ApoB":
        basis_line = "Basis: ApoB (preferred marker)"
    elif basis == "LDL":
        basis_line = "Basis: LDL-C (ApoB unmeasured)"
    else:
        basis_line = "Basis: Unknown (ApoB/LDL unavailable)"

    # Missing clarifiers list (only if present)
    missing_html = ""
    if missing:
        # Keep it tight; users see this as a checklist
        items = "".join(f"<li>{_html_escape(m)}</li>" for m in missing)
        missing_html = f"""
<div class="rss-subhead">Missing clarifiers</div>
<ul class="rss-list">{items}</ul>
""".strip()

    # Score display (big number + /100)
    score_disp = _html_escape(str(score))
    band_disp = _html_escape(str(band))
    note_disp = _html_escape(note or subtitle)

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
  <div class="rss-title">{_html_escape(title)}</div>

  <div class="rss-score-row">
    <div>
      <span class="rss-score">{score_disp}</span>
      <span class="rss-outof">/100</span>
    </div>
    <div class="rss-band">{band_disp}</div>
  </div>

  <div class="rss-note">{note_disp}</div>

  <div class="rss-meta"><b>{_html_escape(comp_line)}</b></div>
  <div class="rss-meta">{_html_escape(basis_line)}</div>

  {missing_html}
</div>
""".strip()


def _html_escape(s: str) -> str:
    import html
    return html.escape(str(s), quote=True)
