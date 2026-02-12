# levels_output_adapter.py
# Risk Continuum™ output adapter (CamelCase / TS-like contract)
# Aligns to Risk Continuum engine v2.6+ (levels, riskSignal, PCE, prevent10, targets, evidence tags)

from typing import Any, Dict, List, Optional


def evaluate_unified(patient, engine_version: str = "legacy"):
    """
    Unified entry point for Risk Continuum evaluation.
    Keeps app insulated from engine refactors.
    """
    if engine_version == "v4":
        from levels_engine_v4 import evaluate_v4
        v4 = evaluate_v4(patient)
        return _v4_to_legacy(v4, patient)

    from levels_engine import evaluate
    return evaluate(patient)


def _v4_to_legacy(v4: dict, patient=None) -> dict:
    """
    Translate v4 payload into the legacy shape expected by app.py.
    Minimal bridge; expand only when the app needs more.
    """

    level_num = int(v4.get("level_num") or 2)
    sublevel_raw = v4.get("sublevel")  # "2A"/"2B"/"3A"/"3B" or None
    s = str(sublevel_raw).strip().upper() if sublevel_raw else None

    enh_txt = str(v4.get("level_enhancers_text") or "").strip()
    # ensure enhancer text formats as a parenthetical when present
    if enh_txt and not enh_txt.startswith("("):
        enh_txt = f"({enh_txt})"
    if enh_txt and not enh_txt.startswith(" "):
        enh_txt = " " + enh_txt

    LEVEL_MEANINGS = {
        1: "Minimal risk signal",
        2: "Emerging risk signals",
        3: "Actionable biologic risk",
        4: "Subclinical atherosclerosis present",
        5: "Very high risk / ASCVD intensity",
    }
    SUBLEVEL_LABELS = {
        "2A": "Level 2A — Emerging (isolated / mild)",
        "2B": "Level 2B — Emerging (converging / rising)",
        "3A": "Level 3A — Actionable biology (limited enhancers)",
        "3B": "Level 3B — Actionable biology + enhancers",
    }

    if s and s in SUBLEVEL_LABELS:
        label = SUBLEVEL_LABELS[s] + enh_txt
    else:
        label = f"Level {level_num} — {LEVEL_MEANINGS.get(level_num, '—')}" + enh_txt

    plaque_status = v4.get("plaque_status", "Unknown")
    plaque_burden = v4.get("plaque_burden", "Not quantified")

    therapy_on = False
    try:
        if patient is not None:
            for k in ("lipid_lowering", "on_statin", "statin", "lipidTherapy"):
                if bool(getattr(patient, "get", lambda *_: None)(k)) is True:
                    therapy_on = True
                    break
    except Exception:
        therapy_on = False

    return {
        "version": v4.get("version", {}),
        "system": v4.get("system", "Risk Continuum"),

        "levels": {
            "postureLevel": level_num,
            "managementLevel": level_num,
            "sublevel": s if s else None,
            "label": label,

            # Needed for EMR note render_quick_text()
            "plaqueEvidence": plaque_status,
            "plaqueBurden": plaque_burden,

            "decisionConfidence": v4.get("decision_confidence", "—"),
            "decisionStability": v4.get("decision_stability", "—"),
            "decisionStabilityNote": v4.get("decision_stability_note", ""),

            "evidence": {
                "clinical_ascvd": bool(v4.get("clinical_ascvd", False)),
                "on_lipid_therapy": bool(therapy_on),
                "cac_status": plaque_status,
                "burden_band": plaque_burden,
                "cac_value": v4.get("cac_value", None),
            },

            "legend": v4.get("legend", []),
        },

        "riskSignal": v4.get("riskSignal", {}),
        "pooledCohortEquations10yAscvdRisk": v4.get("pooledCohortEquations10yAscvdRisk", {}),
        "ascvdPce10yRisk": v4.get("pooledCohortEquations10yAscvdRisk", {}),
        "prevent10": v4.get("prevent10", {}),
        "targets": v4.get("targets", {}),

        "drivers": v4.get("drivers", []),
        "nextActions": v4.get("nextActions", []),

        "aspirin": {
            "status": v4.get("aspirin_status", "Not assessed"),
            "explanation": v4.get("aspirin_expl", ""),
            "rationale": v4.get("aspirin_rationale", []),
        },

        "insights": {
            "ckm_copy": {
                "headline": v4.get("ckm_text", ""),
                "detail": v4.get("ckm_detail", ""),
            },
            "ckd_copy": {
                "headline": v4.get("ckd_text", ""),
                "detail": v4.get("ckd_detail", ""),
            },

            "cac_copy": v4.get("cac_copy", {}),
            "aspirin_copy": v4.get("aspirin_copy", {}),

            "risk_driver_pattern": v4.get("risk_driver_pattern", {}),
            "cac_decision_support": v4.get("cac_decision_support", {}),
            "ckm_context": v4.get("ckm_context", {}),

            # Engine-owned HTML tables (restored)
            "criteria_table_html": v4.get("criteria_table_html", ""),
            "where_patient_falls_html": v4.get("where_patient_falls_html", ""),
        },

        "anchors": v4.get("anchors", {}),
        "trace": v4.get("trace", []),
    }

# -------------------------------------------------------------------
# The TS-like contract generator (unchanged legacy helper)
# -------------------------------------------------------------------

def _fmt_num(x: Optional[float], unit: str = "", dp: int = 0) -> Optional[str]:
    if x is None:
        return None
    try:
        v = float(x)
    except Exception:
        return str(x)
    if dp == 0:
        v = int(round(v))
    else:
        v = round(v, dp)
    return f"{v} {unit}".strip() if unit else f"{v}"


def _fmt_pct(x: Optional[float], dp: int = 1) -> Optional[str]:
    if x is None:
        return None
    try:
        return f"{round(float(x), dp)}%"
    except Exception:
        return None


def _trigger(
    code: str,
    label: str,
    value: Optional[str] = None,
    detail: Optional[str] = None,
    severity: str = "moderate",
) -> Dict[str, Any]:
    out: Dict[str, Any] = {"code": code, "label": label, "severity": severity}
    if value is not None:
        out["value"] = value
    if detail is not None:
        out["detail"] = detail
    return out


def _plan_item(kind: str, text: str, timing: Optional[str] = None, priority: Optional[int] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"kind": kind, "text": text}
    if timing is not None:
        out["timing"] = timing
    if priority is not None:
        out["priority"] = priority
    return out


def _get_level(engine_levels: dict, engine_out: dict) -> int:
    lvl = (
        engine_levels.get("managementLevel")
        or engine_levels.get("postureLevel")
        or engine_levels.get("level")
        or engine_out.get("managementLevel")
        or engine_out.get("postureLevel")
        or engine_out.get("level")
        or 2
    )
    try:
        return max(1, min(5, int(lvl)))
    except Exception:
        return 2


def generateRiskContinuumCvOutput(inputData: dict, engineOut: dict) -> dict:
    """
    Adapter: engineOut (Risk Continuum engine evaluate()) + inputData -> camelCase contract.

    Notes:
    - inputData here is whatever your UI sends (may be camelCase or snake_case).
    - engineOut is the evaluated output from levels_engine.evaluate(patient).
    """

    levels_obj = engineOut.get("levels", {}) or {}
    level = _get_level(levels_obj, engineOut)
    level_label = levels_obj.get("label", f"Level {level}")
    sublevel = levels_obj.get("sublevel")

    recommendation_tag = levels_obj.get("recommendationStrength") or "—"
    meaning = levels_obj.get("meaning") or ""
    level_explainer = levels_obj.get("explainer") or ""
    legend = levels_obj.get("legend") or []

    # Evidence
    ev = levels_obj.get("evidence") or {}
    cac_status = ev.get("cac_status")
    burden_band = ev.get("burden_band")
    evidence_summary = None
    if cac_status or burden_band:
        evidence_summary = f"{cac_status or '—'} / {burden_band or '—'}"

    # PCE (2013) anchor
    risk10 = engineOut.get("pooledCohortEquations10yAscvdRisk", {}) or {}
    pce_risk_pct = risk10.get("risk_pct")
    pce_cat = risk10.get("category")

    # Risk Signal
    rss = engineOut.get("riskSignal", {}) or {}
    rss_score = rss.get("score")
    rss_band = rss.get("band")

    # PREVENT (optional comparator)
    prevent10 = engineOut.get("prevent10", {}) or {}
    prevent_total = prevent10.get("total_cvd_10y_pct")
    prevent_ascvd = prevent10.get("ascvd_10y_pct")
    prevent_missing = prevent10.get("missing") or []
    prevent_note = prevent10.get("notes")

    # Inputs (normalize some names)
    apob = inputData.get("apob")
    ldl = inputData.get("ldl")
    lpa = inputData.get("lpa")
    lpa_unit = inputData.get("lpaUnit") or inputData.get("lpa_unit") or "nmol/L"
    a1c = inputData.get("a1c")
    sbp = inputData.get("sbp")
    dbp = inputData.get("dbp")  # not always present in your app
    fhx = inputData.get("fhx") or inputData.get("famHxPrematureAscVD")
    smoker = inputData.get("smoking") or inputData.get("smoker")
    diabetes = inputData.get("diabetes")
    ckd = inputData.get("ckd")
    therapy_on = bool(
        inputData.get("lipid_lowering")
        or inputData.get("on_statin")
        or inputData.get("statin")
        or inputData.get("lipidTherapy")
    )

    # Triggers (kept similar, but aligned with Risk Continuum language)
    triggers: List[Dict[str, Any]] = []

    if apob is not None:
        try:
            if float(apob) >= 120:
                triggers.append(_trigger("APOB_HIGH", "ApoB high", _fmt_num(apob, "mg/dL"), "Atherogenic particle burden elevated.", "high"))
            elif float(apob) >= 90:
                triggers.append(_trigger("APOB_ELEV", "ApoB elevated", _fmt_num(apob, "mg/dL"), "Above goal for this risk tier.", "moderate"))
        except Exception:
            pass

    if lpa is not None:
        try:
            thresh = 50 if str(lpa_unit).lower().startswith("mg") else 125
            if float(lpa) >= thresh:
                triggers.append(_trigger("LPA_ELEV", "Lp(a) elevated", _fmt_num(lpa, lpa_unit, 1), "Genetic risk enhancer.", "moderate"))
        except Exception:
            pass

    if a1c is not None:
        try:
            if float(a1c) >= 6.5:
                triggers.append(_trigger("A1C_DM", "Diabetes-range A1c", _fmt_num(a1c, "%", 1), "Metabolic amplification of risk.", "high"))
            elif float(a1c) >= 5.7:
                triggers.append(_trigger("A1C_PRE", "Prediabetes-range A1c", _fmt_num(a1c, "%", 1), "Metabolic risk enhancer.", "moderate"))
        except Exception:
            pass

    if pce_risk_pct is not None:
        try:
            if float(pce_risk_pct) >= 20:
                triggers.append(_trigger("PCE10_HIGH", "10-year ASCVD risk high (PCE)", _fmt_pct(pce_risk_pct), "Population estimate is high.", "high"))
            elif float(pce_risk_pct) >= 7.5:
                triggers.append(_trigger("PCE10_INT", "10-year ASCVD risk intermediate (PCE)", _fmt_pct(pce_risk_pct), "Population estimate is clinically meaningful.", "moderate"))
        except Exception:
            pass

    if sbp is not None or dbp is not None:
        s = sbp if sbp is not None else "?"
        d = dbp if dbp is not None else "?"
        try:
            if (sbp is not None and float(sbp) >= 140) or (dbp is not None and float(dbp) >= 90):
                triggers.append(_trigger("BP_UNCTRL", "BP uncontrolled", f"{s}/{d}", "Major driver of stroke/MI risk.", "high"))
            elif (sbp is not None and float(sbp) >= 130) or (dbp is not None and float(dbp) >= 80):
                triggers.append(_trigger("BP_ELEV", "BP above goal", f"{s}/{d}", "Treat-to-goal reduces events.", "moderate"))
        except Exception:
            pass

    if ckd is True:
        triggers.append(_trigger("CKD", "CKD present", None, "Risk enhancer.", "high"))
    if smoker is True:
        triggers.append(_trigger("SMOKE", "Current smoker", None, "Risk enhancer.", "high"))
    if diabetes is True:
        triggers.append(_trigger("DM_FLAG", "Diabetes present", None, "Risk enhancer.", "high"))
    if fhx is True:
        triggers.append(_trigger("FHX", "Premature family history", None, "Risk enhancer.", "moderate"))

    if not triggers:
        triggers.append(_trigger("NO_MAJOR", "No major triggers detected", None, "Based on provided inputs.", "low"))

    triggers = triggers[:6]

    # Targets — use engine targets to avoid mismatch
    eng_targets = engineOut.get("targets", {}) or {}
    apob_goal = eng_targets.get("apob")
    ldl_goal = eng_targets.get("ldl")

    targets: List[Dict[str, Any]] = [
        {
            "marker": "LDL-C",
            "current": _fmt_num(ldl, "mg/dL"),
            "target": (f"<{int(ldl_goal)} mg/dL" if ldl_goal is not None else None),
            "why": "Treat-to-goal reduces events; proxy when ApoB missing.",
        },
        {
            "marker": "ApoB",
            "current": _fmt_num(apob, "mg/dL"),
            "target": (f"<{int(apob_goal)} mg/dL" if apob_goal is not None else None),
            "why": "Best proxy for plaque-driving particle burden.",
        },
    ]
    targets = [t for t in targets if t.get("target") is not None]

    # Plan (compact) — anchored to level + recommendation tag
    plan_items: List[Dict[str, Any]] = []

    tag = str(recommendation_tag or "").lower()
    pending = "pending" in tag

    if pending:
        plan_items.append(_plan_item("test", "Complete key missing inputs to increase certainty (e.g., CAC, ApoB, Lp(a), hsCRP).", "now", 1))
        plan_items.append(_plan_item("followup", "Re-run Risk Continuum after data completion.", "after data", 1))
    else:
        if level >= 4:
            med_line = (
                "Intensify lipid-lowering therapy to reach targets."
                if therapy_on
                else "Initiate or intensify lipid-lowering therapy to reach targets."
            )
            plan_items.append(_plan_item("med", med_line, "now", 1))
            plan_items.append(_plan_item("test", "Repeat lipids (± ApoB) to confirm response.", "8–12 weeks", 1))
        elif level == 3:
            plan_items.append(_plan_item("med", "Shared decision toward lipid-lowering therapy; consider escalation based on enhancers and trajectory.", "now", 1))
            plan_items.append(_plan_item("test", "Repeat lipids (± ApoB) to confirm trajectory/response.", "8–12 weeks", 1))
        elif level == 2:
            plan_items.append(_plan_item("lifestyle", "Structured lifestyle sprint; reassess trajectory.", "now", 1))
            plan_items.append(_plan_item("test", "Repeat lipids (± ApoB) to confirm trend; consider CAC if it would change intensity.", "8–12 weeks", 2))
        else:
            plan_items.append(_plan_item("lifestyle", "Maintain favorable trajectory; periodic reassessment.", "now", 1))

    plan = {
        "meds": [p for p in plan_items if p["kind"] == "med"],
        "tests": [p for p in plan_items if p["kind"] == "test"],
        "lifestyle": [p for p in plan_items if p["kind"] == "lifestyle"],
        "avoid": [p for p in plan_items if p["kind"] == "avoid"],
        "followup": [p for p in plan_items if p["kind"] == "followup"],
    }

    title = "RISK CONTINUUM — CV ACTION SUMMARY"
    level_name = level_label.split("—", 1)[-1].strip() if "—" in level_label else level_label
    summary_line = f"Current CV Level: Level {level}" + (f" ({sublevel})" if sublevel else "") + f" — {level_name}."

    confidence_line = f"Recommendation tag: {recommendation_tag}."
    if rss_score is not None:
        confidence_line += f" Risk Signal Score: {rss_score}/100."
    if pce_risk_pct is not None:
        confidence_line += f" PCE 10y ASCVD: {_fmt_pct(pce_risk_pct)}"
        if pce_cat:
            confidence_line += f" ({pce_cat})."
        else:
            confidence_line += "."

    patient_translation = (
        "This places you on a risk spectrum. The goal is to reduce plaque-driving particles (ApoB/LDL) and control major drivers "
        "(blood pressure, metabolic factors) over time."
    )

    reassess_line = "Reassess after repeat labs and/or additional data (e.g., CAC) as indicated."

    prevent_summary = None
    if prevent_total is not None or prevent_ascvd is not None:
        prevent_summary = {
            "totalCvd10yPct": prevent_total,
            "ascvd10yPct": prevent_ascvd,
            "notes": prevent_note or "PREVENT (10-year) comparator.",
        }
    else:
        if prevent_missing:
            prevent_summary = {
                "totalCvd10yPct": None,
                "ascvd10yPct": None,
                "notes": "PREVENT not calculated (missing required inputs).",
                "missing": prevent_missing[:5],
            }
        elif prevent_note:
            prevent_summary = {"totalCvd10yPct": None, "ascvd10yPct": None, "notes": prevent_note}

    md_parts = [
        title,
        summary_line,
        "",
        "Triggers:",
        *[f"- {t['label']}{': '+t['value'] if t.get('value') else ''}" for t in triggers],
        "",
        "Targets:",
        *[f"- {x['marker']}: {x.get('current','—')} → {x['target']} — {x['why']}" for x in targets],
        "",
        "Plan:",
        *[f"- {p['text']}{' ('+p['timing']+')' if p.get('timing') else ''}" for p in plan_items],
    ]
    if evidence_summary:
        md_parts += ["", f"Evidence: {evidence_summary}"]
    if prevent_summary and (prevent_summary.get("totalCvd10yPct") is not None or prevent_summary.get("ascvd10yPct") is not None):
        md_parts += ["", f"PREVENT (10-year): total CVD {_fmt_pct(prevent_summary.get('totalCvd10yPct'), dp=1)} / "
                         f"ASCVD {_fmt_pct(prevent_summary.get('ascvd10yPct'), dp=1)}"]

    markdown = "\n".join([x for x in md_parts if x is not None])

    return {
        "systemName": engineOut.get("system") or engineOut.get("version", {}).get("system") or "Risk Continuum",
        "level": level,
        "sublevel": sublevel,
        "title": title,
        "summaryLine": summary_line,

        "meaning": meaning,
        "levelExplainer": level_explainer,
        "legend": legend,
        "recommendationTag": recommendation_tag,

        "evidence": {
            "cacStatus": cac_status,
            "burdenBand": burden_band,
            "summary": evidence_summary,
        },

        "triggers": triggers,
        "targets": targets,
        "plan": plan,

        "confidenceLine": confidence_line,
        "patientTranslation": patient_translation,
        "reassessLine": reassess_line,
        "markdown": markdown,

        "riskSignalScore": {"score": rss_score, "band": rss_band},
        "pooledCohortEquations10yAscvdRisk": {"riskPct": pce_risk_pct, "category": pce_cat},

        "prevent10": prevent_summary,
    }
