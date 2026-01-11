# ui_components.py

def render_management_bar(level: int, sublevel: str | None = None) -> str:
    """
    5-step Management Level bar with clinician-native labels.
    """
    lvl = max(0, min(5, int(level or 0)))

    labels = {
        1: "Minimal risk",
        2: "Emerging risk",
        3: "High biologic risk",
        4: "Subclinical atherosclerosis",
        5: "Atherosclerosis",
    }

    segs = []
    for i in range(1, 6):
        active = (i == lvl)
        segs.append(f"""
        <div style="
            flex:1;
            padding:10px 10px;
            border:1px solid rgba(31,41,55,0.18);
            border-radius:12px;
            background:{'rgba(31,41,55,0.06)' if active else '#fff'};
            font-weight:{'800' if active else '600'};
            text-align:center;
            font-size:0.88rem;
        ">
          {i}
          <div style="font-weight:600; font-size:0.78rem; color:rgba(31,41,55,0.70); margin-top:2px;">
            {labels[i]}
          </div>
        </div>
        """)

    sub = f" <span style='font-weight:700; color:rgba(31,41,55,0.70)'>({sublevel})</span>" if sublevel else ""
    return f"""
    <div style="margin-top:8px; margin-bottom:10px;">
      <div style="font-weight:900; font-size:1.0rem; margin-bottom:6px;">
        Management Level: {lvl}{sub}
      </div>
      <div style="display:flex; gap:8px;">
        {''.join(segs)}
      </div>
    </div>
    """
