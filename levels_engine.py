# levels_engine.py
# Risk Continuum™ Engine — v2.8 (PREVENT added; CV module; snapshot insights + clinician confidence label)
#
# Preserves v2.7:
# - RSS scoring (biologic + plaque signal, not event probability)
# - PCE 10y risk (ACC/AHA 2013; other→non-Black coefficients)
# - Inflammatory states + hsCRP + metabolic + Lp(a) unit-aware thresholds
# - Aspirin logic + bleeding flags
# - Targets + ESC goals text
# - Drivers + next actions + confidence assessment
# - Anchors (near-term vs lifetime)
# - Rule trace (auditable)
# - Optional PREVENT 10-year risks:
#     - total CVD 10y
#     - ASCVD 10y
#
# Adds v2.8:
# - Clinician-facing decision confidence label:
#     levels.decisionConfidence = "High confidence" | "Moderate confidence" | "Low confidence"
#   (Derived from completeness-based recommendationStrength.)
#
# - Snapshot insights (single-source-of-truth for UI/EMR note):
#     out["insights"] = {
#        "phenotype_label": "Atherogenic-leaning" or None,
#        "phenotype_definition": <immutable definition> or None,
#        "structural_clarification": one-line CAC advisory or None,
#        "decision_robustness": "High"|"Moderate"|"Low",
#        "decision_robustness_note": short clause
#     }
#
# Design intent:
# - Insights should be shown ONCE in a single "Clinical context" block.
# - CAC advisory is non-directive and "worth the trouble" oriented, aspirin-aware.

import math
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

PCE_DEBUG_SENTINEL = "PCE_SENTINEL_2026_01_11"

SYSTEM_NAME = "Risk Continuum™"

VERSION = {
    "system": SYSTEM_NAME,
    "levels": "v2.8-risk-continuum-prevent-insights",
    "riskSignal": "RSS v1.0",
    "riskCalc": "Pooled Cohort Equations (ACC/AHA 2013; Race other→non-Black)",
    "aspirin": "Aspirin v1.0 (CAC≥100 OR 10y risk≥10%, age 40–69, low bleed risk)",
    "prevent": "PREVENT (AHA) base model 10y: total CVD + ASCVD (requires BMI/eGFR/lipid therapy + coefficients)",
    "insights": "Snapshot insights v1.0 (phenotype + CAC clarification + robustness)",
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

def short_why(items: List[str], max_items: int = 2) -> str:
    if not items:
        return ""
    cleaned = [str(x).strip() for x in items if str(x).strip()]
    return "; ".join(cleaned[:max_items])


# ----------------------------
# Trace helper (auditable rules)
# ----------------------------
def add_trace(trace: List[Dict[str, Any]], rule: str, value: Any = None, effect: str = "") -> None:
    trace.append({"rule": rule, "value": value, "effect": effect})


# ----------------------------
# Core domain helpers
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
    if p.has("hscrp"):
        try:
            if float(p.get("hscrp")) >= 2:
                flags.append("hsCRP≥2")
        except Exception:
            pass
    if p.get("ra") is True: flags.append("RA")
    if p.get("psoriasis") is True: flags.append("Psoriasis")
    if p.get("sle") is True: flags.append("SLE")
    if p.get("ibd") is True: flags.append("IBD")
    if p.get("hiv") is True: flags.append("HIV")
    if p.get("osa") is True: flags.append("OSA")
    if p.get("nafld") is True: flags.append("NAFLD/MASLD")
    return flags


# ----------------------------
# Lp(a) normalization + threshold transparency
# ----------------------------
# NOTE: true conversion depends on isoform size. We use a common rough estimate:
# 1 mg/dL ≈ 2.5 nmol/L. This is labeled "estimated" in output.
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


# ============================================================
# PREVENT (AHA) — optional comparator (10y total CVD + 10y ASCVD)
# ============================================================

PREVENT_COEFS: Dict[str, Dict[str, Dict[str, Dict[str, float]]]] = {
    "10yr": {
        "female": {"total_cvd": {}, "ascvd": {}},
        "male": {"total_cvd": {}, "ascvd": {}},
    }
}

def _chol_mgdl_to_mmol(x: float) -> float:
    return float(x) / 38.67

def _as01(x: Any) -> float:
    return 1.0 if bool(x) else 0.0

def _round_half_up(x: float, dp: int = 2) -> float:
    m = 10 ** int(dp)
    return float(math.floor(x * m + 0.5) / m)

def prevent_prep_terms_base(
    *,
    age: float,
    total_c_mgdl: float,
    hdl_c_mgdl: float,
    sbp: float,
    dm: bool,
    smoking: bool,
    bmi: float,
    egfr: float,
    bp_tx: bool,
    statin: bool,
) -> Dict[str, float]:
    age_term = (age - 55.0) / 10.0
    age_sq = age_term ** 2

    non_hdl_mmol = _chol_mgdl_to_mmol(total_c_mgdl - hdl_c_mgdl) - 3.5
    hdl_term = (_chol_mgdl_to_mmol(hdl_c_mgdl) - 1.3) / 0.3

    sbp_lt_110 = (min(sbp, 110.0) - 110.0) / 20.0
    sbp_gte_110 = (max(sbp, 110.0) - 130.0) / 20.0

    bmi_lt_30 = (min(bmi, 30.0) - 25.0) / 5.0
    bmi_gte_30 = (max(bmi, 30.0) - 30.0) / 5.0

    egfr_lt_60 = (min(egfr, 60.0) - 60.0) / -15.0
    egfr_gte_60 = (max(egfr, 60.0) - 90.0) / -15.0

    dm01 = _as01(dm)
    smk01 = _as01(smoking)
    bp01 = _as01(bp_tx)
    st01 = _as01(statin)

    terms = {
        "constant": 1.0,
        "age": age_term,
        "age_squared": age_sq,
        "non_hdl_c": non_hdl_mmol,
        "hdl_c": hdl_term,
        "sbp_lt_110": sbp_lt_110,
        "sbp_gte_110": sbp_gte_110,
        "dm": dm01,
        "smoking": smk01,
        "bmi_lt_30": bmi_lt_30,
        "bmi_gte_30": bmi_gte_30,
        "egfr_lt_60": egfr_lt_60,
        "egfr_gte_60": egfr_gte_60,
        "bp_tx": bp01,
        "statin": st01,
        "bp_tx_sbp_gte_110": bp01 * sbp_gte_110,
        "statin_non_hdl_c": st01 * non_hdl_mmol,
        "age_non_hdl_c": age_term * non_hdl_mmol,
        "age_hdl_c": age_term * hdl_term,
        "age_sbp_gte_110": age_term * sbp_gte_110,
        "age_dm": age_term * dm01,
        "age_smoking": age_term * smk01,
        "age_bmi_gte_30": age_term * bmi_gte_30,
        "age_egfr_lt_60": age_term * egfr_lt_60,
    }
    return terms

def prevent_apply_logistic(beta: Dict[str, float], terms: Dict[str, float], dp: int = 2) -> float:
    log_odds = 0.0
    for k, b in beta.items():
        log_odds += float(b) * float(terms.get(k, 0.0))
    r = math.exp(log_odds) / (1.0 + math.exp(log_odds))
    return _round_half_up(r * 100.0, dp=dp)

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

    sex = str(p.get("sex", "")).lower()
    sex_key = "male" if sex in ("m","male") else "female"

    terms = prevent_prep_terms_base(
        age=float(age),
        total_c_mgdl=float(p.get("tc")),
        hdl_c_mgdl=float(p.get("hdl")),
        sbp=float(p.get("sbp")),
        dm=bool(p.get("diabetes")),
        smoking=bool(p.get("smoking")),
        bmi=float(p.get("bmi")),
        egfr=float(p.get("egfr")),
        bp_tx=bool(p.get("bp_treated")),
        statin=bool(p.get("lipid_lowering")),
    )
    terms.pop("age_squared", None)

    coef_bank = PREVENT_COEFS.get("10yr", {}).get(sex_key, {})
    b_total = (coef_bank.get("total_cvd") or {})
    b_ascvd = (coef_bank.get("ascvd") or {})

    if not b_total or not b_ascvd:
        add_trace(trace, "PREVENT_coefficients_missing", sex_key, "Coefficients not loaded into PREVENT_COEFS")
        return {
            "total_cvd_10y_pct": None,
            "ascvd_10y_pct": None,
            "missing": [],
            "notes": "PREVENT coefficients not loaded into PREVENT_COEFS.",
        }

    total_pct = prevent_apply_logistic(b_total, terms, dp=2)
    ascvd_pct = prevent_apply_logistic(b_ascvd, terms, dp=2)

    add_trace(trace, "PREVENT_calculated", {"sex": sex_key, "total": total_pct, "ascvd": ascvd_pct}, "PREVENT 10y calculated")
    return {
        "total_cvd_10y_pct": total_pct,
        "ascvd_10y_pct": ascvd_pct,
        "missing": [],
        "notes": "PREVENT base model (10-year): total CVD and ASCVD.",
    }


# ----------------------------
# CAC three-state evidence model
# ----------------------------
def evidence_model(p: Patient, trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    clinical = (p.get("ascvd") is True)
    if clinical:
        add_trace(trace, "Evidence_clinical_ASCVD", True, "Evidence=clinical ASCVD (plaque confirmed clinically)")
        return {
            "clinical_ascvd": True,
            "cac_status": "N/A (clinical ASCVD)",
            "cac_value": None,
            "plaque_present": True,
            "burden_band": "Clinical ASCVD",
            "certainty": "High",
        }

    if not p.has("cac"):
        add_trace(trace, "Evidence_CAC_unknown", None, "CAC not available; plaque certainty reduced")
        return {
            "clinical_ascvd": False,
            "cac_status": "Unknown",
            "cac_value": None,
            "plaque_present": None,
            "burden_band": "Unknown",
            "certainty": "Low",
        }

    cac = int(p.get("cac", 0))
    if cac == 0:
        add_trace(trace, "Evidence_CAC_zero", 0, "CAC=0 (negative for calcified plaque; soft plaque still possible)")
        return {
            "clinical_ascvd": False,
            "cac_status": "Known zero (CAC=0)",
            "cac_value": 0,
            "plaque_present": False,
            "burden_band": "None detected",
            "certainty": "Moderate",
        }

    band = (
        "Minimal plaque" if cac <= 9 else
        ("Low plaque burden" if cac <= 99 else
         ("Moderate plaque burden" if cac <= 399 else "High plaque burden"))
    )
    add_trace(trace, "Evidence_CAC_positive", cac, f"CAC positive → plaque present; burden_band={band}")
    return {
        "clinical_ascvd": False,
        "cac_status": f"Positive (CAC {cac})",
        "cac_value": cac,
        "plaque_present": True,
        "burden_band": band,
        "certainty": "High",
    }


# ----------------------------
# Confidence gating
# ----------------------------
def completeness(p: Patient) -> Dict[str, Any]:
    key = ["apob","lpa","cac","hscrp","a1c","tc","hdl","sbp","bp_treated","smoking","diabetes","sex","race","age"]
    present = [k for k in key if p.has(k)]
    missing = [k for k in key if not p.has(k)]
    pct = int(round(100 * (len(present) / len(key))))
    conf = "High" if pct >= 85 else ("Moderate" if pct >= 60 else "Low")
    return {"pct": pct, "confidence": conf, "top_missing": missing[:2], "missing": missing}

def recommendation_strength(confidence: Dict[str, Any]) -> str:
    conf = (confidence or {}).get("confidence", "Low")
    if conf == "High":
        return "Recommended"
    if conf == "Moderate":
        return "Consider"
    return "Pending more data"

def decision_confidence_label(strength: str) -> str:
    m = {
        "Recommended": "High confidence",
        "Consider": "Moderate confidence",
        "Pending more data": "Low confidence",
    }
    return m.get(str(strength or "").strip(), "—")


# ----------------------------
# RSS scoring (0–100) with trace of components
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
        add_trace(trace, "RSS_burden_ASCVD", 55, "Burden points = 55")
    elif p.has("cac"):
        cac = int(p.get("cac", 0))
        if cac == 0: burden = 0
        elif 1 <= cac <= 9: burden = 20
        elif 10 <= cac <= 99: burden = 30
        elif 100 <= cac <= 399: burden = 45
        else: burden = 55
        add_trace(trace, "RSS_burden_CAC", cac, f"Burden points = {burden}")

    athero = 0
    if p.has("apob"):
        apob = float(p.get("apob", 0))
        if apob < 80: athero = 0
        elif apob <= 99: athero = 8
        elif apob <= 119: athero = 15
        elif apob <= 149: athero = 20
        else: athero = 25
        add_trace(trace, "RSS_athero_ApoB", apob, f"Athero points = {athero}")
    elif p.has("ldl"):
        ldl = float(p.get("ldl", 0))
        if ldl < 100: athero = 0
        elif ldl <= 129: athero = 5
        elif ldl <= 159: athero = 10
        elif ldl <= 189: athero = 15
        else: athero = 20
        add_trace(trace, "RSS_athero_LDL", ldl, f"Athero points = {athero}")

    genetics = 0
    lpa_inf = lpa_info(p, trace)
    if lpa_inf.get("present"):
        used = lpa_inf["used_unit"]
        v = lpa_inf["raw_value"]
        if used == "mg/dL":
            genetics += 12 if v >= 100 else (8 if v >= 50 else 0)
        else:
            genetics += 12 if v >= 250 else (8 if v >= 125 else 0)
    if p.get("fhx") is True:
        genetics += 5
    genetics = min(genetics, 15)
    if genetics:
        add_trace(trace, "RSS_genetics", genetics, "Genetics points (Lp(a)/FHx)")

    infl = 0
    if p.has("hscrp"):
        h = float(p.get("hscrp", 0))
        if h < 2: infl += 0
        elif h < 10: infl += 5
        else: infl += 3
        add_trace(trace, "RSS_infl_hsCRP", h, f"Inflammation points from hsCRP = {infl}")
    if has_chronic_inflammatory_disease(p):
        infl += 5
        add_trace(trace, "RSS_infl_chronic", True, "Inflammation +5 (chronic inflammatory disease present)")
    infl = min(infl, 10)

    metab = 0
    if p.get("diabetes") is True:
        metab += 6
        add_trace(trace, "RSS_metab_diabetes", True, "Metabolic +6 (diabetes)")
    if p.get("smoking") is True:
        metab += 4
        add_trace(trace, "RSS_metab_smoking", True, "Metabolic +4 (smoking)")
    if a1c_status(p) == "prediabetes":
        metab += 2
        add_trace(trace, "RSS_metab_prediabetes", True, "Metabolic +2 (prediabetes A1c)")
    metab = min(metab, 10)

    total = clamp(int(round(burden + athero + genetics + infl + metab)))
    add_trace(trace, "RSS_total", total, f"Total RSS={total}")

    return {"score": total, "band": rss_band(total), "note": "Not an event probability (biologic + plaque signal)."}


# ----------------------------
# Pooled Cohort Equations (10-year ASCVD risk)
# ----------------------------
def pooled_cohort_equations_10y_ascvd_risk(p: Patient, trace: List[Dict[str, Any]]) -> Dict[str, Any]:
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
        add_trace(trace, "PCE_missing_inputs", missing, "PCE not calculated")
        return {"risk_pct": None, "missing": missing}

    age = int(p.get("age"))
    if age < 40 or age > 79:
        add_trace(trace, "PCE_age_out_of_range", age, "Valid age range 40–79")
        return {"risk_pct": None, "missing": [], "notes": "Valid for ages 40–79."}

    sex = str(p.get("sex", "")).lower()
    sex_key = "male" if sex in ("m","male") else "female"

    race = str(p.get("race", "")).lower()
    race_key = "black" if race in ("black","african american","african-american") else "white"

    c = PCE[(race_key, sex_key)]
    tc = float(p.get("tc")); hdl = float(p.get("hdl")); sbp = float(p.get("sbp"))
    treated = bool(p.get("bp_treated")); smoker = bool(p.get("smoking")); dm = bool(p.get("diabetes"))

    ln_age = math.log(age); ln_tc = math.log(tc); ln_hdl = math.log(hdl); ln_sbp = math.log(sbp)

    lp = 0.0
    lp += c.get("ln_age",0)*ln_age
    if "ln_age_sq" in c:
        lp += c["ln_age_sq"]*(ln_age**2)
    lp += c.get("ln_tc",0)*ln_tc
    if "ln_age_ln_tc" in c:
        lp += c["ln_age_ln_tc"]*(ln_age*ln_tc)
    lp += c.get("ln_hdl",0)*ln_hdl
    if "ln_age_ln_hdl" in c:
        lp += c["ln_age_ln_hdl"]*(ln_age*ln_hdl)

    if treated:
        lp += c.get("ln_sbp_treated",0)*ln_sbp
        if "ln_age_ln_sbp_treated" in c:
            lp += c["ln_age_ln_sbp_treated"]*(ln_age*ln_sbp)
    else:
        lp += c.get("ln_sbp_untreated",0)*ln_sbp
        if "ln_age_ln_sbp_untreated" in c:
            lp += c["ln_age_ln_sbp_untreated"]*(ln_age*ln_sbp)

    if smoker:
        lp += c.get("smoker",0)
        if "ln_age_smoker" in c:
            lp += c["ln_age_smoker"]*ln_age
    if dm:
        lp += c.get("diabetes",0)

    risk = 1 - (c["s0"] ** math.exp(lp - c["mean"]))
    risk = max(0.0, min(1.0, risk))
    risk_pct = round(risk*100, 1)

    if risk_pct < 5:
        cat = "Low (<5%)"
    elif risk_pct < 7.5:
        cat = "Borderline (5–7.4%)"
    elif risk_pct < 20:
        cat = "Intermediate (7.5–19.9%)"
    else:
        cat = "High (≥20%)"

    add_trace(trace, "PCE_calculated", risk_pct, f"PCE category={cat}")
    return {"risk_pct": risk_pct, "category": cat, "notes": "Population estimate (does not include CAC/ApoB/Lp(a))."}


# ----------------------------
# Aspirin module
# ----------------------------
def _bleeding_flags(p: Patient) -> Tuple[bool, List[str]]:
    flags = []
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

def aspirin_advice(p: Patient, risk10: Dict[str, Any], trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    age = int(p.get("age", 0)) if p.has("age") else None
    cac = int(p.get("cac", 0)) if p.has("cac") else None
    ascvd = (p.get("ascvd") is True)

    bleed_high, bleed_flags = _bleeding_flags(p)

    if ascvd:
        add_trace(trace, "Aspirin_ASCVD", True, "Secondary prevention aspirin consideration")
        if bleed_flags:
            return {
                "status": "Secondary prevention: typically indicated, but bleeding risk flags present",
                "rationale": bleed_flags,
                "bleeding_risk_high": bleed_high,
                "bleeding_flags": bleed_flags,
            }
        return {
            "status": "Secondary prevention: typically indicated if no contraindication",
            "rationale": ["ASCVD present"],
            "bleeding_risk_high": bleed_high,
            "bleeding_flags": bleed_flags,
        }

    if age is None:
        add_trace(trace, "Aspirin_age_missing", None, "Not assessed")
        return {
            "status": "Not assessed",
            "rationale": ["Age missing"],
            "bleeding_risk_high": bleed_high,
            "bleeding_flags": bleed_flags,
        }

    if age < 40 or age >= 70:
        add_trace(trace, "Aspirin_age_out_of_range", age, "Avoid primary prevention aspirin by age rule")
        return {
            "status": "Avoid (primary prevention)",
            "rationale": [f"Age {age} (bleeding risk likely outweighs benefit)"],
            "bleeding_risk_high": bleed_high,
            "bleeding_flags": bleed_flags,
        }

    if bleed_flags:
        add_trace(trace, "Aspirin_bleed_flags", bleed_flags, "Avoid due to bleed risk")
        return {
            "status": "Avoid (primary prevention)",
            "rationale": ["High bleeding risk: " + "; ".join(bleed_flags)],
            "bleeding_risk_high": bleed_high,
            "bleeding_flags": bleed_flags,
        }

    risk_pct = risk10.get("risk_pct")
    risk_ok = (risk_pct is not None and risk_pct >= 10.0)
    cac_ok = (cac is not None and cac >= 100)

    if cac_ok or risk_ok:
        reasons = []
        if cac_ok: reasons.append("CAC ≥100")
        if risk_ok: reasons.append(f"Pooled Cohort Equations 10-year risk ≥10% ({risk_pct}%)")
        add_trace(trace, "Aspirin_consider", reasons, "Consider aspirin shared decision")
        return {
            "status": "Consider (shared decision)",
            "rationale": reasons + ["Bleeding risk low by available flags"],
            "bleeding_risk_high": bleed_high,
            "bleeding_flags": bleed_flags,
        }

    add_trace(trace, "Aspirin_avoid_low_benefit", risk_pct, "Avoid/individualize (low benefit)")
    return {
        "status": "Avoid / individualize",
        "rationale": ["Primary prevention benefit likely small at current risk level"],
        "bleeding_risk_high": bleed_high,
        "bleeding_flags": bleed_flags,
    }


# ----------------------------
# Anchors: Near-term vs Lifetime
# ----------------------------
def build_anchors(p: Patient, risk10: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    near_factors = []
    if risk10.get("risk_pct") is not None:
        near_factors.append(f"PCE 10y {risk10['risk_pct']}% ({risk10.get('category','')})")
    else:
        near_factors.append("PCE 10y not available")

    cac_status = evidence.get("cac_status", "Unknown")
    if str(cac_status).startswith("Known zero"):
        near_factors.append("CAC=0 (low short-term signal)")
    elif str(cac_status).startswith("Positive"):
        near_factors.append(cac_status)
    else:
        near_factors.append("CAC unknown")

    near_summary = " / ".join(near_factors)

    life_factors = []
    if p.has("apob"):
        life_factors.append(f"ApoB {fmt_int(p.get('apob'))}")
    elif p.has("ldl"):
        life_factors.append(f"LDL-C {fmt_int(p.get('ldl'))}")

    if p.has("lpa"):
        unit = str(p.get("lpa_unit", "")).strip()
        life_factors.append(f"Lp(a) {fmt_1dp(p.get('lpa'))} {unit}".strip())

    if p.get("fhx") is True:
        life_factors.append("Premature FHx")

    infl = inflammation_flags(p)
    if infl:
        life_factors.append("Inflammation: " + ", ".join(infl))

    if p.get("diabetes") is True:
        life_factors.append("Diabetes")
    elif a1c_status(p) == "prediabetes":
        life_factors.append("Prediabetes")

    if p.get("smoking") is True:
        life_factors.append("Smoking")

    if not life_factors:
        life_factors.append("No major lifetime accelerators detected (with available data)")

    life_summary = " / ".join(life_factors)

    return {
        "nearTerm": {"summary": near_summary, "factors": near_factors},
        "lifetime": {"summary": life_summary, "factors": life_factors},
    }


# ----------------------------
# Internal Levels 1–5 along the Risk Continuum
# ----------------------------
def _has_any_data(p: Patient) -> bool:
    return bool(p.data)

def posture_level(p: Patient, evidence: Dict[str, Any], trace: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
    triggers: List[str] = []

    if evidence.get("clinical_ascvd"):
        triggers.append("Clinical ASCVD")
        add_trace(trace, "Level_override_ASCVD", True, "Clinical ASCVD present (secondary prevention intensity)")
        return 5, triggers

    if evidence.get("plaque_present") is True:
        cac = evidence.get("cac_value")
        if isinstance(cac, int):
            if 1 <= cac <= 99:
                triggers.append(f"CAC {cac} (plaque present)")
                add_trace(trace, "Level_CAC_1_99", cac, "Level=4 (subclinical disease present)")
                return 4, triggers
            if cac >= 100:
                triggers.append(f"CAC {cac} (high plaque burden)")
                add_trace(trace, "Level_CAC_100_plus", cac, "Level=5 (advanced subclinical)")
                return 5, triggers

    high = False
    mild = False

    if p.has("apob") and float(p.get("apob", 0)) >= 100:
        high = True; triggers.append("ApoB≥100")
    if p.has("ldl") and float(p.get("ldl", 0)) >= 130:
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
        if p.has("apob") and 80 <= float(p.get("apob", 0)) <= 99:
            mild = True; triggers.append("ApoB 80–99")
        if p.has("ldl") and 100 <= float(p.get("ldl", 0)) <= 129:
            mild = True; triggers.append("LDL 100–129")
        if a1c_status(p) == "prediabetes":
            mild = True; triggers.append("Prediabetes A1c")
        if p.has("hscrp") and not has_chronic_inflammatory_disease(p):
            try:
                if float(p.get("hscrp")) >= 2:
                    mild = True; triggers.append("hsCRP≥2 (mild)")
            except Exception:
                pass

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
        return "ESC/EAS goals (advanced subclinical): LDL-C <55–70 mg/dL; ApoB <65–80 mg/dL (tighten with enhancers)."
    if level == 4:
        return "ESC/EAS goals (subclinical disease): LDL-C <70 mg/dL; ApoB <80 mg/dL."
    if level == 3:
        return "ESC/EAS goals (high biologic risk): LDL-C <100 mg/dL; ApoB <100 mg/dL (tighten with enhancers)."
    if level == 2:
        return "ESC/EAS goals: individualized; consider LDL-C <100 mg/dL if sustained emerging risk."
    return "ESC/EAS goals: individualized by risk tier."

def atherosclerotic_disease_burden(p: Patient) -> str:
    if p.get("ascvd") is True:
        return "Present (clinical ASCVD)"
    if p.has("cac"):
        cac = int(p.get("cac", 0))
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

    if p.has("apob") and float(p.get("apob", 0)) >= 100:
        candidates.append((20, f"ApoB {fmt_int(p.get('apob'))}"))
    elif p.has("ldl") and float(p.get("ldl", 0)) >= 130:
        candidates.append((20, f"LDL-C {fmt_int(p.get('ldl'))}"))

    lpa_inf = lpa_info(p, trace)
    if lpa_inf.get("present") and lpa_inf.get("elevated"):
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
        candidates.append((70, "Prediabetes A1c"))

    candidates.sort(key=lambda x: (x[0], x[1]))
    ranked = [txt for _, txt in candidates]
    add_trace(trace, "Drivers_ranked", ranked, "Deterministic driver ranking applied")
    return ranked


# ----------------------------
# Next actions (brief)
# ----------------------------
def next_actions(p: Patient, level: int, targets: Dict[str, int], evidence: Dict[str, Any]) -> List[str]:
    acts = []

    if p.has("apob"):
        ap = fmt_int(p.get("apob"))
        try:
            if float(ap) > targets["apob"]:
                acts.append(f"Reduce ApoB toward <{targets['apob']} mg/dL.")
        except Exception:
            pass

    if p.has("ldl"):
        ld = fmt_int(p.get("ldl"))
        try:
            if float(ld) > targets["ldl"]:
                acts.append(f"Reduce LDL-C toward <{targets['ldl']} mg/dL.")
        except Exception:
            pass

    if str(evidence.get("cac_status", "")).startswith("Known zero") and level in (2, 3):
        acts.append("CAC=0 supports staged escalation; consider repeat CAC in 3–5y if risk persists.")

    return acts[:2]


# ----------------------------
# Level labels, legend, and patient explainer
# ----------------------------
def posture_labels(level: int) -> str:
    labels = {
        0: "Level 0 — Not assessed (insufficient data)",
        1: "Level 1 — Minimal risk signal (no evidence of plaque with available data)",
        2: "Level 2 — Emerging risk signals (mild–moderate biology; plaque not proven)",
        3: "Level 3 — Actionable biologic risk (plaque possible; refine with imaging when helpful)",
        4: "Level 4 — Subclinical atherosclerosis present (lower plaque burden)",
        5: "Level 5 — Very high risk / ASCVD intensity (advanced plaque or clinical ASCVD)",
    }
    return labels.get(level, f"Level {level}")

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

def level_explainer_for_patient(
    level: int,
    sublevel: Optional[str],
    evidence: Dict[str, Any],
    drivers: List[str],
) -> str:
    cac_status = evidence.get("cac_status", "Unknown")
    plaque = evidence.get("plaque_present", None)
    cac_val = evidence.get("cac_value", None)
    top = "; ".join(drivers[:2]) if drivers else ""

    mesa_note = ""
    try:
        if isinstance(cac_val, int) and cac_val > 0:
            mesa_note = (
                " CAC reclassifies risk: In MESA, any detectable coronary calcium identified established "
                "atherosclerotic plaque and higher observed event rates compared with CAC=0, independent of "
                "traditional risk scores."
            )
    except Exception:
        mesa_note = ""

    if level == 1:
        return (
            "Level 1 means we do not see a strong biologic or plaque signal with the data available; focus is "
            "maintaining healthy baseline habits and periodic reassessment."
        )
    if level == 2:
        return (
            f"Level 2 means early risk signals are emerging without proven plaque; best next step is a structured "
            f"lifestyle sprint and/or completing key missing data. Key signals: {top}."
        )
    if level == 3:
        suffix = ""
        if str(cac_status).startswith("Known zero"):
            suffix = " CAC=0 lowers short-term plaque signal, but biology may still justify action based on lifetime trajectory."
        elif plaque is None:
            suffix = " Plaque status is uncertain; CAC can improve certainty when it would change management."
        if sublevel:
            suffix = (suffix + f" (Sublevel {sublevel} refines intensity.)").strip()
        return (
            f"Level 3 means biologic risk is high enough to justify deliberate action and shared decision-making."
            f"{suffix}{mesa_note} Key signals: {top}."
        )
    if level == 4:
        return (
            f"Level 4 means subclinical plaque is present (early disease); prevention should be more decisive and "
            f"target-driven.{mesa_note} Key signals: {top}."
        )
    if level == 5:
        if evidence.get("clinical_ascvd"):
            return (
                f"Level 5 means clinical ASCVD is present; focus is secondary prevention intensity and aggressive risk "
                f"reduction. Key signals: {top}."
            )
        return (
            f"Level 5 means very high plaque burden or disease-equivalent intensity; management should be aggressive "
            f"and target-driven.{mesa_note} Key signals: {top}."
        )
    return (
        "This Level represents the system’s current best estimate of where the patient falls on the Risk Continuum "
        "based on available data."
    )


# ----------------------------
# Snapshot insights
# ----------------------------
PHENOTYPE_DEFINITION = (
    "Biologic profile associated with a predilection toward atherosclerotic plaque formation, "
    "without current structural expression."
)

def _exposure_context_ok(p: Patient) -> bool:
    if p.get("fhx") is True:
        return True
    if not p.has("age") or not p.has("sex"):
        return False
    age = int(p.get("age"))
    sex = str(p.get("sex","")).lower()
    if sex in ("m","male") and age >= 40:
        return True
    if sex in ("f","female") and age >= 45:
        return True
    return False

def _meets_predilection_biology(p: Patient, trace: List[Dict[str, Any]]) -> bool:
    major = 0
    if p.has("apob") and float(p.get("apob")) >= 100:
        major += 1
    if p.has("ldl") and float(p.get("ldl")) >= 160:
        major += 1
    if lpa_elevated(p, trace):
        major += 1
    if p.get("diabetes") is True:
        major += 1
    if p.get("smoking") is True:
        major += 1
    if major >= 1:
        return True

    minor = 0
    if p.has("apob") and 90 <= float(p.get("apob")) <= 99:
        minor += 1
    if p.has("ldl") and 130 <= float(p.get("ldl")) <= 159:
        minor += 1
    if a1c_status(p) == "prediabetes":
        minor += 1
    if p.has("hscrp"):
        try:
            if float(p.get("hscrp")) >= 2:
                minor += 1
        except Exception:
            pass
    if has_chronic_inflammatory_disease(p) or inflammation_flags(p):
        minor += 1
    if p.get("bp_treated") is True:
        minor += 1
    if p.get("fhx") is True:
        minor += 1

    return minor >= 2

def atherogenic_leaning_phenotype(p: Patient, evidence: Dict[str, Any], trace: List[Dict[str, Any]]) -> Optional[str]:
    if evidence.get("clinical_ascvd") is True:
        return None
    if evidence.get("plaque_present") is not False:
        return None
    if not _exposure_context_ok(p):
        add_trace(trace, "Phenotype_blocked_context", None, "Atherogenic-leaning not assigned (insufficient exposure context)")
        return None
    if not _meets_predilection_biology(p, trace):
        add_trace(trace, "Phenotype_blocked_biology", None, "Atherogenic-leaning not assigned (biology gate not met)")
        return None

    add_trace(trace, "Phenotype_atherogenic_leaning", True, "Assigned (CAC=0 + exposure + biology gate)")
    return "Atherogenic-leaning"

def _aspirin_cac_window(p: Patient, risk10: Dict[str, Any], level: int, aspirin: Dict[str, Any]) -> bool:
    if p.get("ascvd") is True:
        return False
    if not p.has("age"):
        return False
    age = int(p.get("age"))
    if age < 40 or age >= 70:
        return False
    if bool((aspirin or {}).get("bleeding_risk_high", False)):
        return False

    rp = risk10.get("risk_pct")
    if rp is not None and rp >= 7.5:
        return True
    if level >= 3:
        return True
    return False

def structural_clarification_advisory(
    p: Patient,
    evidence: Dict[str, Any],
    risk10: Dict[str, Any],
    aspirin: Dict[str, Any],
    level: int,
    trace: List[Dict[str, Any]],
) -> Optional[str]:
    if evidence.get("cac_status") != "Unknown":
        return None

    if _aspirin_cac_window(p, risk10, level, aspirin):
        add_trace(trace, "CAC_advisory_aspirin", True, "CAC unknown; aspirin candidacy could be informed")
        return "Structural clarification: Coronary calcium imaging could meaningfully inform aspirin candidacy and treatment confidence."

    if level >= 3:
        add_trace(trace, "CAC_advisory_intensity", True, "CAC unknown; level≥3 intensity refinement")
        return "Structural clarification: Coronary calcium imaging could meaningfully refine confidence in treatment intensity."

    return None

def decision_robustness(
    p: Patient,
    evidence: Dict[str, Any],
    conf: Dict[str, Any],
    level: int,
    risk10: Dict[str, Any],
    aspirin: Dict[str, Any],
    trace: List[Dict[str, Any]],
) -> Dict[str, str]:
    conf_band = (conf or {}).get("confidence", "Low")
    if conf_band == "Low":
        add_trace(trace, "Robustness_low_confidence", conf.get("pct"), "Decision robustness=Low")
        return {"band": "Low", "note": "Key inputs missing; conclusions limited."}

    if evidence.get("clinical_ascvd") is True:
        add_trace(trace, "Robustness_high_structural", "ASCVD", "Decision robustness=High")
        return {"band": "High", "note": "Clinical ASCVD defines intensity."}

    if evidence.get("plaque_present") is True:
        add_trace(trace, "Robustness_high_structural", evidence.get("cac_value"), "Decision robustness=High")
        return {"band": "High", "note": "Plaque present defines intensity."}

    if evidence.get("plaque_present") is False:
        add_trace(trace, "Robustness_moderate_cac0", 0, "Decision robustness=Moderate")
        return {"band": "Moderate", "note": "CAC=0 lowers plaque signal; escalation may be staged."}

    if evidence.get("cac_status") == "Unknown":
        if _aspirin_cac_window(p, risk10, level, aspirin) or level >= 3:
            add_trace(trace, "Robustness_moderate_cac_unknown", True, "Decision robustness=Moderate")
            return {"band": "Moderate", "note": "Structural status unknown; may affect confidence."}
        add_trace(trace, "Robustness_high_cac_unknown_low_level", level, "Decision robustness=High")
        return {"band": "High", "note": "Structural testing unlikely to change management."}

    add_trace(trace, "Robustness_default", None, "Decision robustness=Moderate (default)")
    return {"band": "Moderate", "note": "Moderate robustness with available data."}


# ----------------------------
# Level explanations (Level meaning + confidence gating)
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

    sublevel = None
    if level == 3:
        enhancers = 0
        lpa_inf = lpa_info(p, trace)
        if lpa_inf.get("present") and lpa_inf.get("elevated"):
            enhancers += 1
        if p.get("fhx") is True:
            enhancers += 1
        if inflammation_flags(p) or has_chronic_inflammatory_disease(p):
            enhancers += 1

        risk_pct = risk10.get("risk_pct")
        intermediate = (risk_pct is not None and risk_pct >= 7.5)

        if enhancers >= 1:
            sublevel = "3B"
        elif intermediate:
            sublevel = "3C"
        else:
            sublevel = "3A"

        add_trace(trace, "Sublevel_level3", sublevel, "Assigned Level 3 sublevel")

    clinical = bool(evidence.get("clinical_ascvd"))

    if clinical:
        meaning = "Clinical ASCVD is present; management reflects secondary prevention intensity."
        base_plan = "High-intensity therapy; aggressive ApoB/LDL targets; address all enhancers."
    elif level == 1:
        meaning = "Low biologic risk signals and no evidence of plaque with current data."
        base_plan = "Lifestyle-first; periodic reassessment; avoid over-medicalization."
    elif level == 2:
        meaning = "Mild–moderate emerging risk without proven plaque."
        base_plan = "Confirm and trend; lifestyle sprint; shared decision on medications based on trajectory."
    elif level == 3:
        meaning = "High biologic risk; plaque is possible but unproven (or CAC=0 suggests low short-term signal)."
        cac_status = str(evidence.get("cac_status", "Unknown"))
        if cac_status.startswith("Known zero"):
            base_plan = "Shared decision toward lipid lowering; CAC=0 supports staged escalation; treat enhancers aggressively."
        elif cac_status == "Unknown":
            base_plan = "Shared decision toward lipid lowering; structural clarification may refine intensity; treat enhancers aggressively."
        else:
            base_plan = "Shared decision toward lipid lowering; treat enhancers aggressively; target-driven prevention."
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
        missing = confidence.get("top_missing") or []
        if missing:
            why = why[:2] + [f"Key missing data: {', '.join(missing)}"]
        else:
            why = why[:2] + ["Key missing data limits decisiveness"]

    add_trace(trace, "Recommendation_strength", strength, "Confidence-gated decisiveness applied")

    explainer = level_explainer_for_patient(level, sublevel, evidence, drivers_all[:3])
    legend = levels_legend_compact()

    return {
        "postureLevel": level,
        "managementLevel": level,
        "label": posture_labels(level),
        "sublevel": sublevel,
        "meaning": meaning,
        "why": why,
        "defaultPosture": plan,
        "recommendationStrength": strength,      # retained (compat/debug)
        "decisionConfidence": decision_conf,     # NEW clinician-facing label
        "evidence": evidence,
        "anchorsSummary": {
            "nearTerm": anchors["nearTerm"]["summary"],
            "lifetime": anchors["lifetime"]["summary"],
        },
        "explainer": explainer,
        "legend": legend,
    }


# ----------------------------
# Public API
# ----------------------------
def evaluate(p: Patient) -> Dict[str, Any]:
    trace: List[Dict[str, Any]] = []
    add_trace(trace, "Engine_start", VERSION["levels"], "Begin evaluation")

    evidence = evidence_model(p, trace)
    risk10 = pooled_cohort_equations_10y_ascvd_risk(p, trace)
    conf = completeness(p)
    rs = risk_signal_score(p, trace)
    anchors = build_anchors(p, risk10, evidence)

    prevent10 = prevent10_total_and_ascvd(p, trace)

    level, level_triggers = posture_level(p, evidence, trace)

    targets = levels_targets(level)
    burden_str = atherosclerotic_disease_burden(p)
    asp = aspirin_advice(p, risk10, trace)

    drivers_all = ranked_drivers(p, evidence, trace)
    drivers_top = drivers_all[:3]

    rs = {**rs, "drivers": drivers_top}

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

    # ---- insights (single source of truth for UI/EMR note) ----
    phenotype = atherogenic_leaning_phenotype(p, evidence, trace)
    cac_msg = structural_clarification_advisory(p, evidence, risk10, asp, level, trace)
    robust = decision_robustness(p, evidence, conf, level, risk10, asp, trace)

    insights = {
        "phenotype_label": phenotype,
        "phenotype_definition": PHENOTYPE_DEFINITION if phenotype else None,
        "structural_clarification": cac_msg,
        "decision_robustness": robust.get("band"),
        "decision_robustness_note": robust.get("note"),
    }

    out = {
        "version": VERSION,
        "system": SYSTEM_NAME,
        "levels": levels_obj,
        "riskSignal": rs,
        "pooledCohortEquations10yAscvdRisk": risk10,
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

    lines: List[str] = []
    lines.append(f"{SYSTEM_NAME} {out['version']['levels']} — Quick Reference")

    sub = f" ({lvl.get('sublevel')})" if lvl.get("sublevel") else ""
    lines.append(
        f"Level {lvl.get('postureLevel', lvl.get('level'))}{sub}: "
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

    if ins.get("decision_robustness"):
        lines.append(f"Decision robustness: {ins.get('decision_robustness')} — {ins.get('decision_robustness_note','')}".strip())
    if ins.get("phenotype_label"):
        lines.append(f"Phenotype: {ins.get('phenotype_label')}")
    if ins.get("structural_clarification"):
        lines.append(ins.get("structural_clarification"))
    lines.append("")

    lines.append(f"Risk Signal Score: {rs['score']}/100 ({rs['band']}) — {rs['note']}")

    if risk10.get("risk_pct") is not None:
        lines.append(f"Pooled Cohort Equations (10-year ASCVD risk): {risk10['risk_pct']}% ({risk10['category']})")
    else:
        if risk10.get("missing"):
            lines.append(
                f"Pooled Cohort Equations (10-year ASCVD risk): not calculated "
                f"(missing {', '.join(risk10['missing'][:3])})"
            )
        else:
            lines.append("Pooled Cohort Equations (10-year ASCVD risk): not calculated")

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
        "Note: Risk Signal reflects biologic/plaque signal; risk calculators estimate event probability—"
        "discordance is expected and informative."
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

    legend = (lvl.get("legend") or [])[:7]
    if legend:
        lines.append("")
        lines.append("Risk Continuum Legend (Levels)")
        for item in legend:
            lines.append(f"• {item}")

    return "\n".join(lines)


