# levels_engine.py
# LEVELS v2.5 — Defensible build on v2.0 baseline
#
# Preserves v2.0:
# - RSS scoring (biologic + plaque signal, not event probability)
# - PCE 10y risk (ACC/AHA 2013; other→non-Black)
# - Inflammatory states + hsCRP + metabolic + Lp(a) unit-aware thresholds
# - Aspirin logic + bleeding flags
# - Targets + ESC goals text
# - Drivers + next actions + confidence assessment
#
# Adds defensibility features:
# (1) Posture vs Evidence split:
#     - levels.postureLevel (1–5) = default management posture (risk/subclinical focused)
#     - levels.evidence = plaque certainty/burden model (CAC/ASCVD)
# (2) Confidence gating:
#     - levels.recommendationStrength: Default / Consider / Defer—need data
#     - defaultPosture prefixed accordingly
# (4) Anchors:
#     - anchors.nearTerm (PCE + CAC)
#     - anchors.lifetime (ApoB/LDL, Lp(a), FHx, inflammation, metabolic)
# Rule trace:
#     - trace: list of rule firings with values + effects
# Lp(a) normalization:
#     - lpaInfo: raw + unit + threshold used + estimated conversion fields
# Deterministic drivers:
#     - drivers: top 3
#     - drivers_all: ranked full list (for transparency)
# Safety constraints:
#     - Confidence gating avoids "Default" when data are low
#     - Mild signals cannot escalate posture beyond Level 2 without high-risk signals or evidence

import math
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple
PCE_DEBUG_SENTINEL = "PCE_SENTINEL_2026_01_11"


VERSION = {
    "levels": "v2.5-defensible",
    "riskSignal": "RSS v1.0",
    "riskCalc": "Pooled Cohort Equations (ACC/AHA 2013; Race other→non-Black)",
    "aspirin": "Aspirin v1.0 (CAC≥100 OR 10y risk≥10%, age 40–69, low bleed risk)",
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
        add_trace(trace, "Evidence_CAC_zero", 0, "CAC=0 (known negative for calcified plaque; soft plaque still possible)")
        return {
            "clinical_ascvd": False,
            "cac_status": "Known zero (CAC=0)",
            "cac_value": 0,
            "plaque_present": False,
            "burden_band": "None detected",
            "certainty": "Moderate",
        }

    band = "Minimal plaque" if cac <= 9 else ("Low plaque burden" if cac <= 99 else ("Moderate plaque burden" if cac <= 399 else "High plaque burden"))
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
        return "Default"
    if conf == "Moderate":
        return "Consider"
    return "Defer—need data"


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
    if "ln_age_sq" in c: lp += c["ln_age_sq"]*(ln_age**2)
    lp += c.get("ln_tc",0)*ln_tc
    if "ln_age_ln_tc" in c: lp += c["ln_age_ln_tc"]*(ln_age*ln_tc)
    lp += c.get("ln_hdl",0)*ln_hdl
    if "ln_age_ln_hdl" in c: lp += c["ln_age_ln_hdl"]*(ln_age*ln_hdl)

    if treated:
        lp += c.get("ln_sbp_treated",0)*ln_sbp
        if "ln_age_ln_sbp_treated" in c: lp += c["ln_age_ln_sbp_treated"]*(ln_age*ln_sbp)
    else:
        lp += c.get("ln_sbp_untreated",0)*ln_sbp
        if "ln_age_ln_sbp_untreated" in c: lp += c["ln_age_ln_sbp_untreated"]*(ln_age*ln_sbp)

    if smoker:
        lp += c.get("smoker",0)
        if "ln_age_smoker" in c: lp += c["ln_age_smoker"]*ln_age
    if dm:
        lp += c.get("diabetes",0)

    risk = 1 - (c["s0"] ** math.exp(lp - c["mean"]))
    risk = max(0.0, min(1.0, risk))
    risk_pct = round(risk*100, 1)

    if risk_pct < 5: cat = "Low (<5%)"
    elif risk_pct < 7.5: cat = "Borderline (5–7.4%)"
    elif risk_pct < 20: cat = "Intermediate (7.5–19.9%)"
    else: cat = "High (≥20%)"

    add_trace(trace, "PCE_calculated", risk_pct, f"PCE category={cat}")
    return {"risk_pct": risk_pct, "category": cat, "notes": "Population estimate (does not include CAC/ApoB/Lp(a))."}


# ----------------------------
# Aspirin module
# ----------------------------
def aspirin_advice(p: Patient, risk10: Dict[str, Any], trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    age = int(p.get("age", 0)) if p.has("age") else None
    cac = int(p.get("cac", 0)) if p.has("cac") else None
    ascvd = (p.get("ascvd") is True)

    bleed_flags = []
    for k, label in [
        ("bleed_gi", "Prior GI bleed/ulcer"),
        ("bleed_ich", "Prior intracranial hemorrhage"),
        ("bleed_anticoag", "Anticoagulant use"),
        ("bleed_nsaid", "Chronic NSAID/steroid use"),
        ("bleed_disorder", "Bleeding disorder/thrombocytopenia"),
        ("bleed_ckd", "Advanced CKD / eGFR<45"),
    ]:
        if p.get(k) is True:
            bleed_flags.append(label)

    if ascvd:
        add_trace(trace, "Aspirin_ASCVD", True, "Secondary prevention aspirin posture")
        if bleed_flags:
            return {"status": "Secondary prevention: typically indicated, but bleeding risk flags present", "rationale": bleed_flags}
        return {"status": "Secondary prevention: typically indicated if no contraindication", "rationale": ["ASCVD present"]}

    if age is None:
        add_trace(trace, "Aspirin_age_missing", None, "Not assessed")
        return {"status": "Not assessed", "rationale": ["Age missing"]}

    if age < 40 or age >= 70:
        add_trace(trace, "Aspirin_age_out_of_range", age, "Avoid primary prevention aspirin by age rule")
        return {"status": "Avoid (primary prevention)", "rationale": [f"Age {age} (bleeding risk likely outweighs benefit)"]}

    if bleed_flags:
        add_trace(trace, "Aspirin_bleed_flags", bleed_flags, "Avoid due to bleed risk")
        return {"status": "Avoid (primary prevention)", "rationale": ["High bleeding risk: " + "; ".join(bleed_flags)]}

    risk_pct = risk10.get("risk_pct")
    risk_ok = (risk_pct is not None and risk_pct >= 10.0)
    cac_ok = (cac is not None and cac >= 100)

    if cac_ok or risk_ok:
        reasons = []
        if cac_ok: reasons.append("CAC ≥100")
        if risk_ok: reasons.append(f"Pooled Cohort Equations 10-year risk ≥10% ({risk_pct}%)")
        add_trace(trace, "Aspirin_consider", reasons, "Consider aspirin shared decision")
        return {"status": "Consider (shared decision)", "rationale": reasons + ["Bleeding risk low by available flags"]}

    add_trace(trace, "Aspirin_avoid_low_benefit", risk_pct, "Avoid/individualize (low benefit)")
    return {"status": "Avoid / individualize", "rationale": ["Primary prevention benefit likely small at current risk level"]}


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
# Posture levels 1–5 (risk + subclinical focus)
# ----------------------------
def _has_any_data(p: Patient) -> bool:
    return bool(p.data)

def posture_level(p: Patient, evidence: Dict[str, Any], trace: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
    triggers: List[str] = []

    if evidence.get("clinical_ascvd"):
        triggers.append("Clinical ASCVD")
        add_trace(trace, "Posture_override_ASCVD", True, "Clinical ASCVD present (posture uses secondary prevention banner)")
        return 5, triggers

    if evidence.get("plaque_present") is True:
        cac = evidence.get("cac_value")
        if isinstance(cac, int):
            if 1 <= cac <= 99:
                triggers.append(f"CAC {cac} (plaque present)")
                add_trace(trace, "Posture_CAC_1_99", cac, "PostureLevel=4 (early subclinical disease)")
                return 4, triggers
            if cac >= 100:
                triggers.append(f"CAC {cac} (high plaque burden)")
                add_trace(trace, "Posture_CAC_100_plus", cac, "PostureLevel=5 (advanced subclinical)")
                return 5, triggers

    high = False
    mild = False

    if p.has("apob") and float(p.get("apob", 0)) >= 100:
        high = True; triggers.append("ApoB>=100")
    if p.has("ldl") and float(p.get("ldl", 0)) >= 130:
        high = True; triggers.append("LDL>=130")

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
        add_trace(trace, "Posture_high_biology", triggers[:4], "PostureLevel=3")
        return 3, triggers
    if mild:
        # drift renamed everywhere → Emerging risk
        add_trace(trace, "Posture_emerging_risk", triggers[:4], "PostureLevel=2")
        return 2, triggers

    if _has_any_data(p):
        add_trace(trace, "Posture_low_biology", None, "PostureLevel=1")
        return 1, triggers

    return 0, triggers


# ----------------------------
# Targets + ESC goals (posture-based)
# ----------------------------
def levels_targets(level:int)->Dict[str,int]:
    if level <= 2: return {"apob":80, "ldl":100}
    if level == 3: return {"apob":80, "ldl":100}
    if level == 4: return {"apob":70, "ldl":70}
    return {"apob":60, "ldl":70}

def esc_numeric_goals(level:int, clinical_ascvd: bool)->str:
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

def atherosclerotic_disease_burden(p: Patient)->str:
    if p.get("ascvd") is True:
        return "Present (clinical ASCVD)"
    if p.has("cac"):
        cac=int(p.get("cac",0))
        return "Not detected (CAC=0)" if cac==0 else f"Present (CAC {cac})"
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
# Next actions
# ----------------------------
def next_actions(p: Patient, posture:int, targets:Dict[str,int], evidence: Dict[str, Any])->List[str]:
    acts=[]
    if p.has("apob"):
        ap=fmt_int(p.get("apob"))
        try:
            if float(ap) > targets["apob"]:
                acts.append(f"Reduce ApoB toward <{targets['apob']} mg/dL.")
        except Exception:
            pass

    if str(evidence.get("cac_status","")).startswith("Known zero") and posture in (2,3):
        acts.append("CAC=0 supports staged escalation; consider repeat CAC in 3–5y if risk persists.")
    elif evidence.get("cac_status") == "Unknown" and posture >= 3:
        acts.append("Consider CAC to clarify plaque burden and refine intensity.")

    return acts[:2]


# ----------------------------
# Level explanations (posture vs evidence + confidence gating)
# ----------------------------
def posture_labels(posture:int)->str:
    labels = {
        0: "Level 0 — No data / not assessed",
        1: "Level 1 — Low biologic risk (no plaque evidence)",
        2: "Level 2 — Emerging risk (mild–moderate biology)",
        3: "Level 3 — High biologic risk (plaque possible, unproven)",
        4: "Level 4 — Early subclinical atherosclerosis (plaque present, low burden)",
        5: "Level 5 — Advanced subclinical atherosclerosis (high plaque burden / intensity equivalent)",
    }
    return labels.get(posture, f"Level {posture}")

def explain_levels(
    p: Patient,
    posture:int,
    evidence: Dict[str, Any],
    anchors: Dict[str, Any],
    confidence: Dict[str, Any],
    drivers_all: List[str],
    trace: List[Dict[str, Any]],
    risk10: Dict[str, Any],
) -> Dict[str, Any]:
    strength = recommendation_strength(confidence)

    sublevel = None
    if posture == 3:
        enhancers = 0
        lpa_inf = lpa_info(p, trace)
        if lpa_inf.get("present") and lpa_inf.get("elevated"): enhancers += 1
        if p.get("fhx") is True: enhancers += 1
        if inflammation_flags(p) or has_chronic_inflammatory_disease(p): enhancers += 1

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
        meaning = "Clinical ASCVD is present; posture reflects secondary prevention intensity."
        base_posture = "High-intensity therapy by default; aggressive ApoB/LDL targets; address all enhancers."
    elif posture == 1:
        meaning = "Low biologic risk signals and no evidence of plaque with current data."
        base_posture = "Lifestyle-first; periodic reassessment; avoid over-medicalization."
    elif posture == 2:
        meaning = "Mild–moderate emerging risk without proven plaque."
        base_posture = "Confirm and trend; lifestyle sprint; shared decision on medications based on trajectory."
    elif posture == 3:
        meaning = "High biologic risk; plaque is possible but unproven (or CAC=0 suggests low short-term signal)."
        base_posture = "Shared decision toward lipid lowering; refine with CAC if unknown; treat enhancers aggressively."
    elif posture == 4:
        meaning = "Subclinical plaque is present (early disease)."
        base_posture = "Treat like early disease: statin default; target-driven therapy; reassess response."
    else:
        meaning = "High plaque burden or intensity-equivalent state."
        base_posture = "Aggressive lipid targets; consider add-ons; treat as disease-equivalent intensity."

    prefix = {"Default": "Default posture: ", "Consider": "Consider: ", "Defer—need data": "Defer—need data: "}.get(strength, "")
    default_posture = prefix + base_posture

    why = drivers_all[:3]
    if strength == "Defer—need data":
        missing = confidence.get("top_missing") or []
        if missing:
            why = why[:2] + [f"Key missing data: {', '.join(missing)}"]
        else:
            why = why[:2] + ["Key missing data limits decisiveness"]

    add_trace(trace, "Recommendation_strength", strength, "Confidence-gated decisiveness applied")

    return {
        "postureLevel": posture,
        "label": posture_labels(posture),
        "sublevel": sublevel,
        "meaning": meaning,
        "why": why,
        "defaultPosture": default_posture,
        "recommendationStrength": strength,
        "evidence": evidence,
        "anchorsSummary": {
            "nearTerm": anchors["nearTerm"]["summary"],
            "lifetime": anchors["lifetime"]["summary"],
        },
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

    posture, posture_triggers = posture_level(p, evidence, trace)

    targets = levels_targets(posture)
    burden_str = atherosclerotic_disease_burden(p)
    asp = aspirin_advice(p, risk10, trace)

    drivers_all = ranked_drivers(p, evidence, trace)
    drivers_top = drivers_all[:3]

    rs = {**rs, "drivers": drivers_top}

    levels_obj = explain_levels(
        p=p,
        posture=posture,
        evidence=evidence,
        anchors=anchors,
        confidence=conf,
        drivers_all=drivers_all,
        trace=trace,
        risk10=risk10,
    )
    levels_obj["triggers"] = sorted(set(posture_triggers))

    next_acts = next_actions(p, posture, targets, evidence)

    out = {
        "version": VERSION,
        "levels": levels_obj,
        "riskSignal": rs,
        "pooledCohortEquations10yAscvdRisk": risk10,
        "targets": targets,
        "confidence": conf,
        "diseaseBurden": burden_str,
        "drivers": drivers_top,
        "drivers_all": drivers_all,
        "nextActions": next_acts,
        "escGoals": esc_numeric_goals(posture, clinical_ascvd=bool(evidence.get("clinical_ascvd"))),
        "aspirin": asp,
        "anchors": anchors,
        "lpaInfo": lpa_info(p, trace),
        "trace": trace,
    }

    add_trace(trace, "Engine_end", VERSION["levels"], "Evaluation complete")
    return out


def render_quick_text(p: Patient, out: Dict[str,Any]) -> str:
    lvl = out["levels"]
    rs = out["riskSignal"]
    risk10 = out["pooledCohortEquations10yAscvdRisk"]
    t = out["targets"]
    conf = out["confidence"]

    lines=[]
    lines.append(f"LEVELS™ {out['version']['levels']} — Quick Reference")
    sub = f" ({lvl.get('sublevel')})" if lvl.get("sublevel") else ""
    lines.append(f"Posture Level {lvl.get('postureLevel', lvl.get('level'))}{sub}: {lvl['label'].split('—',1)[1].strip()}")

    ev = lvl.get("evidence", {})
    lines.append(f"Evidence: {ev.get('cac_status','Unknown')} / burden: {ev.get('burden_band','Unknown')}")
    lines.append(f"Atherosclerotic disease burden: {out['diseaseBurden']}")

    miss=", ".join(conf["top_missing"]) if conf["top_missing"] else "none"
    lines.append(f"Confidence: {conf['confidence']} ({conf['pct']}% complete; missing: {miss})")
    lines.append(f"Recommendation strength: {lvl.get('recommendationStrength','—')}")
    lines.append("")
    lines.append(f"Risk Signal Score: {rs['score']}/100 ({rs['band']}) — {rs['note']}")

    if risk10.get("risk_pct") is not None:
        lines.append(f"Pooled Cohort Equations (10-year ASCVD risk): {risk10['risk_pct']}% ({risk10['category']})")
    else:
        if risk10.get("missing"):
            lines.append(f"Pooled Cohort Equations (10-year ASCVD risk): not calculated (missing {', '.join(risk10['missing'][:3])})")
        else:
            lines.append("Pooled Cohort Equations (10-year ASCVD risk): not calculated")

    if out.get("drivers"):
        lines.append("Drivers: " + "; ".join(out["drivers"]))

    lines.append("Targets")
    if p.has("apob"):
        lines.append(f"• ApoB: {fmt_int(p.get('apob'))} mg/dL → target <{t['apob']} mg/dL")
    if p.has("ldl"):
        lines.append(f"• LDL-C: {fmt_int(p.get('ldl'))} mg/dL → target <{t['ldl']} mg/dL")

    above = False
    try:
        if p.has("apob") and float(p.get("apob")) > t["apob"]: above = True
        if p.has("ldl") and float(p.get("ldl")) > t["ldl"]: above = True
    except Exception:
        pass
    if above:
        lines.append("Benefit context: ~40 mg/dL ApoB/LDL reduction ≈ ~20–25% relative ASCVD event reduction over time (population data).")

    lines.append(out["escGoals"])

    if out.get("nextActions"):
        lines.append("Next: " + " / ".join(out["nextActions"]))

    lines.append(f"Aspirin 81 mg: {out['aspirin']['status']}")
    return "\n".join(lines)


