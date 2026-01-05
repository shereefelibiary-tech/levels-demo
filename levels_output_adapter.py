# levels_output_adapter.py
# Output adapter: converts your engine result into a TS-like camelCase contract.

from typing import Any, Dict, List, Optional

def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s

def _fmt_num(x: Optional[float], unit: str = "", dp: int = 0) -> Optional[str]:
    if x is None:
        return None
    try:
        v = float(x)
    except:
        return str(x)
    if dp == 0:
        v = int(round(v))
    else:
        v = round(v, dp)
    return f"{v} {unit}".strip() if unit else f"{v}"

def _fmt_pct(x: Optional[float]) -> Optional[str]:
    if x is None:
        return None
    try:
        return f"{round(float(x),1)}%"
    except:
        return None

def _trigger(code: str, label: str, value: Optional[str]=None, detail: Optional[str]=None, severity: str="moderate") -> Dict[str, Any]:
    out = {"code": code, "label": label, "severity": severity}
    if value is not None: out["value"] = value
    if detail is not None: out["detail"] = detail
    return out

def _plan_item(kind: str, text: str, timing: Optional[str]=None, priority: Optional[int]=None) -> Dict[str, Any]:
    out = {"kind": kind, "text": text}
    if timing is not None: out["timing"] = timing
    if priority is not None: out["priority"] = priority
    return out

def generateLevelsCvOutput(inputData: dict, engineOut: dict) -> dict:
    """
    CamelCase LevelsCvOutput-like contract.
    Safe: if some fields are missing, fills reasonable defaults.
    """

    # Pull level
    level_obj = engineOut.get("levels", engineOut)
    level = int(level_obj.get("level", engineOut.get("level", 2)))
    level_label = level_obj.get("label", f"Level {level}")

    # Risk calc: "Pooled Cohort Equations (10-year ASCVD risk)"
    risk10 = engineOut.get("risk10") or engineOut.get("pooled_cohort_equations_10y_ascvd_risk") or {}
    risk_pct = risk10.get("risk_pct")
    risk_cat = risk10.get("category")

    # Risk signal score
    rss = engineOut.get("risk_signal") or engineOut.get("risk_signal_score") or {}
    rss_score = rss.get("score")
    rss_band = rss.get("band")

    # Triggers (short, stable codes)
    triggers: List[Dict[str, Any]] = []

    apob = inputData.get("apob")
    ldl = inputData.get("ldl")
    lpa = inputData.get("lpa")
    lpa_unit = inputData.get("lpaUnit") or inputData.get("lpa_unit") or "nmol/L"
    a1c = inputData.get("a1c")
    sbp = inputData.get("sbp")
    dbp = inputData.get("dbp")
    fhx = inputData.get("fhx") or inputData.get("famHxPrematureAscVD") or inputData.get("famHxPrematureAscVD")
    smoker = inputData.get("smoking") or inputData.get("smoker")
    diabetes = inputData.get("diabetes")

    if apob is not None:
        if float(apob) >= 120:
            triggers.append(_trigger("APOB_HIGH", "ApoB high", _fmt_num(apob, "mg/dL"), "Atherogenic particle burden elevated.", "high"))
        elif float(apob) >= 90:
            triggers.append(_trigger("APOB_ELEV", "ApoB elevated", _fmt_num(apob, "mg/dL"), "Above goal for this risk tier.", "moderate"))

    if lpa is not None:
        thresh = 50 if str(lpa_unit).lower().startswith("mg") else 125
        if float(lpa) >= thresh:
            triggers.append(_trigger("LPA_ELEV", "Lp(a) elevated", _fmt_num(lpa, lpa_unit), "Genetic risk enhancer.", "moderate"))

    if a1c is not None:
        if float(a1c) >= 6.5:
            triggers.append(_trigger("A1C_DM", "Diabetes-range A1c", _fmt_num(a1c, "%", 1), "Metabolic amplification of ASCVD risk.", "high"))
        elif float(a1c) >= 5.7:
            triggers.append(_trigger("A1C_PRE", "Prediabetes-range A1c", _fmt_num(a1c, "%", 1), "Metabolic risk enhancer.", "moderate"))

    if risk_pct is not None:
        if float(risk_pct) >= 20:
            triggers.append(_trigger("ASCVD10Y_HIGH", "10-year ASCVD risk high", _fmt_pct(risk_pct), "Population estimate is high.", "high"))
        elif float(risk_pct) >= 7.5:
            triggers.append(_trigger("ASCVD10Y_INT", "10-year ASCVD risk intermediate", _fmt_pct(risk_pct), "Population estimate is clinically meaningful.", "moderate"))

    if sbp is not None or dbp is not None:
        s = sbp if sbp is not None else "?"
        d = dbp if dbp is not None else "?"
        try:
            if (sbp is not None and float(sbp) >= 140) or (dbp is not None and float(dbp) >= 90):
                triggers.append(_trigger("BP_UNCTRL", "BP uncontrolled", f"{s}/{d}", "Major driver of stroke/MI risk.", "high"))
            elif (sbp is not None and float(sbp) >= 130) or (dbp is not None and float(dbp) >= 80):
                triggers.append(_trigger("BP_ELEV", "BP above goal", f"{s}/{d}", "Treat-to-goal reduces events.", "moderate"))
        except:
            pass

    if smoker is True:
        triggers.append(_trigger("SMOKE", "Current smoker", None, "Risk enhancer.", "high"))
    if diabetes is True:
        triggers.append(_trigger("DM_FLAG", "Diabetes present", None, "Risk enhancer.", "high"))
    if fhx is True:
        triggers.append(_trigger("FHX", "Premature family history", None, "Risk enhancer.", "moderate"))

    if not triggers:
        triggers.append(_trigger("NO_MAJOR", "No major triggers detected", None, "Based on provided inputs.", "low"))

    triggers = triggers[:6]

    # Targets (simple, readable)
    def apob_target_for_level(lvl: int) -> str:
        if lvl >= 4: return "<60 mg/dL"
        if lvl == 3: return "<70 mg/dL"
        if lvl == 2: return "<80 mg/dL"
        return "<90 mg/dL"

    def ldl_target_for_level(lvl: int) -> str:
        if lvl >= 3: return "<70 mg/dL"
        if lvl == 2: return "<100 mg/dL"
        return "<130 mg/dL"

    targets = [
        {
            "marker": "ApoB",
            "current": _fmt_num(apob, "mg/dL"),
            "target": apob_target_for_level(level),
            "why": "Best proxy for plaque-driving particle burden."
        },
        {
            "marker": "LDL-C",
            "current": _fmt_num(ldl, "mg/dL"),
            "target": ldl_target_for_level(level),
            "why": "Treat-to-goal reduces events; proxy when ApoB missing."
        }
    ]

    # Plan (short, grouped)
    plan_items: List[Dict[str, Any]] = []
    if level >= 3:
        plan_items.append(_plan_item("med", "Start or intensify statin therapy.", "now", 1))
        plan_items.append(_plan_item("test", "Repeat lipids + ApoB to confirm response.", "8–12 weeks", 1))
    elif level == 2:
        plan_items.append(_plan_item("med", "Discuss statin based on risk enhancers + shared decision-making.", "now", 2))
        plan_items.append(_plan_item("test", "Repeat lipids + ApoB to confirm trajectory.", "8–12 weeks", 1))
    else:
        plan_items.append(_plan_item("lifestyle", "Lifestyle optimization; maintain favorable trajectory.", "now", 1))

    # Group plan
    grouped_plan = {
        "meds": [p for p in plan_items if p["kind"] == "med"],
        "tests": [p for p in plan_items if p["kind"] == "test"],
        "lifestyle": [p for p in plan_items if p["kind"] == "lifestyle"],
        "avoid": [p for p in plan_items if p["kind"] == "avoid"],
        "followup": [p for p in plan_items if p["kind"] == "followup"],
    }

    # Summary lines
    title = "LEVELS CV — ACTION SUMMARY"
    level_name = level_label.split("—", 1)[-1].strip() if "—" in level_label else level_label
    summary_line = f"Current CV Level: Level {level} — {level_name}."

    confidence_line = "Recommendation strength: Moderate. Evidence base: Moderate."
    if rss_score is not None:
        confidence_line = f"Recommendation strength: {_cap('moderate')}. Evidence base: {_cap('moderate')}. Risk Signal Score: {rss_score}/100."

    patient_translation = (
        "Focus is lowering plaque-driving particles (ApoB/LDL) and controlling major drivers (BP/metabolic) over time."
    )
    reassess_line = "Reassess after repeat lipids/ApoB and updated risk factors."

    # Markdown
    markdown = (
        f"{title}\n"
        f"{summary_line}\n\n"
        f"Triggers:\n" +
        "\n".join([f"- {t['label']}{': '+t['value'] if t.get('value') else ''}" for t in triggers]) +
        "\n\nTargets:\n" +
        "\n".join([f"- {x['marker']}: {x.get('current','—')} → {x['target']} — {x['why']}" for x in targets]) +
        "\n\nPlan:\n" +
        "\n".join([f"- {p['text']}{' ('+p['timing']+')' if p.get('timing') else ''}" for p in plan_items])
    )

    return {
        "level": level,
        "title": title,
        "summaryLine": summary_line,
        "triggers": triggers,
        "targets": targets,
        "plan": grouped_plan,
        "confidenceLine": confidence_line,
        "patientTranslation": patient_translation,
        "reassessLine": reassess_line,
        "markdown": markdown,
        # extra context if you want it:
        "riskSignalScore": {"score": rss_score, "band": rss_band},
        "pooledCohortEquations10yAsc vdRisk": {"riskPct": risk_pct, "category": risk_cat},
    }

