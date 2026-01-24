# levels_engine.py
# Risk Continuum™ Engine — v2.9
#
# Core philosophy:
# - Produce ease and confidence in CV risk decisions
# - Separate biologic risk, plaque evidence, and decision confidence
# - CAC is a late-stage optional clarifier, never a reflex trigger
#
# v2.9 changes:
# - Removed legacy 2013 PCE entirely
# - ASCVD risk aligned to Epic-style 2019 ACC/AHA interpretation
# - CAC ordering logic decoupled from Levels (suppressed / deferred / optional)
# - Explicit confidence language to reduce decision anxiety
#
# Preserves:
# - RSS scoring (biologic + plaque signal)
# - PREVENT comparator
# - Level framework
# - Anchors, drivers, traceability
# - EMR-safe quick text output

import math
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

SYSTEM_NAME = "Risk Continuum™"

VERSION = {
    "system": SYSTEM_NAME,
    "levels": "v2.9-risk-continuum-confidence",
    "riskSignal": "RSS v1.0",
    "riskCalc": "ASCVD PCE (ACC/AHA 2019 interpretation; Epic-aligned)",
    "aspirin": "Aspirin v1.0 (CAC≥100 OR ASCVD risk≥10%, age 40–69, low bleed risk)",
    "prevent": "PREVENT (AHA) population model 10y: total CVD + ASCVD",
    "insights": "Confidence-calibrated decision support",
}

# ----------------------------
# Patient wrapper
# ----------------------------
@dataclass
class Patient:
    data: Dict[str, Any]

    def get(self, k, d=None):
        return self.data.get(k, d)

    def has(self, k):
        return k in self.data and self.data[k] is not None

# ----------------------------
# Formatting helpers
# ----------------------------
def fmt_int(x):
    try:
        return int(round(float(x)))
    except Exception:
        return x

def fmt_1dp(x):
    try:
        return round(float(x), 1)
    except Exception:
        return x

# ----------------------------
# Trace helper (auditable rules)
# ----------------------------
def add_trace(trace: List[Dict[str, Any]], rule: str, value: Any = None, effect: str = "") -> None:
    trace.append({"rule": rule, "value": value, "effect": effect})

# ----------------------------
# Safe float
# ----------------------------
def safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

# ----------------------------
# A1c + inflammation helpers
# ----------------------------
def a1c_status(p: Patient) -> Optional[str]:
    if not p.has("a1c"):
        return None
    try:
        a1c = float(p.get("a1c"))
    except Exception:
        return None
    if a1c < 5.7:
        return "normal"
    if a1c < 6.5:
        return "prediabetes"
    return "diabetes_range"

def has_chronic_inflammatory_disease(p: Patient) -> bool:
    return any(p.get(k) is True for k in ["ra", "psoriasis", "sle", "ibd", "hiv"])

def inflammation_flags(p: Patient) -> List[str]:
    flags = []
    if p.has("hscrp") and safe_float(p.get("hscrp")) >= 2:
        flags.append("hsCRP≥2")
    for k, label in [
        ("ra", "RA"),
        ("psoriasis", "Psoriasis"),
        ("sle", "SLE"),
        ("ibd", "IBD"),
        ("hiv", "HIV"),
        ("osa", "OSA"),
        ("nafld", "NAFLD/MASLD"),
    ]:
        if p.get(k) is True:
            flags.append(label)
    return flags

# ----------------------------
# Lp(a) normalization + threshold transparency
# ----------------------------
_LPA_MGDL_TO_NMOLL = 2.5

def lpa_info(p: Patient, trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not p.has("lpa"):
        return {"present": False}

    try:
        raw_val = float(p.get("lpa"))
    except Exception:
        return {"present": False}

    unit_raw = str(p.get("lpa_unit", "")).strip()
    unit = unit_raw.lower()

    if "mg" in unit:
        threshold = 50.0
        elevated = raw_val >= threshold
        nmol_est = raw_val * _LPA_MGDL_TO_NMOLL
        mg_est = raw_val
        used = "mg/dL"
    else:
        threshold = 125.0
        elevated = raw_val >= threshold
        nmol_est = raw_val
        mg_est = raw_val / _LPA_MGDL_TO_NMOLL
        used = "nmol/L"

    add_trace(
        trace,
        "Lp(a)_threshold",
        value=f"{raw_val} {unit_raw}".strip(),
        effect=f"Used threshold {threshold} {used}; elevated={elevated} (conversion est 1 mg/dL≈2.5 nmol/L)",
    )

    return {
        "present": True,
        "raw_value": raw_val,
        "raw_unit": unit_raw or ("nmol/L" if used == "nmol/L" else "mg/dL"),
        "used_threshold": threshold,
        "used_unit": used,
        "elevated": elevated,
        "estimated_nmolL": round(nmol_est, 1),
        "estimated_mgdl": round(mg_est, 1),
        "conversion_note": "Estimated conversion only; true conversion depends on isoform size.",
    }

def lpa_elevated(p: Patient, trace: List[Dict[str, Any]]) -> bool:
    info = lpa_info(p, trace)
    return bool(info.get("present") and info.get("elevated"))

def lpa_elevated_no_trace(p: Patient) -> bool:
    """
    Same thresholds as lpa_info(), but without trace.
    nmol/L elevated >=125; mg/dL elevated >=50.
    """
    if not p.has("lpa"):
        return False
    try:
        raw_val = float(p.get("lpa"))
    except Exception:
        return False
    unit_raw = str(p.get("lpa_unit", "")).strip().lower()
    if "mg" in unit_raw:
        return raw_val >= 50.0
    return raw_val >= 125.0


# ============================================================
# PREVENT (AHA) — Population model comparator (AHAprevent R pkg v1.0.0)
# FULL model: 10-year Total CVD + 10-year ASCVD (%), logistic form
# ============================================================

def mmol_conversion(x_mgdl: float) -> float:
    return float(x_mgdl) / 38.67

def _prevent_logistic_pct(logor: float) -> float:
    r = math.exp(logor) / (1.0 + math.exp(logor))
    return round(r * 100.0, 2)

def adjust_uacr(uacr: float) -> float:
    return max(float(uacr), 0.1)

def sdicat(sdi_decile: int) -> int:
    v = int(sdi_decile)
    if 1 <= v <= 3:
        return 0
    if 4 <= v <= 6:
        return 1
    if 7 <= v <= 10:
        return 2
    return 0

def sdi_to_decile(x) -> Optional[int]:
    try:
        v = int(float(x))
    except Exception:
        return None
    if 1 <= v <= 10:
        return v
    if 1 <= v <= 100:
        return int((v - 1) / 10) + 1
    return None


_PREVENT_FULL_LOGOR_10Y = {
    ("female", "total_cvd"):
        "-3.860385 + 0.7716794*((age - 55)/10) + 0.0062109*(mmol_conversion(tc - hdl) - 3.5) - "
        "0.1547756*(mmol_conversion(hdl) - 1.3)/0.3 - 0.1933123*(min(sbp, 110) - 110)/20 + "
        "0.3071217*(max(sbp, 110) - 130)/20 + 0.496753*(dm) + 0.466605*(smoking) + "
        "0.4780697*(min(egfr, 60) - 60)/(-15) + 0.0529077*(max(egfr, 60) - 90)/(-15) + "
        "0.3034892*(bptreat) - 0.1556524*(statin) - 0.0667026*(bptreat)*(max(sbp, 110) - 130)/20 + "
        "0.1197879*(statin)*(mmol_conversion(tc - hdl) - 3.5) - 0.070257*(age - 55)/10*(mmol_conversion(tc - hdl) - 3.5) + "
        "0.0310635*(age - 55)/10*(mmol_conversion(hdl) - 1.3)/0.3 - 0.0875231*(age - 55)/10*(max(sbp, 110) - 130)/20 - "
        "0.2267102*(age - 55)/10*(dm) - 0.0676125*(age - 55)/10*(smoking) - 0.1493231*(age - 55)/10*(min(egfr, 60) - 60)/(-15) + "
        "((0.1361989*(2-sdicat(sdi))*(sdicat(sdi)) + 0.2261596*(sdicat(sdi)-1)*(0.5*sdicat(sdi))) if sdi is not None else (0.1804508)) + "
        "((0.1645922*math.log(adjust_uacr(uacr))) if uacr is not None else (0.0198413)) + "
        "((0.1298513*(hba1c-5.3)*(dm) + 0.1412555*(hba1c-5.3)*(1 - dm)) if hba1c is not None else (-0.0031658))",

    ("female", "ascvd"):
        "-4.291503 + 0.7023067*((age - 55)/10) + 0.0898765*((mmol_conversion(tc) - mmol_conversion(hdl)) - 3.5) - "
        "0.1407316*(mmol_conversion(hdl) - 1.3)/0.3 - 0.0256648*(min(sbp, 110) - 110)/20 + "
        "0.314511*(max(sbp, 110) - 130)/20 + 0.4487393*(dm) + 0.425949*(smoking) + "
        "0.3631734*(min(egfr, 60) - 60)/(-15) + 0.0449096*(max(egfr, 60) - 90)/(-15) + "
        "0.2133861*(bptreat) - 0.0678552*(statin) - 0.036088*(bptreat)*(max(sbp, 110) - 130)/20 + "
        "0.0844423*(statin)*((mmol_conversion(tc) - mmol_conversion(hdl)) - 3.5) - 0.0504475*(age - 55)/10*((mmol_conversion(tc) - mmol_conversion(hdl)) - 3.5) + "
        "0.0325985*(age - 55)/10*(mmol_conversion(hdl) - 1.3)/0.3 - 0.0979228*(age - 55)/10*(max(sbp, 110) - 130)/20 - "
        "0.2251783*(age - 55)/10*(dm) - 0.1075591*(age - 55)/10*(smoking) - 0.163771*(age - 55)/10*(min(egfr, 60) - 60)/(-15) + "
        "((0.1067741*(2-sdicat(sdi))*(sdicat(sdi)) + 0.1735343*(sdicat(sdi)-1)*(0.5*sdicat(sdi))) if sdi is not None else (0.1567115)) + "
        "((0.1142251*math.log(adjust_uacr(uacr))) if uacr is not None else (-0.0055863)) + "
        "((0.0940543*(hba1c-5.3)*(dm) + 0.1116486*(hba1c-5.3)*(1 - dm)) if hba1c is not None else (-0.0024798))",

    ("male", "total_cvd"):
        "-3.631387 + 0.7847578*((age - 55)/10) + 0.0534485*(mmol_conversion(tc - hdl) - 3.5) - "
        "0.0946487*(mmol_conversion(hdl) - 1.3)/0.3 - 0.4921973*(min(sbp, 110) - 110)/20 + "
        "0.2825685*(max(sbp, 110) - 130)/20 + 0.4527054*(dm) + 0.3871999*(smoking) - "
        "0.0485841*(min(bmi, 30) - 25)/5 + 0.3726929*(max(bmi, 30) - 30)/5 + "
        "0.4140627*(min(egfr, 60) - 60)/(-15) + 0.0244018*(max(egfr, 60) - 90)/(-15) + "
        "0.2602434*(bptreat) - 0.1063606*(statin) - 0.0450131*(bptreat)*(max(sbp, 110) - 130)/20 + "
        "0.139964*(statin)*(mmol_conversion(tc - hdl) - 3.5) - 0.0465287*(age - 55)/10*(mmol_conversion(tc - hdl) - 3.5) + "
        "0.0179247*(age - 55)/10*(mmol_conversion(hdl) - 1.3)/0.3 - 0.0999406*(age - 55)/10*(max(sbp, 110) - 130)/20 - "
        "0.2031801*(age - 55)/10*(dm) - 0.1149175*(age - 55)/10*(smoking) + 0.0068126*(age - 55)/10*(max(bmi, 30) - 30)/5 - "
        "0.1357792*(age - 55)/10*(min(egfr, 60) - 60)/(-15) + "
        "((0.1213034*(2-sdicat(sdi))*(sdicat(sdi)) + 0.1865146*(sdicat(sdi)-1)*(0.5*sdicat(sdi))) if sdi is not None else (0.1819138)) + "
        "((0.1887974*math.log(adjust_uacr(uacr))) if uacr is not None else (0.0916979)) + "
        "((0.1856442*(hba1c-5.3)*(dm) + 0.1833083*(hba1c-5.3)*(1 - dm)) if hba1c is not None else (-0.0143112))",

    ("male", "ascvd"):
        "-3.969788 + 0.7128741*((age - 55)/10) + 0.1465201*((mmol_conversion(tc) - mmol_conversion(hdl)) - 3.5) - "
        "0.1125794*(mmol_conversion(hdl) - 1.3)/0.3 - 0.1830509*(min(sbp, 110) - 110)/20 + "
        "0.350999*(max(sbp, 110) - 130)/20 + 0.4089407*(dm) + 0.3786529*(smoking) - "
        "0.0833107*(min(bmi, 30) - 25)/5 + 0.26999*(max(bmi, 30) - 30)/5 + "
        "0.3237833*(min(egfr, 60) - 60)/(-15) + 0.0297847*(max(egfr, 60) - 90)/(-15) + "
        "0.1779797*(bptreat) - 0.0145553*(statin) - 0.022474*(bptreat)*(max(sbp, 110) - 130)/20 + "
        "0.1119581*(statin)*((mmol_conversion(tc) - mmol_conversion(hdl)) - 3.5) - 0.0407326*(age - 55)/10*((mmol_conversion(tc) - mmol_conversion(hdl)) - 3.5) + "
        "0.0189978*(age - 55)/10*(mmol_conversion(hdl) - 1.3)/0.3 - 0.1035993*(age - 55)/10*(max(sbp, 110) - 130)/20 - "
        "0.2264091*(age - 55)/10*(dm) - 0.1328636*(age - 55)/10*(smoking) + 0.0182831*(age - 55)/10*(max(bmi, 30) - 30)/5 - "
        "0.1275693*(age - 55)/10*(min(egfr, 60) - 60)/(-15) + "
        "((0.0847634*(2-sdicat(sdi))*(sdicat(sdi)) + 0.1444688*(sdicat(sdi)-1)*(0.5*sdicat(sdi))) if sdi is not None else (0.1485802)) + "
        "((0.1486028*math.log(adjust_uacr(uacr))) if uacr is not None else (0.011608)) + "
        "((0.0768169*(hba1c-5.3)*(dm) + 0.0777295*(hba1c-5.3)*(1 - dm)) if hba1c is not None else (0.0092204))",
}

def _prevent_eval_logor(expr: str, *, age, tc, hdl, sbp, dm, smoking, bmi, egfr, bptreat, statin, uacr, hba1c, sdi) -> float:
    scope = {
        "min": min,
        "max": max,
        "math": math,
        "mmol_conversion": mmol_conversion,
        "adjust_uacr": adjust_uacr,
        "sdicat": sdicat,
        "age": float(age),
        "tc": float(tc),
        "hdl": float(hdl),
        "sbp": float(sbp),
        "dm": 1.0 if bool(dm) else 0.0,
        "smoking": 1.0 if bool(smoking) else 0.0,
        "bmi": float(bmi),
        "egfr": float(egfr),
        "bptreat": 1.0 if bool(bptreat) else 0.0,
        "statin": 1.0 if bool(statin) else 0.0,
        "uacr": (float(uacr) if uacr is not None else None),
        "hba1c": (float(hba1c) if hba1c is not None else None),
        "sdi": (int(sdi) if sdi is not None else None),
    }
    return float(eval(expr, {"__builtins__": {}}, scope))

def prevent10_total_and_ascvd(p: Patient, trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    req = ["age","sex","tc","hdl","sbp","bp_treated","smoking","diabetes","bmi","egfr","lipid_lowering"]
    missing = [k for k in req if not p.has(k)]
    if missing:
        add_trace(trace, "PREVENT_missing_inputs", missing, "PREVENT not calculated")
        return {
            "total_cvd_10y_pct": None,
            "ascvd_10y_pct": None,
            "missing": missing,
            "notes": "PREVENT not calculated (missing required inputs).",
        }

    age = int(p.get("age"))
    if age < 30 or age > 79:
        add_trace(trace, "PREVENT_age_out_of_range", age, "Validated for ages 30–79")
        return {
            "total_cvd_10y_pct": None,
            "ascvd_10y_pct": None,
            "missing": [],
            "notes": "PREVENT validated for ages 30–79.",
        }

    sex_raw = str(p.get("sex","")).lower()
    sex_key = "female" if sex_raw in ("f","female") else "male"

    tc = safe_float(p.get("tc"), 0)
    hdl = safe_float(p.get("hdl"), 0)
    sbp = safe_float(p.get("sbp"), 0)
    bmi = safe_float(p.get("bmi"), 0)
    egfr = safe_float(p.get("egfr"), 0)

    if tc <= 0 or hdl <= 0 or sbp <= 0 or bmi <= 0 or egfr <= 0:
        add_trace(trace, "PREVENT_invalid_inputs", {"tc":tc,"hdl":hdl,"sbp":sbp,"bmi":bmi,"egfr":egfr}, "PREVENT not calculated")
        return {
            "total_cvd_10y_pct": None,
            "ascvd_10y_pct": None,
            "missing": [],
            "notes": "PREVENT not calculated (invalid inputs).",
        }

    dm = bool(p.get("diabetes"))
    smoking = bool(p.get("smoking"))
    bptreat = bool(p.get("bp_treated"))
    statin = bool(p.get("lipid_lowering"))

    uacr = float(p.get("uacr")) if p.has("uacr") else None
    hba1c = None
    if p.has("hba1c"):
        hba1c = float(p.get("hba1c"))
    elif p.has("a1c"):
        hba1c = float(p.get("a1c"))

    sdi = None
    if p.has("sdi"):
        sdi = sdi_to_decile(p.get("sdi"))
    elif p.has("sdi_decile"):
        sdi = sdi_to_decile(p.get("sdi_decile"))

    if uacr is not None and uacr < 0:
        add_trace(trace, "PREVENT_uacr_invalid", uacr, "UACR < 0 (ignored)")
        uacr = None
    if hba1c is not None and hba1c <= 0:
        add_trace(trace, "PREVENT_hba1c_invalid", hba1c, "HbA1c <= 0 (ignored)")
        hba1c = None
    if sdi is not None and not (1 <= int(sdi) <= 10):
        add_trace(trace, "PREVENT_sdi_invalid", sdi, "SDI out of range (ignored)")
        sdi = None

    logor_total = _prevent_eval_logor(
        _PREVENT_FULL_LOGOR_10Y[(sex_key, "total_cvd")],
        age=age, tc=tc, hdl=hdl, sbp=sbp, dm=dm, smoking=smoking, bmi=bmi, egfr=egfr,
        bptreat=bptreat, statin=statin, uacr=uacr, hba1c=hba1c, sdi=sdi,
    )
    logor_ascvd = _prevent_eval_logor(
        _PREVENT_FULL_LOGOR_10Y[(sex_key, "ascvd")],
        age=age, tc=tc, hdl=hdl, sbp=sbp, dm=dm, smoking=smoking, bmi=bmi, egfr=egfr,
        bptreat=bptreat, statin=statin, uacr=uacr, hba1c=hba1c, sdi=sdi,
    )

    total_pct = _prevent_logistic_pct(logor_total)
    ascvd_pct = _prevent_logistic_pct(logor_ascvd)

    add_trace(
        trace,
        "PREVENT_calculated",
        {"sex": sex_key, "total": total_pct, "ascvd": ascvd_pct, "uacr": (uacr is not None), "hba1c": (hba1c is not None), "sdi": (sdi is not None)},
        "PREVENT 10y calculated (population model, full equations)",
    )

    return {
        "total_cvd_10y_pct": total_pct,
        "ascvd_10y_pct": ascvd_pct,
        "missing": [],
        "notes": "PREVENT full equations (AHAprevent v1.0.0): 10y total CVD + 10y ASCVD.",
    }


# ============================================================
# ASCVD PCE — 2019 interpretation; Epic-aligned behavior
# ============================================================

def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def _pce_category(risk_pct: float) -> str:
    if risk_pct < 5:
        return "Low (<5%)"
    if risk_pct < 7.5:
        return "Borderline (5–7.4%)"
    if risk_pct < 20:
        return "Intermediate (7.5–19.9%)"
    return "High (≥20%)"

def ascvd_pce_10y_risk_epic_2019(p: Patient, trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Epic-aligned 10-year ASCVD risk estimate under 2019 ACC/AHA guideline use of PCE.

    Key alignment choices (to reduce mismatch anxiety):
    - Uses standard PCE coefficients (race/sex specific) and 40–79 validation window
    - Non-Black / "other" races default to non-Black ("white") coefficients (Epic/ACC tool behavior)
    - Clips physiologic inputs to typical tool ranges before ln() to prevent extreme artifacts
    - Rounds to 1 decimal and returns standard risk categories
    """
    # Standard PCE coefficients (the underlying equation remains the same; 2019 refers to guideline interpretation & workflow use)
    PCE = {
        ("white", "female"): {"s0": 0.9665, "mean": -29.18,
            "ln_age": -29.799, "ln_age_sq": 4.884, "ln_tc": 13.540, "ln_age_ln_tc": -3.114,
            "ln_hdl": -13.578, "ln_age_ln_hdl": 3.149,
            "ln_sbp_treated": 2.019, "ln_sbp_untreated": 1.957,
            "smoker": 7.574, "ln_age_smoker": -1.665,
            "diabetes": 0.661
        },
        ("black", "female"): {"s0": 0.9533, "mean": 86.61,
            "ln_age": 17.114, "ln_tc": 0.940,
            "ln_hdl": -18.920, "ln_age_ln_hdl": 4.475,
            "ln_sbp_treated": 29.291, "ln_age_ln_sbp_treated": -6.432,
            "ln_sbp_untreated": 27.820, "ln_age_ln_sbp_untreated": -6.087,
            "smoker": 0.691, "diabetes": 0.874
        },
        ("white", "male"): {"s0": 0.9144, "mean": 61.18,
            "ln_age": 12.344, "ln_tc": 11.853, "ln_age_ln_tc": -2.664,
            "ln_hdl": -7.990, "ln_age_ln_hdl": 1.769,
            "ln_sbp_treated": 1.797, "ln_sbp_untreated": 1.764,
            "smoker": 7.837, "ln_age_smoker": -1.795,
            "diabetes": 0.658
        },
        ("black", "male"): {"s0": 0.8954, "mean": 19.54,
            "ln_age": 2.469, "ln_tc": 0.302, "ln_hdl": -0.307,
            "ln_sbp_treated": 1.916, "ln_sbp_untreated": 1.809,
            "smoker": 0.549, "diabetes": 0.645
        },
    }

    req = ["age","sex","race","tc","hdl","sbp","bp_treated","smoking","diabetes"]
    missing = [k for k in req if not p.has(k)]
    if missing:
        add_trace(trace, "PCE_missing_inputs", missing, "ASCVD PCE not calculated")
        return {"risk_pct": None, "missing": missing, "notes": "Missing required inputs for ASCVD PCE."}

    try:
        age = int(p.get("age"))
    except Exception:
        add_trace(trace, "PCE_age_invalid", p.get("age"), "Invalid age — skipping ASCVD PCE")
        return {"risk_pct": None, "missing": [], "notes": "Invalid age input."}

    if age < 40 or age > 79:
        add_trace(trace, "PCE_age_out_of_range", age, "Validated for ages 40–79")
        return {"risk_pct": None, "missing": [], "notes": "ASCVD PCE validated for ages 40–79."}

    sex = str(p.get("sex", "")).strip().lower()
    sex_key = "male" if sex in ("m","male") else "female"

    race = str(p.get("race", "")).strip().lower()
    race_key = "black" if race in ("black","african american","african-american") else "white"

    c = PCE.get((race_key, sex_key))
    if not c:
        add_trace(trace, "PCE_race_sex_invalid", (race_key, sex_key), "Invalid race/sex for coefficients")
        return {"risk_pct": None, "missing": [], "notes": "Invalid race/sex for ASCVD PCE."}

    # Tool-aligned clipping to avoid extreme ln() artifacts & reduce cross-tool mismatch.
    # These are pragmatic bounds used by many implementations (ACC-style).
    tc = _clip(safe_float(p.get("tc")), 130.0, 320.0)
    hdl = _clip(safe_float(p.get("hdl")), 20.0, 100.0)
    sbp = _clip(safe_float(p.get("sbp")), 90.0, 200.0)

    treated = bool(p.get("bp_treated"))
    smoker = bool(p.get("smoking"))
    dm = bool(p.get("diabetes"))

    try:
        ln_age = math.log(_clip(float(age), 40.0, 79.0))
        ln_tc = math.log(tc)
        ln_hdl = math.log(hdl)
        ln_sbp = math.log(sbp)
    except Exception as e:
        add_trace(trace, "PCE_log_error", str(e), "Log error in ASCVD PCE")
        return {"risk_pct": None, "missing": [], "notes": "Log error in ASCVD PCE (invalid input)."}

    lp = 0.0
    lp += c.get("ln_age", 0) * ln_age
    if "ln_age_sq" in c:
        lp += c["ln_age_sq"] * (ln_age ** 2)

    lp += c.get("ln_tc", 0) * ln_tc
    if "ln_age_ln_tc" in c:
        lp += c["ln_age_ln_tc"] * (ln_age * ln_tc)

    lp += c.get("ln_hdl", 0) * ln_hdl
    if "ln_age_ln_hdl" in c:
        lp += c["ln_age_ln_hdl"] * (ln_age * ln_hdl)

    if treated:
        lp += c.get("ln_sbp_treated", 0) * ln_sbp
        if "ln_age_ln_sbp_treated" in c:
            lp += c["ln_age_ln_sbp_treated"] * (ln_age * ln_sbp)
    else:
        lp += c.get("ln_sbp_untreated", 0) * ln_sbp
        if "ln_age_ln_sbp_untreated" in c:
            lp += c["ln_age_ln_sbp_untreated"] * (ln_age * ln_sbp)

    if smoker:
        lp += c.get("smoker", 0)
        if "ln_age_smoker" in c:
            lp += c["ln_age_smoker"] * ln_age

    if dm:
        lp += c.get("diabetes", 0)

    try:
        risk = 1 - (c["s0"] ** math.exp(lp - c["mean"]))
        risk = max(0.0, min(1.0, risk))
        risk_pct = round(risk * 100.0, 1)
    except Exception as e:
        add_trace(trace, "PCE_calc_error", str(e), "Error in ASCVD PCE calculation")
        return {"risk_pct": None, "missing": [], "notes": "Calculation error in ASCVD PCE."}

    cat = _pce_category(risk_pct)
    add_trace(trace, "PCE_calculated_epic2019", {"risk_pct": risk_pct, "category": cat}, "ASCVD PCE calculated (Epic-aligned)")

    return {
        "risk_pct": risk_pct,
        "category": cat,
        "missing": [],
        "notes": "ASCVD PCE (2019 guideline interpretation; Epic-aligned implementation).",
        "inputs_used": {
            "age": age,
            "sex": sex_key,
            "race_key": race_key,
            "tc_used": tc,
            "hdl_used": hdl,
            "sbp_used": sbp,
            "bp_treated": treated,
            "smoking": smoker,
            "diabetes": dm,
        },
    }

# ----------------------------
# CAC evidence model (plaque state only — no ordering logic)
# ----------------------------
def evidence_model(p: Patient, trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    if p.get("ascvd") is True:
        add_trace(trace, "Evidence_clinical_ASCVD", True, "Clinical ASCVD present")
        return {
            "clinical_ascvd": True,
            "cac_status": "Clinical ASCVD",
            "cac_value": None,
            "plaque_present": True,
            "burden_band": "Clinical ASCVD",
            "certainty": "High",
        }

    if not p.has("cac"):
        add_trace(trace, "Evidence_CAC_unknown", None, "CAC not available")
        return {
            "clinical_ascvd": False,
            "cac_status": "Unknown",
            "cac_value": None,
            "plaque_present": None,
            "burden_band": "Unknown",
            "certainty": "Low",
        }

    try:
        cac = int(p.get("cac"))
    except Exception:
        add_trace(trace, "CAC_invalid", p.get("cac"), "Invalid CAC value")
        return {
            "clinical_ascvd": False,
            "cac_status": "Unknown",
            "cac_value": None,
            "plaque_present": None,
            "burden_band": "Unknown",
            "certainty": "Low",
        }

    if cac == 0:
        add_trace(trace, "CAC_zero", 0, "No calcified plaque detected")
        return {
            "clinical_ascvd": False,
            "cac_status": "Known zero (CAC=0)",
            "cac_value": 0,
            "plaque_present": False,
            "burden_band": "None detected",
            "certainty": "Moderate",
        }

    if cac <= 9:
        band = "Minimal plaque"
    elif cac <= 99:
        band = "Low plaque burden"
    elif cac <= 399:
        band = "Moderate plaque burden"
    else:
        band = "High plaque burden"

    add_trace(trace, "CAC_positive", cac, f"Plaque present: {band}")
    return {
        "clinical_ascvd": False,
        "cac_status": f"Positive (CAC {cac})",
        "cac_value": cac,
        "plaque_present": True,
        "burden_band": band,
        "certainty": "High",
    }


# ----------------------------
# Risk Signal Score (RSS)
# ----------------------------
def clamp(x: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, x))

def rss_band(score: int) -> str:
    if score <= 19: return "Low"
    if score <= 39: return "Mild"
    if score <= 59: return "Moderate"
    if score <= 79: return "High"
    return "Very high"

def risk_signal_score(p: Patient, trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    burden = 0
    if p.get("ascvd") is True:
        burden = 55
        add_trace(trace, "RSS_burden_ASCVD", 55, "Clinical ASCVD burden")
    elif p.has("cac"):
        cac = safe_float(p.get("cac"), 0)
        if cac == 0: burden = 0
        elif cac <= 9: burden = 20
        elif cac <= 99: burden = 30
        elif cac <= 399: burden = 45
        else: burden = 55
        add_trace(trace, "RSS_burden_CAC", cac, f"Burden points={burden}")

    athero = 0
    if p.has("apob"):
        ap = safe_float(p.get("apob"))
        if ap < 80: athero = 0
        elif ap <= 99: athero = 8
        elif ap <= 119: athero = 15
        elif ap <= 149: athero = 20
        else: athero = 25
        add_trace(trace, "RSS_ApoB", ap, f"Atherogenic points={athero}")
    elif p.has("ldl"):
        ld = safe_float(p.get("ldl"))
        if ld < 100: athero = 0
        elif ld <= 129: athero = 5
        elif ld <= 159: athero = 10
        elif ld <= 189: athero = 15
        else: athero = 20
        add_trace(trace, "RSS_LDL", ld, f"Atherogenic points={athero}")

    genetics = 0
    if lpa_elevated(p, trace):
        genetics += 10
    if p.get("fhx") is True:
        genetics += 5
    genetics = min(genetics, 15)
    if genetics:
        add_trace(trace, "RSS_genetics", genetics, "Genetic contribution")

    infl = 0
    if p.has("hscrp") and safe_float(p.get("hscrp")) >= 2:
        infl += 5
    if has_chronic_inflammatory_disease(p):
        infl += 5
    infl = min(infl, 10)
    if infl:
        add_trace(trace, "RSS_inflammation", infl, "Inflammatory contribution")

    metab = 0
    if p.get("diabetes") is True:
        metab += 6
    if p.get("smoking") is True:
        metab += 4
    if a1c_status(p) == "prediabetes":
        metab += 2
    metab = min(metab, 10)
    if metab:
        add_trace(trace, "RSS_metabolic", metab, "Metabolic contribution")

    total = clamp(int(round(burden + athero + genetics + infl + metab)))
    add_trace(trace, "RSS_total", total, "Total RSS")

    return {
        "score": total,
        "band": rss_band(total),
        "note": "Biologic + plaque signal (not event probability).",
    }


# ----------------------------
# Data completeness / confidence
# ----------------------------
def completeness(p: Patient) -> Dict[str, Any]:
    core = ["age","sex","race","sbp","bp_treated","smoking","diabetes","tc","hdl"]
    enh = ["apob","lpa","cac","hscrp","a1c","ldl"]

    core_pct = int(sum(p.has(k) for k in core) / len(core) * 100)
    enh_pct = int(sum(p.has(k) for k in enh) / len(enh) * 100)

    overall = int(round(core_pct * 0.6 + enh_pct * 0.4))

    conf = "High" if overall >= 85 and enh_pct >= 50 else \
           "Moderate" if overall >= 60 else "Low"

    missing = [k for k in core + enh if not p.has(k)]

    return {
        "pct": overall,
        "confidence": conf,
        "core_pct": core_pct,
        "enhancer_pct": enh_pct,
        "top_missing": missing[:3],
        "missing": missing,
    }


# ----------------------------
# Anchors: near-term vs lifetime
# ----------------------------
def build_anchors(p: Patient, risk10: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    near = []
    if risk10.get("risk_pct") is not None:
        near.append(f"ASCVD PCE {risk10['risk_pct']}% ({risk10['category']})")
    else:
        near.append("ASCVD PCE not available")

    cs = evidence.get("cac_status", "Unknown")
    if cs.startswith("Known zero"):
        near.append("CAC=0 (low short-term plaque signal)")
    elif cs.startswith("Positive"):
        near.append(cs)
    else:
        near.append("CAC unknown")

    life = []
    if p.has("apob") and safe_float(p.get("apob")) >= 100:
        life.append(f"ApoB {fmt_int(p.get('apob'))}")
    elif not p.has("apob") and p.has("ldl") and safe_float(p.get("ldl")) >= 130:
        life.append(f"LDL-C {fmt_int(p.get('ldl'))}")

    if lpa_elevated_no_trace(p):
        life.append("Lp(a) elevated")

    if p.get("fhx") is True:
        life.append("Premature FHx")

    if inflammation_flags(p):
        life.append("Inflammation present")

    if p.get("diabetes") is True:
        life.append("Diabetes")
    elif a1c_status(p) == "prediabetes":
        life.append("Prediabetes")

    if p.get("smoking") is True:
        life.append("Smoking")

    if not life:
        life.append("No major lifetime accelerators detected")

    return {
        "nearTerm": {"summary": " / ".join(near), "factors": near},
        "lifetime": {"summary": " / ".join(life), "factors": life},
    }


# ----------------------------
# Trajectory note
# ----------------------------
def trajectory_note(p: Patient, risk10: Dict[str, Any]) -> str:
    if p.has("apob") and safe_float(p.get("apob")) >= 100:
        return "Rising atherogenic burden — track ApoB over time."
    if risk10.get("risk_pct", 0) >= 15:
        return "Elevated near-term risk — closer follow-up advised."
    if p.has("hscrp") and safe_float(p.get("hscrp")) >= 3:
        return "Inflammatory signal — address drivers and recheck."
    return "Stable profile with available data."

# ----------------------------
# Internal Levels 1–5 along the Risk Continuum
# ----------------------------
def _has_any_data(p: Patient) -> bool:
    return bool(p.data)

def posture_labels(level: int) -> str:
    labels = {
        0: "Level 0 — Not assessed (insufficient data)",
        1: "Level 1 — Minimal risk signal (no evidence of plaque with available data)",
        2: "Level 2 — Emerging risk signals (mild–moderate biology; plaque not proven)",
        3: "Level 3 — Actionable biologic risk (plaque possible; refine thoughtfully)",
        4: "Level 4 — Subclinical atherosclerosis present (early disease)",
        5: "Level 5 — Very high risk / ASCVD intensity (advanced plaque or clinical ASCVD)",
    }
    return labels.get(level, f"Level {level}")

def posture_level(p: Patient, evidence: Dict[str, Any], trace: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
    triggers: List[str] = []

    if evidence.get("clinical_ascvd"):
        triggers.append("Clinical ASCVD")
        add_trace(trace, "Level_override_ASCVD", True, "Level=5")
        return 5, triggers

    if evidence.get("plaque_present") is True:
        cac = evidence.get("cac_value")
        if isinstance(cac, int):
            if 1 <= cac <= 99:
                triggers.append(f"CAC {cac} (plaque present)")
                add_trace(trace, "Level_CAC_1_99", cac, "Level=4")
                return 4, triggers
            if cac >= 100:
                triggers.append(f"CAC {cac} (high plaque burden)")
                add_trace(trace, "Level_CAC_100_plus", cac, "Level=5")
                return 5, triggers

    high = False
    mild = False

    if p.has("apob") and safe_float(p.get("apob")) >= 100:
        high = True; triggers.append("ApoB≥100")
    elif p.has("ldl") and safe_float(p.get("ldl")) >= 130:
        high = True; triggers.append("LDL≥130")

    if lpa_elevated(p, trace):
        high = True; triggers.append("Lp(a) elevated")

    if p.get("fhx") is True:
        high = True; triggers.append("Premature FHx")

    if has_chronic_inflammatory_disease(p) or inflammation_flags(p):
        if has_chronic_inflammatory_disease(p):
            high = True
        triggers.append("Inflammation present")

    if p.get("diabetes") is True:
        high = True; triggers.append("Diabetes")
    if p.get("smoking") is True:
        high = True; triggers.append("Smoking")

    if not high:
        if p.has("apob") and 80 <= safe_float(p.get("apob")) <= 99:
            mild = True; triggers.append("ApoB 80–99")
        if p.has("ldl") and 100 <= safe_float(p.get("ldl")) <= 129:
            mild = True; triggers.append("LDL 100–129")
        if a1c_status(p) == "prediabetes":
            mild = True; triggers.append("Prediabetes")
        if p.has("hscrp") and safe_float(p.get("hscrp")) >= 2 and not has_chronic_inflammatory_disease(p):
            mild = True; triggers.append("hsCRP≥2")

    if high:
        add_trace(trace, "Level_high_biology", triggers[:4], "Level=3")
        return 3, triggers
    if mild:
        add_trace(trace, "Level_emerging_risk", triggers[:4], "Level=2")
        return 2, triggers

    if _has_any_data(p):
        add_trace(trace, "Level_low_biology", None, "Level=1")
        return 1, triggers

    return 0, triggers


# ----------------------------
# Targets + ESC goals (Level-based)
# ----------------------------
def levels_targets(level: int) -> Dict[str, int]:
    if level <= 2: return {"apob": 80, "ldl": 100}
    if level == 3: return {"apob": 80, "ldl": 100}
    if level == 4: return {"apob": 70, "ldl": 70}
    return {"apob": 60, "ldl": 70}

def esc_numeric_goals(level: int, clinical_ascvd: bool) -> str:
    if clinical_ascvd:
        return "ESC/EAS goals (clinical ASCVD): LDL-C <55 mg/dL; ApoB <65 mg/dL."
    if level >= 5:
        return "ESC/EAS goals (very high risk): LDL-C <55–70 mg/dL; ApoB <65–80 mg/dL."
    if level == 4:
        return "ESC/EAS goals (subclinical disease): LDL-C <70 mg/dL; ApoB <80 mg/dL."
    if level == 3:
        return "ESC/EAS goals (high biologic risk): LDL-C <100 mg/dL; ApoB <100 mg/dL."
    if level == 2:
        return "ESC/EAS goals: individualized; consider LDL-C <100 mg/dL if sustained risk."
    return "ESC/EAS goals: individualized by risk tier."

def atherosclerotic_disease_burden(p: Patient) -> str:
    if p.get("ascvd") is True:
        return "Present (clinical ASCVD)"
    if p.has("cac"):
        try:
            cac = int(p.get("cac"))
        except Exception:
            return "Unknown (CAC invalid)"
        return "Not detected (CAC=0)" if cac == 0 else f"Present (CAC {cac})"
    return "Unknown (CAC not available)"


# ----------------------------
# Deterministic driver ranking
# ----------------------------
def ranked_drivers(p: Patient, evidence: Dict[str, Any], trace: List[Dict[str, Any]]) -> List[str]:
    candidates: List[Tuple[int, str]] = []

    if p.get("ascvd") is True:
        candidates.append((10, "Clinical ASCVD"))
    elif evidence.get("plaque_present") is True and evidence.get("cac_value") is not None:
        candidates.append((10, f"CAC {int(evidence['cac_value'])}"))

    if p.has("apob") and safe_float(p.get("apob")) >= 100:
        candidates.append((20, f"ApoB {fmt_int(p.get('apob'))}"))
    elif p.has("ldl") and safe_float(p.get("ldl")) >= 130:
        candidates.append((20, f"LDL-C {fmt_int(p.get('ldl'))}"))

    if lpa_elevated(p, trace):
        candidates.append((30, "Lp(a) elevated"))

    if p.get("diabetes") is True:
        candidates.append((40, "Diabetes"))
    if p.get("smoking") is True:
        candidates.append((41, "Smoking"))

    if inflammation_flags(p) or has_chronic_inflammatory_disease(p):
        candidates.append((50, "Inflammatory signal"))

    if p.get("fhx") is True:
        candidates.append((60, "Premature family history"))

    if a1c_status(p) == "prediabetes":
        candidates.append((70, "Prediabetes"))

    candidates.sort(key=lambda x: (x[0], x[1]))
    ranked = [txt for _, txt in candidates]
    add_trace(trace, "Drivers_ranked", ranked, "Driver ranking applied")
    return ranked


# ----------------------------
# Level explainer for patient
# ----------------------------
def level_explainer_for_patient(level: int, evidence: Dict[str, Any], drivers: List[str]) -> str:
    cs = evidence.get("cac_status", "Unknown")
    top = "; ".join(drivers[:2]) if drivers else ""

    if level == 1:
        return (
            "Level 1 means we do not see a strong biologic or plaque signal with the data available; "
            "focus is maintaining healthy baseline habits and periodic reassessment."
        )
    if level == 2:
        return (
            f"Level 2 means early risk signals are emerging without proven plaque; best next step is completing "
            f"key missing data and a structured lifestyle sprint. Key signals: {top}."
        )
    if level == 3:
        suffix = ""
        if cs.startswith("Known zero"):
            suffix = " CAC=0 lowers short-term plaque signal, but biology may still justify action based on lifetime trajectory."
        elif cs == "Unknown":
            suffix = " Plaque status is unknown; clarification is optional and should be used only if it would change decisions."
        return (
            f"Level 3 means biologic risk is high enough to justify deliberate action and shared decision-making."
            f"{suffix} Key signals: {top}."
        )
    if level == 4:
        return (
            f"Level 4 means subclinical plaque is present (early disease); prevention should be more decisive and target-driven. "
            f"Key signals: {top}."
        )
    if level == 5:
        if evidence.get("clinical_ascvd"):
            return (
                f"Level 5 means clinical ASCVD is present; focus is secondary prevention intensity and aggressive risk reduction. "
                f"Key signals: {top}."
            )
        return (
            f"Level 5 means very high plaque burden or disease-equivalent intensity; management should be aggressive and target-driven. "
            f"Key signals: {top}."
        )
    return "This Level reflects the system’s best estimate of risk posture based on available data."


# ----------------------------
# Next actions (brief)
# ----------------------------
def next_actions(p: Patient, level: int, targets: Dict[str, int], evidence: Dict[str, Any]) -> List[str]:
    acts: List[str] = []

    if p.has("apob") and safe_float(p.get("apob")) > targets["apob"]:
        acts.append(f"Reduce ApoB toward <{targets['apob']} mg/dL.")
    if p.has("ldl") and safe_float(p.get("ldl")) > targets["ldl"]:
        acts.append(f"Reduce LDL-C toward <{targets['ldl']} mg/dL.")

    if str(evidence.get("cac_status", "")).startswith("Known zero") and level in (2, 3):
        acts.append("CAC=0 supports staged escalation; consider repeat CAC in 3–5y if risk persists.")

    return acts[:2]

# ----------------------------
# Recommendation strength + clinician confidence label
# ----------------------------
def recommendation_strength(confidence: Dict[str, Any]) -> str:
    conf = (confidence or {}).get("confidence", "Low")
    if conf == "High":
        return "Recommended"
    if conf == "Moderate":
        return "Consider"
    return "Pending more data"

def decision_confidence_label(strength: str) -> str:
    return {
        "Recommended": "High confidence",
        "Consider": "Moderate confidence",
        "Pending more data": "Low confidence",
    }.get(strength, "—")


# ----------------------------
# CAC decision support (ordering logic)
# ----------------------------
def _decision_uncertainty_proxy(p: Patient, risk10: Dict[str, Any], level: int) -> bool:
    """
    Proxy for 'I’m not sure what to do' using available signals.
    Conservative by design.
    """
    if p.get("ascvd") is True or p.get("diabetes") is True:
        return False

    rp = risk10.get("risk_pct")
    if rp is None:
        # If we can't compute PCE, we usually shouldn't jump to imaging.
        return False

    # Gray zone where CAC *might* change confidence: 5–20%
    in_gray = (5.0 <= float(rp) <= 20.0)

    # Level 3 can also represent uncertainty, but CAC should not be reflexive.
    return bool(in_gray and level in (2, 3))

def _dominant_high_risk_driver_present(p: Patient, evidence: Dict[str, Any]) -> bool:
    """
    If a dominant driver already justifies intensity, CAC rarely changes management.
    """
    if evidence.get("clinical_ascvd") is True:
        return True
    if evidence.get("plaque_present") is True:
        return True
    if p.get("diabetes") is True:
        return True
    if p.has("apob") and safe_float(p.get("apob")) >= 130:
        return True
    if (not p.has("apob")) and p.has("ldl") and safe_float(p.get("ldl")) >= 190:
        return True
    if p.get("smoking") is True and safe_float(p.get("sbp")) >= 150:
        return True
    return False

def _labs_first_needed(p: Patient) -> List[str]:
    """
    Labs-first philosophy: missing ApoB/Lp(a) should defer CAC in most cases.
    Returns list of suggested labs.
    """
    labs = []
    if not p.has("apob"):
        labs.append("ApoB")
    if not p.has("lpa"):
        labs.append("Lp(a)")
    return labs

def cac_decision_support(
    p: Patient,
    evidence: Dict[str, Any],
    risk10: Dict[str, Any],
    level: int,
    confidence: Dict[str, Any],
    trace: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Returns CAC guidance as one of:
      - suppressed: not recommended (won't change management or already known)
      - deferred: get labs first (ApoB/Lp(a) missing) unless special need
      - optional: reasonable clarifier if uncertainty persists
    This is intentionally conservative to prevent CAC pressure.
    """
    # If CAC already known, don't "recommend" ordering.
    if evidence.get("cac_status") != "Unknown":
        add_trace(trace, "CAC_ordering_suppressed_known", evidence.get("cac_status"), "CAC already known")
        return {
            "status": "suppressed",
            "reason": "CAC already available; use existing result.",
            "message": None,
            "reasons": ["CAC already known"],
        }

    # Clinical ASCVD / clear intensity drivers -> no CAC.
    if _dominant_high_risk_driver_present(p, evidence):
        add_trace(trace, "CAC_ordering_suppressed_dominant_driver", True, "Dominant driver makes CAC low-yield")
        return {
            "status": "suppressed",
            "reason": "Management already justified by dominant risk driver(s).",
            "message": (
                "CAC is not required for appropriate management because treatment intensity is already justified "
                "by current risk drivers."
            ),
            "reasons": ["Dominant driver present → CAC unlikely to change management"],
        }

    # If decision uncertainty proxy is false, suppress.
    if not _decision_uncertainty_proxy(p, risk10, level):
        add_trace(trace, "CAC_ordering_suppressed_not_uncertain", {"risk": risk10.get("risk_pct"), "level": level}, "Not in uncertainty zone")
        return {
            "status": "suppressed",
            "reason": "Not in a state where CAC is likely to change decisions.",
            "message": (
                "CAC is not routinely recommended here. Consider CAC only if you are truly uncertain and the result "
                "would change treatment intensity."
            ),
            "reasons": ["Not in gray-zone uncertainty where CAC changes decisions"],
        }

    # Labs-first gate
    labs_needed = _labs_first_needed(p)
    if labs_needed:
        add_trace(trace, "CAC_ordering_deferred_labs_first", labs_needed, "Defer CAC until key labs available")
        return {
            "status": "deferred",
            "reason": "Obtain low-harm blood-based clarifiers first.",
            "message": (
                f"Structural clarification (CAC) is optional but should generally be deferred until {', '.join(labs_needed)} "
                f"are available, because these labs often resolve uncertainty without imaging."
            ),
            "reasons": [f"Missing {', '.join(labs_needed)} → labs-first sequencing"],
            "labs_first": labs_needed,
        }

    # If labs are available and uncertainty persists -> CAC optional
    add_trace(trace, "CAC_ordering_optional", {"risk": risk10.get("risk_pct"), "level": level}, "CAC may refine confidence")
    return {
        "status": "optional",
        "reason": "Residual uncertainty after labs; CAC may refine confidence.",
        "message": (
            "CAC may be considered as a confidence/refinement tool if the result would change whether you start therapy "
            "or how aggressive you are. If you would treat (or defer) regardless, CAC is unlikely to add value."
        ),
        "reasons": ["Gray-zone risk + labs available → CAC can refine confidence"],
    }


# ----------------------------
# Aspirin module
# ----------------------------
def _bleeding_flags(p: Patient) -> Tuple[bool, List[str]]:
    flags: List[str] = []
    for k, label in [
        ("bleed_gi", "Prior GI bleed/ulcer"),
        ("bleed_ich", "Prior intracranial hemorrhage"),
        ("bleed_anticoag", "Anticoagulant use"),
        ("bleed_nsaid", "Chronic NSAID/steroid use"),
        ("bleed_disorder", "Bleeding disorder/thrombocytopenia"),
        ("bleed_ckd", "Advanced CKD / eGFR<45"),
    ]:
        if p.get(k) is True:
            flags.append(label)
    return (len(flags) > 0), flags

def aspirin_explanation(status: str, rationale: List[str]) -> str:
    reasons = [str(x).strip() for x in (rationale or []) if str(x).strip()]
    if not reasons:
        return ""
    if len(reasons) <= 3:
        return "Reasons: " + "; ".join(reasons) + "."
    return "Reasons: " + "; ".join(reasons[:3]) + "."

def aspirin_advice(p: Patient, risk10: Dict[str, Any], trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    age = int(p.get("age", 0)) if p.has("age") else None
    cac = int(p.get("cac", 0)) if p.has("cac") else None
    ascvd = (p.get("ascvd") is True)
    bleed_high, bleed_flags = _bleeding_flags(p)

    if ascvd:
        add_trace(trace, "Aspirin_ASCVD", True, "Secondary prevention")
        status = "Secondary prevention: typically indicated if no contraindication"
        rationale = ["ASCVD present"]
        if bleed_flags:
            status = "Secondary prevention: consider but bleeding risk flags present"
            rationale = bleed_flags
        return {
            "status": status,
            "rationale": rationale,
            "explanation": aspirin_explanation(status, rationale),
            "bleeding_risk_high": bleed_high,
            "bleeding_flags": bleed_flags,
        }

    if age is None:
        add_trace(trace, "Aspirin_age_missing", None, "Not assessed")
        status = "Not assessed"
        rationale = ["Age missing"]
        return {
            "status": status,
            "rationale": rationale,
            "explanation": aspirin_explanation(status, rationale),
            "bleeding_risk_high": bleed_high,
            "bleeding_flags": bleed_flags,
        }

    if age < 40 or age >= 70:
        add_trace(trace, "Aspirin_age_out_of_range", age, "Avoid primary prevention aspirin by age")
        status = "Avoid (primary prevention)"
        rationale = [f"Age {age} (bleeding risk likely outweighs benefit)"]
        return {
            "status": status,
            "rationale": rationale,
            "explanation": aspirin_explanation(status, rationale),
            "bleeding_risk_high": bleed_high,
            "bleeding_flags": bleed_flags,
        }

    if bleed_flags:
        add_trace(trace, "Aspirin_bleed_flags", bleed_flags, "Avoid due to bleed risk")
        status = "Avoid (primary prevention)"
        rationale = ["High bleeding risk: " + "; ".join(bleed_flags)]
        return {
            "status": status,
            "rationale": rationale,
            "explanation": aspirin_explanation(status, rationale),
            "bleeding_risk_high": bleed_high,
            "bleeding_flags": bleed_flags,
        }

    risk_pct = risk10.get("risk_pct")
    risk_ok = (risk_pct is not None and float(risk_pct) >= 10.0)
    cac_ok = (cac is not None and int(cac) >= 100)

    if cac_ok or risk_ok:
        reasons = []
        if cac_ok:
            reasons.append("CAC ≥100")
        if risk_ok:
            reasons.append(f"ASCVD PCE 10-year risk ≥10% ({risk_pct}%)")
        reasons.append("Bleeding risk low by available flags")
        add_trace(trace, "Aspirin_consider", reasons, "Consider aspirin shared decision")
        status = "Consider (shared decision)"
        rationale = reasons
        return {
            "status": status,
            "rationale": rationale,
            "explanation": aspirin_explanation(status, rationale),
            "bleeding_risk_high": bleed_high,
            "bleeding_flags": bleed_flags,
        }

    add_trace(trace, "Aspirin_avoid_low_benefit", risk_pct, "Avoid/individualize")
    status = "Avoid / individualize"
    rationale = ["Primary prevention benefit likely small at current risk level"]
    return {
        "status": status,
        "rationale": rationale,
        "explanation": aspirin_explanation(status, rationale),
        "bleeding_risk_high": bleed_high,
        "bleeding_flags": bleed_flags,
    }


# ----------------------------
# Level explanation object (clinician-facing + patient explainer)
# ----------------------------
def explain_levels(
    p: Patient,
    level: int,
    evidence: Dict[str, Any],
    anchors: Dict[str, Any],
    confidence: Dict[str, Any],
    drivers_all: List[str],
    trace: List[Dict[str, Any]],
    risk10: Dict[str, Any],
) -> Dict[str, Any]:
    strength = recommendation_strength(confidence)
    decision_conf = decision_confidence_label(strength)

    clinical = bool(evidence.get("clinical_ascvd"))
    cs = str(evidence.get("cac_status", "Unknown"))

    if clinical:
        meaning = "Clinical ASCVD is present; management reflects secondary prevention intensity."
        base_plan = "High-intensity lipid lowering; aggressive targets; address all enhancers."
    elif level == 1:
        meaning = "Low biologic risk signals and no evidence of plaque with current data."
        base_plan = "Lifestyle-first; periodic reassessment; avoid over-medicalization."
    elif level == 2:
        meaning = "Emerging risk without proven plaque."
        base_plan = "Complete key data; lifestyle sprint; shared decision on therapy based on trajectory."
    elif level == 3:
        meaning = "Actionable biologic risk; plaque may be present but is not yet proven."
        if cs.startswith("Known zero"):
            base_plan = "Shared decision toward lipid lowering; CAC=0 supports staged escalation; treat enhancers aggressively."
        elif cs == "Unknown":
            base_plan = (
                "Shared decision toward lipid lowering. Missing plaque data does not require immediate imaging; "
                "use CAC only if it would change the decision."
            )
        else:
            base_plan = "Shared decision toward lipid lowering; target-driven prevention."
    elif level == 4:
        meaning = "Subclinical plaque is present (early disease)."
        base_plan = "Treat like early disease: statin generally recommended; target-driven therapy; reassess response."
    else:
        meaning = "High plaque burden or disease-equivalent intensity."
        base_plan = "Aggressive lipid targets; consider add-ons; treat as disease-equivalent intensity."

    prefix = {
        "Recommended": "Recommended: ",
        "Consider": "Consider: ",
        "Pending more data": "Pending more data: ",
    }.get(strength, "")

    plan = prefix + base_plan

    why = drivers_all[:3]
    if strength == "Pending more data":
        miss = confidence.get("top_missing") or []
        if miss:
            why = why[:2] + [f"Key missing data: {', '.join(miss)}"]
        else:
            why = why[:2] + ["Key missing data limits decisiveness"]

    add_trace(trace, "Recommendation_strength", strength, "Confidence-gated plan applied")

    explainer = level_explainer_for_patient(level, evidence, drivers_all[:3])

    return {
        "postureLevel": level,
        "managementLevel": level,
        "label": posture_labels(level),
        "meaning": meaning,
        "why": why,
        "defaultPosture": plan,
        "recommendationStrength": strength,
        "decisionConfidence": decision_conf,
        "evidence": evidence,
        "anchorsSummary": {
            "nearTerm": anchors["nearTerm"]["summary"],
            "lifetime": anchors["lifetime"]["summary"],
        },
        "explainer": explainer,
        "trajectoryNote": trajectory_note(p, risk10),
    }

# ----------------------------
# Public API
# ----------------------------
def evaluate(p: Patient) -> Dict[str, Any]:
    trace: List[Dict[str, Any]] = []
    add_trace(trace, "Engine_start", VERSION["levels"], "Begin evaluation")

    evidence = evidence_model(p, trace)

    # Epic-aligned ASCVD PCE (2019 interpretation)
    risk10 = ascvd_pce_10y_risk_epic_2019(p, trace)

    conf = completeness(p)
    rs = risk_signal_score(p, trace)
    anchors = build_anchors(p, risk10, evidence)
    prevent10 = prevent10_total_and_ascvd(p, trace)

    level, level_triggers = posture_level(p, evidence, trace)
    targets = levels_targets(level)
    burden_str = atherosclerotic_disease_burden(p)

    drivers_all = ranked_drivers(p, evidence, trace)
    drivers_top = drivers_all[:3]
    rs = {**rs, "drivers": drivers_top}

    asp = aspirin_advice(p, risk10, trace)

    # New CAC decision support (ordering logic decoupled from Levels)
    cac_support = cac_decision_support(
        p=p,
        evidence=evidence,
        risk10=risk10,
        level=level,
        confidence=conf,
        trace=trace,
    )

    levels_obj = explain_levels(
        p=p,
        level=level,
        evidence=evidence,
        anchors=anchors,
        confidence=conf,
        drivers_all=drivers_all,
        trace=trace,
        risk10=risk10,
    )
    levels_obj["triggers"] = sorted(set(level_triggers))

    next_acts = next_actions(p, level, targets, evidence)

    insights = {
        "cac_decision_support": cac_support,   # <— single source of truth for CAC ordering guidance
        "decision_robustness": conf.get("confidence", "Low"),
        "decision_robustness_note": (
            "Higher when plaque known or key labs available; lower when key inputs missing."
        ),
    }

    out = {
        "version": VERSION,
        "system": SYSTEM_NAME,
        "levels": levels_obj,
        "riskSignal": rs,
        "ascvdPce10yRisk": risk10,  # renamed key (but keep compatibility below)
        "pooledCohortEquations10yAscvdRisk": risk10,  # backward-compatible alias for existing app usage
        "prevent10": prevent10,
        "targets": targets,
        "confidence": conf,
        "diseaseBurden": burden_str,
        "drivers": drivers_top,
        "drivers_all": drivers_all,
        "nextActions": next_acts,
        "escGoals": esc_numeric_goals(level, clinical_ascvd=bool(evidence.get("clinical_ascvd"))),
        "aspirin": asp,
        "anchors": anchors,
        "lpaInfo": lpa_info(p, trace),
        "insights": insights,
        "trace": trace,
        "trajectoryNote": trajectory_note(p, risk10),
    }

    add_trace(trace, "Engine_end", VERSION["levels"], "Evaluation complete")
    return out


# ----------------------------
# Quick text output (note-friendly)
# ----------------------------
def render_quick_text(p: Patient, out: Dict[str, Any]) -> str:
    lvl = out["levels"]
    rs = out["riskSignal"]
    risk10 = out["pooledCohortEquations10yAscvdRisk"]
    t = out["targets"]
    conf = out["confidence"]
    prev = out.get("prevent10", {}) or {}
    ins = out.get("insights", {}) or {}
    cac_sup = (ins.get("cac_decision_support") or {})

    lines: List[str] = []
    lines.append(f"{SYSTEM_NAME} {out['version']['levels']} — Quick Reference")

    lines.append(
        f"Level {lvl.get('postureLevel', lvl.get('level'))}: "
        f"{lvl['label'].split('—',1)[1].strip()}"
    )

    if lvl.get("explainer"):
        lines.append(f"Level explainer: {lvl.get('explainer')}")

    ev = lvl.get("evidence", {})
    lines.append(f"Evidence: {ev.get('cac_status','Unknown')} / burden: {ev.get('burden_band','Unknown')}")
    lines.append(f"Atherosclerotic disease burden: {out['diseaseBurden']}")

    miss = ", ".join(conf["top_missing"]) if conf["top_missing"] else "none"
    lines.append(f"Data completeness: {conf['confidence']} ({conf['pct']}% complete; missing: {miss})")
    lines.append(f"Decision confidence: {lvl.get('decisionConfidence','—')}")
    lines.append("")

    # CAC ordering guidance (decoupled from Level pressure)
    if cac_sup:
        status = cac_sup.get("status")
        msg = cac_sup.get("message")
        if status == "optional":
            lines.append("CAC guidance: Optional (confidence/refinement tool)")
        elif status == "deferred":
            lines.append("CAC guidance: Deferred (labs-first)")
        elif status == "suppressed":
            lines.append("CAC guidance: Suppressed (low-yield)")
        else:
            lines.append("CAC guidance: —")

        if msg:
            lines.append(msg)
        labs_first = cac_sup.get("labs_first") or []
        if labs_first:
            lines.append("First-line clarifiers: " + ", ".join(labs_first))
        reasons = cac_sup.get("reasons") or []
        if reasons:
            lines.append("CAC reasoning: " + "; ".join(reasons[:3]))
        lines.append("")

    lines.append(f"Risk Signal Score: {rs['score']}/100 ({rs['band']}) — {rs['note']}")

    if risk10.get("risk_pct") is not None:
        lines.append(f"ASCVD PCE (10-year): {risk10['risk_pct']}% ({risk10['category']})")
    else:
        if risk10.get("missing"):
            lines.append(f"ASCVD PCE (10-year): not calculated (missing {', '.join(risk10['missing'][:3])})")
        else:
            lines.append("ASCVD PCE (10-year): not calculated")

    if prev.get("total_cvd_10y_pct") is not None or prev.get("ascvd_10y_pct") is not None:
        lines.append(
            f"PREVENT (10-year): total CVD {prev.get('total_cvd_10y_pct','—')}% / ASCVD {prev.get('ascvd_10y_pct','—')}%"
        )
    else:
        if prev.get("missing"):
            lines.append(f"PREVENT (10-year): not calculated (missing {', '.join(prev['missing'][:3])})")
        else:
            lines.append("PREVENT (10-year): not calculated")

    lines.append(
        "Note: Risk Signal reflects biologic/plaque signal; calculators estimate event probability—discordance can be informative."
    )

    if out.get("drivers"):
        lines.append("Drivers: " + "; ".join(out["drivers"]))

    lines.append("Targets")
    if p.has("apob"):
        lines.append(f"• ApoB: {fmt_int(p.get('apob'))} mg/dL → target <{t['apob']} mg/dL")
    if p.has("ldl"):
        lines.append(f"• LDL-C: {fmt_int(p.get('ldl'))} mg/dL → target <{t['ldl']} mg/dL")

    lines.append(out["escGoals"])

    if out.get("nextActions"):
        lines.append("Next: " + " / ".join(out["nextActions"]))

    lines.append(f"Aspirin 81 mg: {out['aspirin']['status']}")

    if out.get("trajectoryNote"):
        lines.append(f"Trajectory note: {out['trajectoryNote']}")

    return "\n".join(lines)

# ============================================================
# COMPATIBILITY PATCH (drop-in; paste at END of file)
# Restores legacy exports expected by app.py v2.8
# ============================================================

# Debug sentinel used by app.py (safe to expose)
try:
    PCE_DEBUG_SENTINEL
except NameError:
    PCE_DEBUG_SENTINEL = "PCE_EPIC_2019_ALIGNED_v2_9"

# short_why helper expected by app.py import
def short_why(items: List[str], max_items: int = 2) -> str:
    if not items:
        return ""
    cleaned = [str(x).strip() for x in items if str(x).strip()]
    return "; ".join(cleaned[:max_items])

# Legend helper (optional but keeps lvl.get("legend") populated)
def levels_legend_compact() -> List[str]:
    return [
        "Level 1: minimal signal → reinforce basics, periodic reassess",
        "Level 2A: mild/isolated signal → education, complete data, lifestyle sprint",
        "Level 2B: converging signals → lifestyle sprint + shorter reassess",
        "Level 3A: actionable biologic risk → shared decision; consider therapy based on trajectory",
        "Level 3B: biologic risk + enhancers → therapy often favored; refine with CAC if unknown",
        "Level 4: subclinical plaque present → treat like early disease; target-driven therapy",
        "Level 5: very high risk / ASCVD → secondary prevention intensity; maximize tolerated therapy",
    ]

def _level3_sublevel_compat(p: Patient, risk10: Dict[str, Any]) -> str:
    """
    Matches your prior semantics loosely:
    - 3B if enhancers present (Lp(a) elevated OR FHx OR inflammation)
    - 3C if intermediate risk (>=7.5) without enhancers
    - 3A otherwise
    """
    enh = 0
    try:
        # Lp(a) elevated without trace
        if lpa_elevated_no_trace(p):
            enh += 1
    except Exception:
        pass
    if p.get("fhx") is True:
        enh += 1
    try:
        if inflammation_flags(p) or has_chronic_inflammatory_disease(p):
            enh += 1
    except Exception:
        pass

    rp = risk10.get("risk_pct")
    intermediate = (rp is not None and float(rp) >= 7.5)

    if enh >= 1:
        return "3B"
    if intermediate:
        return "3C"
    return "3A"

# Wrap evaluate() to add legacy keys without editing earlier code
try:
    _evaluate_impl = evaluate  # keep original
except NameError:
    _evaluate_impl = None

def evaluate(p: Patient) -> Dict[str, Any]:
    """
    Backward-compatible wrapper:
    - keeps engine output intact
    - adds legacy fields required by app.py v2.8
    """
    if _evaluate_impl is None:
        raise RuntimeError("Internal error: base evaluate() not found")

    out = _evaluate_impl(p)

    # Ensure levels has sublevel + legend
    lvl = out.get("levels") or {}
    ev = (lvl.get("evidence") or {}) if isinstance(lvl.get("evidence"), dict) else {}
    risk10 = out.get("pooledCohortEquations10yAscvdRisk") or out.get("ascvdPce10yRisk") or {}
    level = int(lvl.get("managementLevel") or lvl.get("postureLevel") or 1)

    if level == 3 and not lvl.get("sublevel"):
        try:
            lvl["sublevel"] = _level3_sublevel_compat(p, risk10)
        except Exception:
            lvl["sublevel"] = "3A"

    if not lvl.get("legend"):
        lvl["legend"] = levels_legend_compact()

    out["levels"] = lvl

    # Ensure insights has legacy structural_clarification + phenotype placeholders
    ins = out.get("insights") or {}
    cac_support = ins.get("cac_decision_support") if isinstance(ins, dict) else None

    # Provide legacy key used by app.py
    if "structural_clarification" not in ins:
        msg = None
        if isinstance(cac_support, dict):
            msg = cac_support.get("message")
        ins["structural_clarification"] = msg

    # App references these optionally
    ins.setdefault("phenotype_label", None)
    ins.setdefault("phenotype_definition", None)

    out["insights"] = ins
    return out



