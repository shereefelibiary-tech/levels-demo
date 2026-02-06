# levels_engine_v4.py
from typing import Any, Dict, List, Tuple

import levels_engine as legacy

Patient = legacy.Patient


# ----------------------------
# CKD label (tight)
# ----------------------------
def _ckd_g_category(egfr: float) -> str:
    if egfr >= 90:
        return "1"
    if egfr >= 60:
        return "2"
    if egfr >= 45:
        return "3a"
    if egfr >= 30:
        return "3b"
    if egfr >= 15:
        return "4"
    return "5"


def derive_ckd_text(p: Patient) -> str:
    egfr = legacy.safe_float(p.get("egfr")) if p.has("egfr") else None
    uacr = legacy.safe_float(p.get("uacr")) if p.has("uacr") else None

    if egfr is None:
        return "CKD —"

    g = _ckd_g_category(float(egfr))
    egfr_txt = f"eGFR {int(round(float(egfr)))}"
    if uacr is not None:
        uacr_txt = f"UACR {int(round(float(uacr)))}"
        return f"CKD{g} ({egfr_txt}, {uacr_txt})"
    return f"CKD{g} ({egfr_txt})"


# ----------------------------
# CKM stage + minimum drivers
# ----------------------------
def derive_ckm_stage_and_drivers(p: Patient) -> Tuple[int, List[str]]:
    egfr = legacy.safe_float(p.get("egfr")) if p.has("egfr") else None
    has_ckd3plus = (egfr is not None and float(egfr) < 60)

    # Stage 3: clinical ASCVD or meaningful CKD
    if p.get("ascvd") is True:
        return 3, ["clinical ASCVD"]
    if has_ckd3plus:
        return 3, ["CKD3+"]

    # Stage 2: metabolic disease
    a1s = legacy.a1c_status(p)
    if p.get("diabetes") is True:
        return 2, ["diabetes"]
    if a1s == "diabetes_range":
        return 2, ["glycemic criteria (diabetes)"]

    # Stage 1: risk factors
    bmi = legacy.safe_float(p.get("bmi")) if p.has("bmi") else None
    sbp = legacy.safe_float(p.get("sbp")) if p.has("sbp") else None

    if bmi is not None and float(bmi) >= 30:
        return 1, ["obesity"]
    if (sbp is not None and float(sbp) >= 130) or (p.get("bp_treated") is True):
        return 1, ["blood pressure burden"]
    if a1s in ("prediabetes", "near_diabetes_boundary"):
        return 1, ["glycemic criteria (prediabetes)"]
    if p.has("apob") or p.has("ldl"):
        return 1, ["dyslipidemia"]

    return 0, ["no CKM drivers identified"]


def render_ckm_text(stage: int, drivers: List[str]) -> str:
    if stage == 0:
        return "CKM: Stage 0 (no CKM drivers identified)"
    return f"CKM: Stage {stage} ({', '.join(drivers)})"


# ----------------------------
# Enhancers (ranked, max 2)
# ----------------------------
_ENH_PRIORITY = {
    "elevated Lp(a)": 1,
    "coronary calcium present": 1,
    "premature family history": 2,
    "chronic inflammatory disease": 2,
    "kidney disease": 2,
    "risk model discordance": 3,
}


def pick_enhancers(p: Patient, legacy_out: Dict[str, Any]) -> List[str]:
    enh: List[str] = []

    if legacy.lpa_elevated_no_trace(p):
        enh.append("elevated Lp(a)")

    # CAC present (only if measured and >0)
    try:
        cac = p.get("cac")
        if cac is not None and int(cac) > 0:
            enh.append("coronary calcium present")
    except Exception:
        pass

    if p.get("fhx") is True:
        enh.append("premature family history")

    if legacy.has_chronic_inflammatory_disease(p) or legacy.inflammation_flags(p):
        enh.append("chronic inflammatory disease")

    egfr = legacy.safe_float(p.get("egfr")) if p.has("egfr") else None
    uacr = legacy.safe_float(p.get("uacr")) if p.has("uacr") else None
    if egfr is not None and float(egfr) >= 60 and uacr is not None and float(uacr) >= 30:
        enh.append("kidney disease")

    mm = (legacy_out.get("insights") or {}).get("risk_model_mismatch") or {}
    if mm.get("should_surface"):
        enh.append("risk model discordance")

    enh = sorted(list(dict.fromkeys(enh)), key=lambda x: _ENH_PRIORITY.get(x, 99))
    return enh[:2]


# ----------------------------
# Aspirin wording (v4 choice)
# ----------------------------
def derive_aspirin_status(legacy_out: Dict[str, Any]) -> str:
    raw = str((legacy_out.get("aspirin") or {}).get("status") or "").strip().lower()

    if raw.startswith("secondary prevention"):
        return "Indicated (secondary prevention)"
    if raw.startswith("avoid") or raw.startswith("avoid /"):
        return "Not indicated"
    if raw.startswith("consider"):
        return "Reasonable (shared decision)"
    if raw in ("", "not assessed"):
        return "Not assessed"
    return "Not indicated"


# ----------------------------
# Public v4 entrypoint
# ----------------------------
def evaluate_v4(p: Patient) -> Dict[str, Any]:
    legacy_out = legacy.evaluate(p)

    stage, drivers = derive_ckm_stage_and_drivers(p)
    ckm_text = render_ckm_text(stage, drivers)
    ckd_text = derive_ckd_text(p)

    enh = pick_enhancers(p, legacy_out)
    enh_txt = f" ({', '.join(enh)})" if enh else ""

    return {
        "level_num": int(((legacy_out.get("levels") or {}).get("managementLevel")) or 2),
        "sublevel": (legacy_out.get("levels") or {}).get("sublevel"),

        "plaque_status": ((legacy_out.get("levels") or {}).get("evidence") or {}).get("cac_status", "Unknown"),
        "plaque_burden": ((legacy_out.get("levels") or {}).get("evidence") or {}).get("burden_band", "Not quantified"),
        "clinical_ascvd": bool((((legacy_out.get("levels") or {}).get("evidence") or {}).get("clinical_ascvd"))),

        "riskSignal": legacy_out.get("riskSignal", {}),
        "pooledCohortEquations10yAscvdRisk": legacy_out.get("pooledCohortEquations10yAscvdRisk", {}),
        "prevent10": legacy_out.get("prevent10", {}),
        "targets": legacy_out.get("targets", {}),
        "drivers": legacy_out.get("drivers", []),
        "nextActions": legacy_out.get("nextActions", []),
        "anchors": legacy_out.get("anchors", {}),
        "trace": legacy_out.get("trace", []),

        # v4 display fields
        "enhancers": enh,
        "level_enhancers_text": enh_txt,

        "ckm_stage": stage,
        "ckm_drivers_min": drivers,
        "ckm_text": ckm_text,

        "ckd_text": ckd_text,

        "aspirin_status": derive_aspirin_status(legacy_out),
        "aspirin_copy": {"headline": f"Aspirin: {derive_aspirin_status(legacy_out)}"},
        "cac_copy": (legacy_out.get("insights") or {}).get("cac_copy", {}),
    }

