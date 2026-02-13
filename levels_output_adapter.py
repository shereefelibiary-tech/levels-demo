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




from datetime import date


def build_diagnosis_synthesis(patient: Any, out: Dict[str, Any]) -> Dict[str, Any]:
    """
    Engine-owned cardiometabolic diagnosis synthesis.
    Scope-locked to Risk Continuum inputs already parsed into `patient` (or derivable).
    Produces out["diagnosisSynthesis"].

    Confirmed vs suspected:
      - suspected diagnoses do not export ICD by default (icd10 list empty; candidates optional)
      - composite-first suppression prevents redundancy
    """

    def _as_float(x: Any) -> Optional[float]:
        try:
            if x is None or isinstance(x, bool):
                return None
            return float(x)
        except Exception:
            return None

    def _as_int(x: Any) -> Optional[int]:
        try:
            if x is None or isinstance(x, bool):
                return None
            return int(float(x))
        except Exception:
            return None

    def _get_attr_first(obj: Any, names: List[str]) -> Any:
        for n in names:
            if isinstance(obj, dict) and n in obj and obj.get(n) is not None:
                return obj.get(n)
            if hasattr(obj, n):
                v = getattr(obj, n)
                if v is not None:
                    return v
        return None

    def _get_float(patient_obj: Any, names: List[str]) -> Optional[float]:
        return _as_float(_get_attr_first(patient_obj, names))

    def _get_int(patient_obj: Any, names: List[str]) -> Optional[int]:
        return _as_int(_get_attr_first(patient_obj, names))

    def _get_bool(patient_obj: Any, names: List[str]) -> Optional[bool]:
        v = _get_attr_first(patient_obj, names)
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        s = str(v).strip().lower()
        if s in {"true", "yes", "y", "1"}:
            return True
        if s in {"false", "no", "n", "0"}:
            return False
        return None

    def _today_iso() -> str:
        return date.today().isoformat()

    a1c = _get_float(patient, ["a1c", "hba1c", "hemoglobin_a1c"])
    egfr = _get_float(patient, ["egfr", "e_gfr"])
    uacr = _get_float(patient, ["uacr", "acr", "albumin_creatinine_ratio", "urine_albumin_creatinine_ratio"])

    bmi = _get_float(patient, ["bmi", "body_mass_index"])
    cac = _get_int(patient, ["cac", "cac_score", "agatston", "agatston_score"])

    lpa = _get_float(patient, ["lpa", "lp_a", "lp(a)", "lipoprotein_a"])
    lpa_unit_raw = _get_attr_first(patient, ["lpa_unit", "lpaUnit", "lp_a_unit", "lpAUnit"])
    lpa_unit = str(lpa_unit_raw).strip() if lpa_unit_raw is not None else ""
    apob = _get_float(patient, ["apob", "apo_b", "apoB"])

    ldl = _get_float(patient, ["ldl", "ldl_c", "ldlc"])
    hdl = _get_float(patient, ["hdl", "hdl_c", "hdlc"])
    tg = _get_float(patient, ["triglycerides", "trig", "tg"])

    diabetes_flag = _get_bool(patient, ["diabetes", "dm", "t2dm", "has_diabetes"])
    htn_flag = _get_bool(patient, ["hypertension", "htn", "has_hypertension"])

    smoking = _get_attr_first(patient, ["smoking_status", "smoking", "tobacco", "tobacco_use"])
    smoking_s = str(smoking).strip().lower() if smoking is not None else ""

    fam_hx_prem_ascvd = _get_bool(patient, ["family_history_premature_ascvd", "fhx_premature_ascvd", "premature_fhx_ascvd"])

    ckd_flag = _get_bool(patient, ["ckd", "has_ckd", "chronic_kidney_disease"])
    albuminuria_persistent_flag = _get_bool(patient, ["albuminuria_persistent", "persistent_albuminuria"])
    dm_confirmed_flag = _get_bool(patient, ["diabetes_confirmed", "dm_confirmed"])

    A1C_DM_MIN = float(globals().get("A1C_DIABETES_MIN", 6.5))
    A1C_PRE_MIN = float(globals().get("A1C_PREDIABETES_MIN", 5.7))
    A1C_PRE_MAX = float(globals().get("A1C_PREDIABETES_MAX", 6.4))

    UACR_A2_MIN = 30.0
    UACR_A3_MIN = 300.0

    LPA_ELEVATED_CUTOFF = float(globals().get("LPA_ELEVATED_CUTOFF", 50.0))
    LPA_ELEVATED_CUTOFF_NMOL = float(globals().get("LPA_ELEVATED_CUTOFF_NMOL", 125.0))
    LDL_FH_SUSPECT_CUTOFF = 190.0

    TG_HIGH_CUTOFF = float(globals().get("TG_HIGH_CUTOFF", 150.0))
    LDL_HIGH_CUTOFF = float(globals().get("LDL_HIGH_CUTOFF", 130.0))

    def _ckd_stage_from_egfr(v: Optional[float]) -> Optional[str]:
        if v is None:
            return None
        if v < 15:
            return "5"
        if v < 30:
            return "4"
        if v < 45:
            return "3b"
        if v < 60:
            return "3a"
        if v < 90:
            return "2"
        return "1"

    def _icd_ckd_stage(stage: str) -> Optional[str]:
        return {"1": "N18.1", "2": "N18.2", "3a": "N18.31", "3b": "N18.32", "4": "N18.4", "5": "N18.5"}.get(stage)

    ckd_stage = _ckd_stage_from_egfr(egfr)

    def _ckd_is_severe(stage: Optional[str]) -> bool:
        return stage in {"3a", "3b", "4", "5"}

    ckd_confirmed = bool(ckd_flag) if ckd_flag is not None else False
    ckd_suspected = egfr is not None and egfr < 60 and not ckd_confirmed

    def _albuminuria_category(u: Optional[float]) -> Optional[str]:
        if u is None:
            return None
        if u >= UACR_A3_MIN:
            return "A3"
        if u >= UACR_A2_MIN:
            return "A2"
        return None

    uacr_cat = _albuminuria_category(uacr)
    albuminuria_confirmed = bool(albuminuria_persistent_flag) if albuminuria_persistent_flag is not None else False
    albuminuria_suspected = uacr_cat is not None and not albuminuria_confirmed

    dm_confirmed = bool(diabetes_flag) if diabetes_flag is not None else False
    if not dm_confirmed and dm_confirmed_flag is True:
        dm_confirmed = True
    dm_suspected = not dm_confirmed and a1c is not None and a1c >= A1C_DM_MIN

    prediabetes = not dm_confirmed and not dm_suspected and a1c is not None and A1C_PRE_MIN <= a1c <= A1C_PRE_MAX

    smoking_current = False
    if smoking_s:
        if "current" in smoking_s or smoking_s in {"yes", "y", "true"}:
            smoking_current = True

    def _dx(dx_id: str, status: str, label: str, icd10: List[Dict[str, str]], is_hcc: bool, severity: int, actionability: str, criteria_summary: str, evidence: List[Dict[str, Any]], suppress_if_present: Optional[List[str]] = None, icd10_candidates: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        return {
            "id": dx_id, "status": status, "priority": 0, "label": label, "icd10": icd10,
            "icd10_candidates": icd10_candidates or [],
            "hcc": {"is_hcc": bool(is_hcc), "hcc_categories": [], "note": "HCC categories require a maintained mapping table; boolean used for ranking only."},
            "evidence": evidence, "criteria_summary": criteria_summary, "actionability": actionability,
            "severity": severity, "suppress_if_present": suppress_if_present or [],
        }

    dxs: List[Dict[str, Any]] = []

    if dm_suspected:
        ev = [{"key": "a1c", "value": a1c, "unit": "%"}] if a1c is not None else []
        dxs.append(_dx("dx_dm_suspected", "suspected", "Suspected diabetes mellitus — confirm with repeat A1C or alternate diagnostic test", [], True, 70, "high", "Single diagnostic-range A1C without confirmatory evidence in current inputs.", ev, icd10_candidates=[{"code": "E11.9", "display": "Type 2 diabetes mellitus without complications"}]))

    if prediabetes:
        ev = [{"key": "a1c", "value": a1c, "unit": "%"}] if a1c is not None else []
        dxs.append(_dx("dx_prediabetes", "confirmed", "Prediabetes", [{"code": "R73.03", "display": "Prediabetes"}], False, 30, "high", "A1C in prediabetes range and diabetes not confirmed.", ev))

    if ckd_confirmed or ckd_suspected:
        stage = ckd_stage
        stage_icd = _icd_ckd_stage(stage) if stage is not None else None
        ev = [{"key": "egfr", "value": egfr, "unit": "mL/min/1.73m2"}] if egfr is not None else []
        if ckd_confirmed and stage_icd:
            dxs.append(_dx(f"dx_ckd_{stage}", "confirmed", f"Chronic kidney disease, stage {stage}", [{"code": stage_icd, "display": f"Chronic kidney disease, stage {stage}"}], _ckd_is_severe(stage), 85 if _ckd_is_severe(stage) else 60, "high", "CKD flagged/confirmed; stage derived from eGFR.", ev))
        elif ckd_suspected and stage_icd:
            dxs.append(_dx(f"dx_ckd_{stage}_suspected", "suspected", f"Suspected chronic kidney disease, stage {stage} — confirm persistence ≥3 months", [], _ckd_is_severe(stage), 80 if _ckd_is_severe(stage) else 55, "high", "Single eGFR-based stage without persistence/CKD flag in current inputs.", ev, icd10_candidates=[{"code": stage_icd, "display": f"Chronic kidney disease, stage {stage}"}]))

    if uacr_cat is not None:
        ev = [{"key": "uacr", "value": uacr, "unit": "mg/g"}] if uacr is not None else []
        status = "confirmed" if albuminuria_confirmed else "suspected"
        label = f"Albuminuria ({uacr_cat})" if status == "confirmed" else f"Albuminuria ({uacr_cat}) — confirm persistence"
        dxs.append(_dx(f"dx_albuminuria_{uacr_cat}", status, label, [], False, 65 if uacr_cat == "A3" else 50, "high", "UACR category derived from available UACR input.", ev))

    if ckd_stage is not None and uacr_cat is not None:
        weak_suspected = (not ckd_confirmed and ckd_suspected) or albuminuria_suspected
        status = "suspected" if weak_suspected else "confirmed"
        label = f"CKD stage {ckd_stage} with {uacr_cat} albuminuria" + (" — confirm persistence" if status == "suspected" else "")
        ev = []
        if egfr is not None: ev.append({"key": "egfr", "value": egfr, "unit": "mL/min/1.73m2"})
        if uacr is not None: ev.append({"key": "uacr", "value": uacr, "unit": "mg/g"})
        icd_list: List[Dict[str, str]] = []
        if ckd_confirmed:
            stage_icd = _icd_ckd_stage(ckd_stage)
            if stage_icd: icd_list.append({"code": stage_icd, "display": f"Chronic kidney disease, stage {ckd_stage}"})
        dxs.append(_dx(f"dx_ckd_{ckd_stage}_{uacr_cat}", status, label, icd_list, _ckd_is_severe(ckd_stage), 90 if (ckd_stage in {"4", "5"} or uacr_cat == "A3") else 75, "high", "Combined CKD stage (eGFR) and albuminuria category (UACR).", ev))

    if htn_flag is True:
        dxs.append(_dx("dx_htn", "confirmed", "Hypertension", [{"code": "I10", "display": "Essential (primary) hypertension"}], False, 45, "high", "Hypertension flag present.", [], suppress_if_present=["dx_htn_ckd"]))

    if htn_flag is True and ckd_confirmed and ckd_stage is not None:
        ckd_stage_icd = _icd_ckd_stage(ckd_stage)
        if ckd_stage in {"5"}:
            i12 = "I12.0"
            i12_disp = "Hypertensive chronic kidney disease with stage 5 chronic kidney disease or end stage renal disease"
        else:
            i12 = "I12.9"
            i12_disp = "Hypertensive chronic kidney disease with stage 1 through stage 4 chronic kidney disease, or unspecified chronic kidney disease"
        icd_list = [{"code": i12, "display": i12_disp}]
        if ckd_stage_icd:
            icd_list.append({"code": ckd_stage_icd, "display": f"Chronic kidney disease, stage {ckd_stage}"})
        ev = [{"key": "egfr", "value": egfr, "unit": "mL/min/1.73m2"}] if egfr is not None else []
        dxs.append(_dx("dx_htn_ckd", "confirmed", f"Hypertensive chronic kidney disease, stage {ckd_stage}", icd_list, _ckd_is_severe(ckd_stage), 88, "high", "Hypertension present with confirmed CKD; stage derived from eGFR.", ev, suppress_if_present=["dx_htn", f"dx_ckd_{ckd_stage}"]))

    if cac is not None and cac > 0:
        dxs.append(_dx("dx_coronary_calcified_plaque", "confirmed", "Coronary atherosclerosis due to calcified coronary lesion", [{"code": "I25.84", "display": "Coronary atherosclerosis due to calcified coronary lesion"}], True, 90 if cac >= 100 else 75, "high", "CAC present (score > 0).", [{"key": "cac", "value": cac, "unit": "Agatston"}]))

    lpa_cutoff = LPA_ELEVATED_CUTOFF_NMOL if "nmol" in lpa_unit.lower() else LPA_ELEVATED_CUTOFF
    if lpa is not None and lpa >= lpa_cutoff:
        lpa_ev_unit = lpa_unit if lpa_unit else "mg/dL"
        dxs.append(_dx("dx_lpa_elevated", "confirmed", "Elevated lipoprotein(a)", [{"code": "E78.41", "display": "Elevated lipoprotein(a)"}], False, 55, "high", "Lp(a) above unit-aware threshold.", [{"key": "lpa", "value": lpa, "unit": lpa_ev_unit}]))

    lipid_code: Optional[str] = None
    lipid_disp: Optional[str] = None
    tg_high = tg is not None and tg >= TG_HIGH_CUTOFF
    ldl_high = ldl is not None and ldl >= LDL_HIGH_CUTOFF
    if tg_high and ldl_high:
        lipid_code, lipid_disp = "E78.2", "Mixed hyperlipidemia"
    elif tg_high:
        lipid_code, lipid_disp = "E78.1", "Pure hyperglyceridemia"
    elif ldl_high:
        lipid_code, lipid_disp = "E78.0", "Pure hypercholesterolemia"

    if lipid_code and lipid_disp:
        ev = []
        if ldl is not None: ev.append({"key": "ldl", "value": ldl, "unit": "mg/dL"})
        if tg is not None: ev.append({"key": "triglycerides", "value": tg, "unit": "mg/dL"})
        if hdl is not None: ev.append({"key": "hdl", "value": hdl, "unit": "mg/dL"})
        dxs.append(_dx("dx_dyslipidemia", "confirmed", lipid_disp, [{"code": lipid_code, "display": lipid_disp}], False, 45, "high", "Lipid phenotype selected by deterministic thresholds.", ev))

    fh_suspected = ldl is not None and ldl >= LDL_FH_SUSPECT_CUTOFF
    if not fh_suspected and apob is not None and fam_hx_prem_ascvd is True:
        apob_fh_cutoff = float(globals().get("APOB_FH_SUSPECT_CUTOFF", 140.0))
        fh_suspected = apob >= apob_fh_cutoff

    if fh_suspected:
        ev = []
        if ldl is not None: ev.append({"key": "ldl", "value": ldl, "unit": "mg/dL"})
        if apob is not None: ev.append({"key": "apob", "value": apob, "unit": "mg/dL"})
        if fam_hx_prem_ascvd is True: ev.append({"key": "family_history_premature_ascvd", "value": True})
        dxs.append(_dx("dx_fh_suspected", "suspected", "Suspected familial hypercholesterolemia", [], False, 60, "high", "LDL ≥ 190 and/or ApoB very high with premature family history.", ev, icd10_candidates=[{"code": "E78.01", "display": "Familial hypercholesterolemia"}]))

    if bmi is not None:
        if bmi >= 30.0:
            dxs.append(_dx("dx_obesity", "confirmed", "Obesity", [{"code": "E66.9", "display": "Obesity, unspecified"}], False, 40, "medium", "BMI ≥ 30.", [{"key": "bmi", "value": bmi, "unit": "kg/m2"}], suppress_if_present=["dx_overweight"]))
        elif bmi >= 25.0:
            dxs.append(_dx("dx_overweight", "confirmed", "Overweight", [{"code": "E66.3", "display": "Overweight"}], False, 20, "medium", "BMI 25–29.9.", [{"key": "bmi", "value": bmi, "unit": "kg/m2"}]))

    if smoking_current:
        dxs.append(_dx("dx_tobacco_use", "confirmed", "Current tobacco use", [{"code": "Z72.0", "display": "Tobacco use, not otherwise specified"}], False, 25, "high", "Smoking status indicates current use.", [{"key": "smoking_status", "value": str(smoking)}]))

    if dm_confirmed:
        if ckd_confirmed and ckd_stage is not None:
            stage_icd = _icd_ckd_stage(ckd_stage)
            icd_list = [{"code": "E11.22", "display": "Type 2 diabetes mellitus with diabetic chronic kidney disease"}]
            if stage_icd:
                icd_list.append({"code": stage_icd, "display": f"Chronic kidney disease, stage {ckd_stage}"})
            ev = []
            if a1c is not None: ev.append({"key": "a1c", "value": a1c, "unit": "%"})
            if egfr is not None: ev.append({"key": "egfr", "value": egfr, "unit": "mL/min/1.73m2"})
            dxs.append(_dx("dx_t2dm_ckd", "confirmed", f"Type 2 diabetes mellitus with diabetic chronic kidney disease, stage {ckd_stage}", icd_list, True, 92, "high", "Diabetes confirmed with confirmed CKD; stage derived from eGFR.", ev, suppress_if_present=["dx_t2dm", f"dx_ckd_{ckd_stage}"]))
        else:
            ev = [{"key": "a1c", "value": a1c, "unit": "%"}] if a1c is not None else []
            dxs.append(_dx("dx_t2dm", "confirmed", "Type 2 diabetes mellitus", [{"code": "E11.9", "display": "Type 2 diabetes mellitus without complications"}], True, 75, "high", "Diabetes flag/confirmation present.", ev, suppress_if_present=["dx_t2dm_ckd"]))

    def _status_rank(s: str) -> int:
        return 0 if s == "confirmed" else 1 if s == "suspected" else 2

    def _action_rank(a: str) -> int:
        return 0 if a == "high" else 1 if a == "medium" else 2

    for d in dxs:
        d["priority"] = 0

    dxs_sorted = sorted(dxs, key=lambda d: (_status_rank(str(d.get("status"))), 0 if ((d.get("hcc") or {}).get("is_hcc") is True) else 1, -int(d.get("severity") or 0), _action_rank(str(d.get("actionability") or "low")), str(d.get("label") or "")))

    present_ids = {d["id"] for d in dxs_sorted}
    id_to_index = {d["id"]: i for i, d in enumerate(dxs_sorted)}
    suppressed_ids = set()
    for i, d in enumerate(dxs_sorted):
        for sid in d.get("suppress_if_present") or []:
            if sid in present_ids and id_to_index.get(sid, -1) > i:
                suppressed_ids.add(sid)

    dxs_final = [d for d in dxs_sorted if d["id"] not in suppressed_ids]

    confirmed = [d for d in dxs_final if d.get("status") == "confirmed"]
    suspected = [d for d in dxs_final if d.get("status") == "suspected"]
    at_risk = [d for d in dxs_final if d.get("status") == "at_risk"]

    max_confirmed = 6
    max_suspected = 3

    dxs_capped = confirmed[:max_confirmed] + suspected[:max_suspected] + at_risk

    return {
        "model_version": "1.0",
        "hcc_model": "CMS-HCC-V28",
        "generated_at": _today_iso(),
        "diagnoses": dxs_capped,
        "render_defaults": {
            "note_show_codes": False,
            "panel_show_codes": True,
            "note_include_suspected_codes": False,
            "max_confirmed": max_confirmed,
            "max_suspected": max_suspected,
        },
    }

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
                triggers.append(_trigger("APOB_HIGH", "ApoB high", _fmt_num(apob, "mg/dL"), "Atherogenic particle burden elevated, supports treatment intensification.", "high"))
            elif float(apob) >= 90:
                triggers.append(_trigger("APOB_ELEV", "ApoB elevated", _fmt_num(apob, "mg/dL"), "Above goal for this risk tier, supports risk-focused follow-up.", "moderate"))
        except Exception:
            pass

    if lpa is not None:
        try:
            thresh = 50 if str(lpa_unit).lower().startswith("mg") else 125
            if float(lpa) >= thresh:
                triggers.append(_trigger("LPA_ELEV", "Lp(a) elevated", _fmt_num(lpa, lpa_unit, 1), "Genetic risk enhancer, informs long-term intensity planning.", "moderate"))
        except Exception:
            pass

    if a1c is not None:
        try:
            if float(a1c) >= 6.5:
                triggers.append(_trigger("A1C_DM", "Diabetes-range A1c", _fmt_num(a1c, "%", 1), "Metabolic amplification of risk, prioritizes comprehensive risk reduction.", "high"))
            elif float(a1c) >= 5.7:
                triggers.append(_trigger("A1C_PRE", "Prediabetes-range A1c", _fmt_num(a1c, "%", 1), "Metabolic risk enhancer, supports trajectory monitoring.", "moderate"))
        except Exception:
            pass

    if pce_risk_pct is not None:
        try:
            if float(pce_risk_pct) >= 20:
                triggers.append(_trigger("PCE10_HIGH", "10-year ASCVD risk high (PCE)", _fmt_pct(pce_risk_pct), "Population estimate is high, supports prompt preventive action.", "high"))
            elif float(pce_risk_pct) >= 7.5:
                triggers.append(_trigger("PCE10_INT", "10-year ASCVD risk intermediate (PCE)", _fmt_pct(pce_risk_pct), "Population estimate is clinically meaningful, supports shared planning.", "moderate"))
        except Exception:
            pass

    if sbp is not None or dbp is not None:
        s = sbp if sbp is not None else "?"
        d = dbp if dbp is not None else "?"
        try:
            if (sbp is not None and float(sbp) >= 140) or (dbp is not None and float(dbp) >= 90):
                triggers.append(_trigger("BP_UNCTRL", "BP uncontrolled", f"{s}/{d}", "Major driver of stroke and MI risk, supports treatment adjustment.", "high"))
            elif (sbp is not None and float(sbp) >= 130) or (dbp is not None and float(dbp) >= 80):
                triggers.append(_trigger("BP_ELEV", "BP above goal", f"{s}/{d}", "Treat-to-goal reduces events, supports timely reassessment.", "moderate"))
        except Exception:
            pass

    if ckd is True:
        triggers.append(_trigger("CKD", "CKD present", None, "Risk enhancer, supports higher-intensity prevention.", "high"))
    if smoker is True:
        triggers.append(_trigger("SMOKE", "Current smoker", None, "Risk enhancer, prioritize cessation support.", "high"))
    if diabetes is True:
        triggers.append(_trigger("DM_FLAG", "Diabetes present", None, "Risk enhancer, supports multifactor risk management.", "high"))
    if fhx is True:
        triggers.append(_trigger("FHX", "Premature family history", None, "Risk enhancer, supports earlier intervention thresholds.", "moderate"))

    if not triggers:
        triggers.append(_trigger("NO_MAJOR", "No major triggers detected", None, "Based on provided inputs, continue guideline-concordant surveillance.", "low"))

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
            "why": "Treat-to-goal reduces events, proxy when ApoB is missing.",
        },
        {
            "marker": "ApoB",
            "current": _fmt_num(apob, "mg/dL"),
            "target": (f"<{int(apob_goal)} mg/dL" if apob_goal is not None else None),
            "why": "Best proxy for plaque-driving particle burden, aligns treatment intensity to biology.",
        },
    ]
    targets = [t for t in targets if t.get("target") is not None]

    # Plan (compact) — anchored to level + recommendation tag
    plan_items: List[Dict[str, Any]] = []

    tag = str(recommendation_tag or "").lower()
    pending = "pending" in tag

    if pending:
        plan_items.append(_plan_item("test", "Complete key missing inputs to increase certainty, e.g., CAC, ApoB, Lp(a), hsCRP.", "now", 1))
        plan_items.append(_plan_item("followup", "Re-run Risk Continuum after data completion, then confirm next-step intensity.", "after data", 1))
    else:
        if level >= 4:
            med_line = (
                "Intensify lipid-lowering therapy to reach targets, aligned with current burden."
                if therapy_on
                else "Initiate or intensify lipid-lowering therapy to reach targets, aligned with current burden."
            )
            plan_items.append(_plan_item("med", med_line, "now", 1))
            plan_items.append(_plan_item("test", "Repeat lipids, ± ApoB, to confirm response.", "8–12 weeks", 1))
        elif level == 3:
            plan_items.append(_plan_item("med", "Shared decision toward lipid-lowering therapy, consider escalation based on enhancers and trajectory.", "now", 1))
            plan_items.append(_plan_item("test", "Repeat lipids, ± ApoB, to confirm trajectory and response.", "8–12 weeks", 1))
        elif level == 2:
            plan_items.append(_plan_item("lifestyle", "Structured lifestyle sprint, reassess trajectory.", "now", 1))
            plan_items.append(_plan_item("test", "Repeat lipids, ± ApoB, to confirm trend, consider CAC if it would change intensity.", "8–12 weeks", 2))
        else:
            plan_items.append(_plan_item("lifestyle", "Maintain favorable trajectory, periodic reassessment.", "now", 1))

    plan = {
        "meds": [p for p in plan_items if p["kind"] == "med"],
        "tests": [p for p in plan_items if p["kind"] == "test"],
        "lifestyle": [p for p in plan_items if p["kind"] == "lifestyle"],
        "avoid": [p for p in plan_items if p["kind"] == "avoid"],
        "followup": [p for p in plan_items if p["kind"] == "followup"],
    }

    title = "RISK CONTINUUM; CLINICIAN CV ACTION SUMMARY"
    level_name = level_label.split("—", 1)[-1].strip() if "—" in level_label else level_label
    summary_line = f"Current CV level, Level {level}" + (f", {sublevel}" if sublevel else "") + f"; {level_name}."

    confidence_line = f"Recommendation tag, {recommendation_tag};"
    if rss_score is not None:
        confidence_line += f" Risk Signal Score, {rss_score}/100;"
    if pce_risk_pct is not None:
        confidence_line += f" PCE 10y ASCVD, {_fmt_pct(pce_risk_pct)}"
        if pce_cat:
            confidence_line += f", {pce_cat}."
        else:
            confidence_line += "."

    patient_translation = (
        "Clinical framing, patient aligns to a cardiovascular risk spectrum; goal is to reduce plaque-driving particles, ApoB and LDL, "
        "and control major drivers, blood pressure and metabolic factors, over time."
    )

    reassess_line = "Reassess after repeat labs and or additional data, e.g., CAC, as indicated."

    prevent_summary = None
    if prevent_total is not None or prevent_ascvd is not None:
        prevent_summary = {
            "totalCvd10yPct": prevent_total,
            "ascvd10yPct": prevent_ascvd,
            "notes": prevent_note or "PREVENT 10-year comparator, for contextual risk discussion.",
        }
    else:
        if prevent_missing:
            prevent_summary = {
                "totalCvd10yPct": None,
                "ascvd10yPct": None,
                "notes": "PREVENT not calculated, missing required inputs.",
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

    out = {
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

    out["diagnosisSynthesis"] = build_diagnosis_synthesis(inputData, out)
    return out
