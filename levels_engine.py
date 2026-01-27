# =========================
# CHUNK 1 / 6 — START
# =========================
# levels_engine.py
# Risk Continuum™ Engine — v3.1 (buffer-based thresholds; locked language; Epic-aligned PCE; CAC gating; modality-aware plan)
#
# Goals:
# - Outputs "ease and confidence" in CV risk management decisions
# - Senior clinical tone (no second person; no marketing language)
# - CAC is optional/deferred/suppressed (never "recommended")
# - Plaque concepts are explicit: Plaque Evidence vs Plaque Burden
# - Decision Confidence vs Decision Stability are distinct, consistent, and calm
# - Buffered binaries: hard gates + reasonableness buffer around cutoffs
#
# Preserves:
# - RSS scoring (biologic + plaque signal)
# - PREVENT (population comparator)
# - Aspirin module + bleed flags
# - Anchors (near-term vs lifetime)
# - Trace (auditable)
# - EMR-friendly render_quick_text()
# - Backward-compatible keys expected by current app.py

import math
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

SYSTEM_NAME = "Risk Continuum™"
PCE_DEBUG_SENTINEL = "PCE_EPIC_2019_ALIGNED_v3_1"

VERSION = {
    "system": SYSTEM_NAME,
    "levels": "v3.1-risk-continuum-buffered",
    "riskSignal": "RSS v1.0",
    "riskCalc": "ASCVD PCE (ACC/AHA 2019 interpretation; Epic-aligned implementation)",
    "aspirin": "Aspirin v1.0 (CAC≥100 OR ASCVD PCE≥10%, age 40–69, low bleed risk)",
    "prevent": "PREVENT (AHA) population model 10y: total CVD + ASCVD",
    "insights": "Locked clinical language v1.0 (buffered binaries)",
}

# -------------------------------------------------------------------
# Buffer-based gates (tight, conservative)
# -------------------------------------------------------------------
PCE_HARD_NO_MAX = 4.0         # <4% → suppress CAC
PCE_BUFFER_MIN = 4.0          # 4–6% → buffer/pause zone
PCE_BUFFER_MAX = 6.0
PCE_ACTION_MIN = 6.0          # ≥6% → actionable zone (preference-sensitive depending on context)
PCE_ACTION_MAX = 20.0         # ≥20% → high risk; CAC usually low incremental value

A1C_BUFFER_MIN = 6.2          # 6.2–6.4% → near diabetes boundary (avoid over-labeling)
A1C_BUFFER_MAX = 6.4

# Optional (used for language + drivers; not required for gating)
LDL_BUFFER_MIN = 170.0
LDL_BUFFER_MAX = 189.0
APOB_BUFFER_MIN = 110.0
APOB_BUFFER_MAX = 129.0

# -------------------------------------------------------------------
# Patient wrapper
# -------------------------------------------------------------------
@dataclass
class Patient:
    data: Dict[str, Any]

    def get(self, k, d=None):
        return self.data.get(k, d)

    def has(self, k) -> bool:
        return (k in self.data) and (self.data[k] is not None)

# -------------------------------------------------------------------
# Trace helper
# -------------------------------------------------------------------
def add_trace(trace: List[Dict[str, Any]], rule: str, value: Any = None, effect: str = "") -> None:
    trace.append({"rule": rule, "value": value, "effect": effect})

# -------------------------------------------------------------------
# Formatting helpers
# -------------------------------------------------------------------
def safe_float(val, default=0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return float(default)

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
    """Used by app.py for compact rationale displays."""
    if not items:
        return ""
    cleaned = [str(x).strip() for x in items if str(x).strip()]
    return "; ".join(cleaned[:max_items])

def levels_legend_compact() -> List[str]:
    return [
        "Level 1: minimal signal → reinforce basics; periodic reassess",
        "Level 2: emerging signals → complete data; lifestyle sprint; reassess",
        "Level 3A: actionable biology → lifestyle-first; pharmacologic reasonable if targets unmet",
        "Level 3B: actionable biology + enhancers → pharmacologic therapy often favored; CAC optional only if it would change timing/intensity",
        "Level 4: plaque present → treat like early disease; target-driven therapy",
        "Level 5: very high risk / ASCVD → secondary prevention intensity; maximize tolerated therapy",
        "Buffered binaries: hard gates at edges; narrow buffer near cutoffs to absorb noise and avoid cascades",
    ]
# =========================
# CHUNK 1 / 6 — END
# =========================

# =========================
# CHUNK 2 / 6 — START
# =========================
# -------------------------------------------------------------------
# A1c + inflammation helpers
# -------------------------------------------------------------------
def a1c_status(p: Patient) -> Optional[str]:
    """
    Returns:
      - normal
      - prediabetes
      - near_diabetes_boundary (6.2–6.4)
      - diabetes_range (≥6.5)
    """
    if not p.has("a1c"):
        return None
    a1c = safe_float(p.get("a1c"), default=float("nan"))
    if math.isnan(a1c):
        return None
    if a1c < 5.7:
        return "normal"
    if A1C_BUFFER_MIN <= a1c <= A1C_BUFFER_MAX:
        return "near_diabetes_boundary"
    if a1c < 6.5:
        return "prediabetes"
    return "diabetes_range"

def has_chronic_inflammatory_disease(p: Patient) -> bool:
    return any(p.get(k) is True for k in ["ra", "psoriasis", "sle", "ibd", "hiv", "osa", "nafld"])

def inflammation_flags(p: Patient) -> List[str]:
    flags: List[str] = []
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

# -------------------------------------------------------------------
# Lp(a) normalization
# -------------------------------------------------------------------
_LPA_MGDL_TO_NMOLL = 2.5

def lpa_info(p: Patient, trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not p.has("lpa"):
        return {"present": False}
    try:
        raw = float(p.get("lpa"))
    except Exception:
        return {"present": False}

    unit_raw = str(p.get("lpa_unit", "")).strip()
    unit = unit_raw.lower()

    if "mg" in unit:
        threshold = 50.0
        elevated = raw >= threshold
        used_unit = "mg/dL"
        est_nmol = raw * _LPA_MGDL_TO_NMOLL
        est_mg = raw
    else:
        threshold = 125.0
        elevated = raw >= threshold
        used_unit = "nmol/L"
        est_nmol = raw
        est_mg = raw / _LPA_MGDL_TO_NMOLL

    add_trace(
        trace,
        "Lp(a)_threshold",
        value=f"{raw} {unit_raw}".strip(),
        effect=f"Threshold {threshold} {used_unit}; elevated={elevated}",
    )

    return {
        "present": True,
        "raw_value": raw,
        "raw_unit": unit_raw or used_unit,
        "used_threshold": threshold,
        "used_unit": used_unit,
        "elevated": elevated,
        "estimated_nmolL": round(est_nmol, 1),
        "estimated_mgdl": round(est_mg, 1),
        "conversion_note": "Estimated conversion only; isoform-size dependent.",
    }

def lpa_elevated(p: Patient, trace: List[Dict[str, Any]]) -> bool:
    info = lpa_info(p, trace)
    return bool(info.get("present") and info.get("elevated"))

def lpa_elevated_no_trace(p: Patient) -> bool:
    if not p.has("lpa"):
        return False
    try:
        raw = float(p.get("lpa"))
    except Exception:
        return False
    unit = str(p.get("lpa_unit", "")).strip().lower()
    if "mg" in unit:
        return raw >= 50.0
    return raw >= 125.0

# -------------------------------------------------------------------
# Plaque Evidence / Plaque Burden (structural only)
# -------------------------------------------------------------------
def plaque_state(p: Patient, trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Plaque Evidence: whether structural plaque is established.
    Plaque Burden: extent of plaque if assessed.
    """
    if p.get("ascvd") is True:
        add_trace(trace, "PlaqueEvidence_ASCVD", True, "Clinical ASCVD")
        return {
            "plaque_evidence": "Clinical ASCVD",
            "plaque_burden": "Established disease",
            "cac_value": None,
            "plaque_present": True,
            "certainty": "High",
        }

    if not p.has("cac"):
        add_trace(trace, "PlaqueEvidence_unmeasured", None, "No structural imaging")
        return {
            "plaque_evidence": "Unknown — no structural imaging",
            "plaque_burden": "Not quantified",
            "cac_value": None,
            "plaque_present": None,
            "certainty": "Low",
        }

    try:
        cac = int(p.get("cac"))
    except Exception:
        add_trace(trace, "CAC_invalid", p.get("cac"), "CAC invalid → treated as unmeasured")
        return {
            "plaque_evidence": "Unknown — no structural imaging",
            "plaque_burden": "Not quantified",
            "cac_value": None,
            "plaque_present": None,
            "certainty": "Low",
        }

    if cac == 0:
        add_trace(trace, "CAC_zero", 0, "CAC=0")
        return {
            "plaque_evidence": "CAC = 0",
            "plaque_burden": "None detected",
            "cac_value": 0,
            "plaque_present": False,
            "certainty": "Moderate",
        }

    # Interpretive buffer: CAC 1–9 should not flip posture alone (avoid cascade)
    if cac <= 9:
        band = "Minimal (1–9)"
        certainty = "High"
    elif cac <= 99:
        band = "Low (10–99)"
        certainty = "High"
    elif cac <= 399:
        band = "Moderate (100–399)"
        certainty = "High"
    else:
        band = "High (≥400)"
        certainty = "High"

    add_trace(trace, "CAC_positive", cac, f"CAC positive; burden={band}")
    return {
        "plaque_evidence": "CAC positive",
        "plaque_burden": f"{band} (Agatston {cac})",
        "cac_value": cac,
        "plaque_present": True,
        "certainty": certainty,
    }
# =========================
# CHUNK 2 / 6 — END
# =========================
# =========================
# CHUNK 3 / 6 — START
# =========================
# -------------------------------------------------------------------
# ASCVD PCE (Epic-aligned 2019 interpretation)
# -------------------------------------------------------------------
def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def _pce_category(risk_pct: float) -> str:
    if risk_pct < PCE_HARD_NO_MAX:
        return f"Low (<{PCE_HARD_NO_MAX:.0f}%)"
    if PCE_BUFFER_MIN <= risk_pct <= PCE_BUFFER_MAX:
        return f"Near boundary ({PCE_BUFFER_MIN:.0f}–{PCE_BUFFER_MAX:.0f}%)"
    if risk_pct < 7.5:
        return "Borderline (5–7.4%)"
    if risk_pct < PCE_ACTION_MAX:
        return "Intermediate (7.5–19.9%)"
    return f"High (≥{PCE_ACTION_MAX:.0f}%)"

def pce_zone(risk_pct: Optional[float]) -> str:
    """
    Buffered-binary zones:
      - hard_no: <4%
      - buffer: 4–6%
      - actionable: ≥6% and <20%
      - high: ≥20%
      - unknown: None
    """
    if risk_pct is None:
        return "unknown"
    rp = float(risk_pct)
    if rp < PCE_HARD_NO_MAX:
        return "hard_no"
    if PCE_BUFFER_MIN <= rp <= PCE_BUFFER_MAX:
        return "buffer"
    if rp >= PCE_ACTION_MAX:
        return "high"
    if rp >= PCE_ACTION_MIN:
        return "actionable"
    return "buffer"

def ascvd_pce_10y_risk(p: Patient, trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Epic-aligned implementation:
    - Standard PCE coefficients
    - Race: 'black' uses Black coefficients; all other races use non-Black coefficients
    - Clips typical input ranges before ln() to reduce cross-tool mismatch
    """
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
        return {"risk_pct": None, "missing": missing, "notes": "Missing required inputs."}

    try:
        age = int(p.get("age"))
    except Exception:
        add_trace(trace, "PCE_age_invalid", p.get("age"), "Invalid age")
        return {"risk_pct": None, "missing": [], "notes": "Invalid age."}

    if age < 40 or age > 79:
        add_trace(trace, "PCE_age_out_of_range", age, "Validated 40–79")
        return {"risk_pct": None, "missing": [], "notes": "Validated for ages 40–79."}

    sex_raw = str(p.get("sex", "")).strip().lower()
    sex = "male" if sex_raw in ("m","male") else "female"

    race_raw = str(p.get("race", "")).strip().lower()
    race = "black" if race_raw in ("black","african american","african-american") else "white"

    c = PCE.get((race, sex))
    if not c:
        add_trace(trace, "PCE_coeff_missing", (race, sex), "No coefficients")
        return {"risk_pct": None, "missing": [], "notes": "Coefficient set not available."}

    tc = _clip(safe_float(p.get("tc")), 130.0, 320.0)
    hdl = _clip(safe_float(p.get("hdl")), 20.0, 100.0)
    sbp = _clip(safe_float(p.get("sbp")), 90.0, 200.0)
    treated = bool(p.get("bp_treated"))
    smoker = bool(p.get("smoking"))
    dm = bool(p.get("diabetes"))

    ln_age = math.log(_clip(float(age), 40.0, 79.0))
    ln_tc = math.log(tc)
    ln_hdl = math.log(hdl)
    ln_sbp = math.log(sbp)

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

    risk = 1 - (c["s0"] ** math.exp(lp - c["mean"]))
    risk = max(0.0, min(1.0, float(risk)))
    risk_pct = round(risk * 100.0, 1)
    cat = _pce_category(risk_pct)

    add_trace(trace, "PCE_calculated", {"risk_pct": risk_pct, "category": cat, "zone": pce_zone(risk_pct)}, "ASCVD PCE calculated")
    return {
        "risk_pct": risk_pct,
        "category": cat,
        "missing": [],
        "notes": "ASCVD PCE (Epic-aligned).",
    }
# =========================
# CHUNK 3 / 6 — END
# =========================
# =========================
# CHUNK 4 / 6 — START
# =========================
# -------------------------------------------------------------------
# PREVENT (AHA) — population comparator (RESTORED: v2.8 full equations + safe evaluator)
# -------------------------------------------------------------------
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
        "PREVENT 10y calculated",
    )

    return {
        "total_cvd_10y_pct": total_pct,
        "ascvd_10y_pct": ascvd_pct,
        "missing": [],
        "notes": "PREVENT (population model).",
    }

# -------------------------------------------------------------------
# Data completeness (diagnostic only)
# -------------------------------------------------------------------
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

# -------------------------------------------------------------------
# Risk Signal Score (RSS)
# -------------------------------------------------------------------
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
    elif p.has("cac"):
        cac = safe_float(p.get("cac"), 0)
        if cac == 0: burden = 0
        elif cac <= 9: burden = 20
        elif cac <= 99: burden = 30
        elif cac <= 399: burden = 45
        else: burden = 55

    athero = 0
    if p.has("apob"):
        ap = safe_float(p.get("apob"))
        if ap < 80: athero = 0
        elif ap <= 99: athero = 8
        elif ap <= 119: athero = 15
        elif ap <= 149: athero = 20
        else: athero = 25
    elif p.has("ldl"):
        ld = safe_float(p.get("ldl"))
        if ld < 100: athero = 0
        elif ld <= 129: athero = 5
        elif ld <= 159: athero = 10
        elif ld <= 189: athero = 15
        else: athero = 20

    genetics = 0
    if lpa_elevated(p, trace): genetics += 10
    if p.get("fhx") is True: genetics += 5
    genetics = min(genetics, 15)

    infl = 0
    if p.has("hscrp") and safe_float(p.get("hscrp")) >= 2: infl += 5
    if has_chronic_inflammatory_disease(p): infl += 5
    infl = min(infl, 10)

    metab = 0
    if p.get("diabetes") is True: metab += 6
    if p.get("smoking") is True: metab += 4

    a1s = a1c_status(p)
    # Buffer: near diabetes boundary signals attention without labeling disease
    if a1s == "near_diabetes_boundary":
        metab += 1
    elif a1s == "prediabetes":
        metab += 2
    metab = min(metab, 10)

    total = clamp(int(round(burden + athero + genetics + infl + metab)))
    add_trace(trace, "RSS_total", total, "RSS computed")

    return {
        "score": total,
        "band": rss_band(total),
        "note": "Biologic + plaque signal (not event probability).",
    }
# =========================
# CHUNK 4 / 6 — END
# =========================
# =========================
# CHUNK 5 / 6 — START
# =========================
# -------------------------------------------------------------------
# Targets + ESC/EAS framing
# -------------------------------------------------------------------
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
        return "ESC/EAS goals: individualized; consider LDL-C <100 mg/dL if risk persists."
    return "ESC/EAS goals: individualized."

# -------------------------------------------------------------------
# NEW: Legacy NCEP/ATP III overlay (display-only; gated)
# -------------------------------------------------------------------
def _atp_risk_factor_count(p: Patient) -> int:
    """
    Simplified ATP III major risk factors (contextual framing only):
      - Age (men ≥45, women ≥55)
      - Smoking (current)
      - Hypertension (treated OR SBP ≥140)
      - Low HDL-C (<40)
      - Family history premature ASCVD (if present)
    """
    rf = 0

    age = int(p.get("age", 0)) if p.has("age") else None
    sex_raw = str(p.get("sex", "")).strip().lower()
    male = sex_raw in ("m", "male")

    if age is not None:
        if male and age >= 45:
            rf += 1
        if (not male) and age >= 55:
            rf += 1

    if p.get("smoking") is True:
        rf += 1

    sbp = safe_float(p.get("sbp"), 0) if p.has("sbp") else 0
    if p.get("bp_treated") is True or sbp >= 140:
        rf += 1

    hdl = safe_float(p.get("hdl"), 999) if p.has("hdl") else 999
    if hdl < 40:
        rf += 1

    if p.get("fhx") is True:
        rf += 1

    return rf


def _atp_rf_count_with_completeness(p: Patient) -> Tuple[Optional[int], List[str]]:
    """
    Returns (risk_factor_count_or_None, missing_inputs_for_count)

    If key inputs for ATP RF counting are missing, returns None to avoid pseudo-precision.
    """
    missing: List[str] = []
    for k in ("age", "sex", "sbp", "bp_treated", "smoking", "hdl"):
        if not p.has(k):
            missing.append(k)

    # If fhx is not present (or is None), avoid treating it as absent
    if not p.has("fhx"):
        missing.append("fhx")

    if missing:
        return None, missing

    return _atp_risk_factor_count(p), []


def atp_overlay_support(
    p: Patient,
    plaque: Dict[str, Any],
    risk10: Dict[str, Any],
    level: int,
    trace: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Legacy NCEP/ATP III LDL context overlay.
    - Display-only; does not change plan/level.
    - Locked tone: interpretive reference only.
    - Suppressed when plaque/particle burden is established or when near-term risk is not low.

    Returns:
      {"status": "suppressed"|"shown", "title": str|None, "lines": List[str]}
    """

    # ---- Hard suppressions (avoid misleading reassurance) ----
    if p.get("ascvd") is True:
        if trace is not None:
            add_trace(trace, "ATP_overlay_suppressed_ASCVD", True, "Clinical ASCVD")
        return {"status": "suppressed", "title": None, "lines": []}

    # Hide when CAC burden is established (CAC ≥100)
    try:
        cac_val = plaque.get("cac_value", None)
        if cac_val is None and p.has("cac"):
            cac_val = int(p.get("cac"))
        if isinstance(cac_val, int) and cac_val >= 100:
            if trace is not None:
                add_trace(trace, "ATP_overlay_suppressed_CAC100", cac_val, "Plaque burden established")
            return {"status": "suppressed", "title": None, "lines": []}
    except Exception:
        pass

    # Hide when ApoB burden is established (ApoB ≥130)
    if p.has("apob") and safe_float(p.get("apob")) >= 130:
        if trace is not None:
            add_trace(trace, "ATP_overlay_suppressed_ApoB130", p.get("apob"), "Atherogenic burden established")
        return {"status": "suppressed", "title": None, "lines": []}

    # Suppress when plaque has already been assessed (CAC=0 or CAC positive)
    if plaque.get("plaque_present") in (True, False) or plaque.get("plaque_evidence") == "Clinical ASCVD":
        if trace is not None:
            add_trace(trace, "ATP_overlay_suppressed_plaque_assessed", plaque.get("plaque_evidence"), "Plaque assessed")
        return {"status": "suppressed", "title": None, "lines": []}

    # Suppress for Level ≥4 (already target-driven by plaque posture)
    if int(level or 0) >= 4:
        if trace is not None:
            add_trace(trace, "ATP_overlay_suppressed_level4plus", level, "Higher posture")
        return {"status": "suppressed", "title": None, "lines": []}

    rp = risk10.get("risk_pct")
    rp_f = float(rp) if rp is not None else None

    # ---- Near-term risk gating ----
    # Default: show only when PCE <7.5% (low/borderline/buffer zone).
    # If risk is unknown, allow display (it will likely be indeterminate).
    if rp_f is not None and rp_f >= 7.5:
        if trace is not None:
            add_trace(trace, "ATP_overlay_suppressed_PCE75plus", rp_f, "Near-term risk not low")
        return {"status": "suppressed", "title": None, "lines": []}

    # ---- Category assignment (with indeterminate fallback) ----
    if p.get("diabetes") is True:
        category = "CHD risk equivalent"
        ldl_goal = "<100 mg/dL"
        drug_thresh = "Treat ≥130 mg/dL"
    elif rp_f is not None and rp_f >= 20.0:
        category = "High risk (10-year risk ≥20%)"
        ldl_goal = "<100 mg/dL"
        drug_thresh = "Treat ≥130 mg/dL"
    elif rp_f is not None and rp_f >= 10.0:
        category = "Intermediate risk (10-year risk 10–20%)"
        ldl_goal = "<130 mg/dL"
        drug_thresh = "Treat ≥130 mg/dL"
    else:
        rf_count, rf_missing = _atp_rf_count_with_completeness(p)
        if rf_count is None:
            category = "Indeterminate (data incomplete for ATP risk-factor counting)"
            ldl_goal = "Typically <130 mg/dL in most non–high-risk primary prevention profiles"
            drug_thresh = "Often considered ≥160 mg/dL depending on risk-factor profile"
        else:
            if rf_count >= 2:
                category = "2+ risk factors with 10-year risk <10%"
                ldl_goal = "<130 mg/dL"
                drug_thresh = "Consider ≥160 mg/dL"
            else:
                category = "0–1 risk factor"
                ldl_goal = "<160 mg/dL"
                drug_thresh = "Treat ≥190 mg/dL (consider 160–189 mg/dL)"

    # ---- LDL/ApoB line ----
    ldl_line = None
    if p.has("ldl"):
        ldl_line = f"Current LDL-C: {fmt_int(p.get('ldl'))} mg/dL"
    elif p.has("apob"):
        ldl_line = f"Current LDL-C: — (ApoB {fmt_int(p.get('apob'))} mg/dL available)"

    title = "LEGACY NCEP / ATP III (LDL CONTEXT)"
    lines = [
        "Interpretive reference only; modern guidance is risk/intensity-based.",
        f"- ATP risk category: {category}",
        f"- LDL goal (legacy): {ldl_goal}",
        f"- Drug threshold (legacy): {drug_thresh}",
    ]
    if ldl_line:
        lines.append(f"- {ldl_line}")

    if trace is not None:
        add_trace(
            trace,
            "ATP_overlay_shown",
            {"category": category, "goal": ldl_goal, "threshold": drug_thresh, "pce": rp_f},
            "Legacy context displayed",
        )

    return {"status": "shown", "title": title, "lines": lines}


# -------------------------------------------------------------------
# Deterministic driver ranking
# -------------------------------------------------------------------
def ranked_drivers(p: Patient, plaque: Dict[str, Any], trace: List[Dict[str, Any]]) -> List[str]:
    drivers: List[Tuple[int, str]] = []

    if p.get("ascvd") is True:
        drivers.append((10, "Clinical ASCVD"))
    elif plaque.get("plaque_present") is True and plaque.get("cac_value") is not None:
        drivers.append((10, f"CAC {int(plaque['cac_value'])}"))

    if p.has("apob"):
        ap = safe_float(p.get("apob"))
        if ap >= 130:
            drivers.append((20, f"ApoB {fmt_int(p.get('apob'))}"))
        elif APOB_BUFFER_MIN <= ap <= APOB_BUFFER_MAX:
            drivers.append((25, f"ApoB {fmt_int(p.get('apob'))} (near boundary)"))
        elif ap >= 100:
            drivers.append((30, f"ApoB {fmt_int(p.get('apob'))}"))
    elif p.has("ldl"):
        ld = safe_float(p.get("ldl"))
        if ld >= 190:
            drivers.append((20, f"LDL-C {fmt_int(p.get('ldl'))}"))
        elif LDL_BUFFER_MIN <= ld <= LDL_BUFFER_MAX:
            drivers.append((25, f"LDL-C {fmt_int(p.get('ldl'))} (near boundary)"))
        elif ld >= 130:
            drivers.append((30, f"LDL-C {fmt_int(p.get('ldl'))}"))

    if lpa_elevated(p, trace):
        drivers.append((40, "Lp(a) elevated"))

    a1s = a1c_status(p)
    if a1s == "diabetes_range" or p.get("diabetes") is True:
        drivers.append((41, "Diabetes"))
    elif a1s == "near_diabetes_boundary":
        drivers.append((55, "A1c near diabetes threshold"))
    elif a1s == "prediabetes":
        drivers.append((60, "Prediabetes"))

    if p.get("smoking") is True:
        drivers.append((42, "Smoking"))

    if inflammation_flags(p) or has_chronic_inflammatory_disease(p):
        drivers.append((50, "Inflammatory signal"))

    if p.get("fhx") is True:
        drivers.append((52, "Premature family history"))

    drivers.sort(key=lambda x: (x[0], x[1]))
    ranked = [d for _, d in drivers]
    add_trace(trace, "Drivers_ranked", ranked, "Drivers ranked")
    return ranked

# -------------------------------------------------------------------
# Anchors (near-term vs lifetime)
# -------------------------------------------------------------------
def build_anchors(p: Patient, risk10: Dict[str, Any], plaque: Dict[str, Any]) -> Dict[str, Any]:
    near: List[str] = []
    if risk10.get("risk_pct") is not None:
        rp = float(risk10["risk_pct"])
        z = pce_zone(rp)
        if z == "buffer":
            near.append(f"ASCVD PCE {rp}% (near boundary)")
        else:
            near.append(f"ASCVD PCE {rp}% ({risk10.get('category','—')})")
    else:
        near.append("ASCVD PCE not available")

    pe = plaque.get("plaque_evidence", "")
    if pe.startswith("CAC = 0"):
        near.append("CAC=0 (low short-term plaque signal)")
    elif pe.startswith("CAC positive"):
        near.append(pe)
    else:
        near.append("Plaque unmeasured")

    life: List[str] = []
    if p.has("apob"):
        ap = safe_float(p.get("apob"))
        if ap >= 130:
            life.append(f"ApoB {fmt_int(p.get('apob'))}")
        elif APOB_BUFFER_MIN <= ap <= APOB_BUFFER_MAX:
            life.append(f"ApoB {fmt_int(p.get('apob'))} (near boundary)")
        elif ap >= 100:
            life.append(f"ApoB {fmt_int(p.get('apob'))}")
    elif p.has("ldl"):
        ld = safe_float(p.get("ldl"))
        if ld >= 190:
            life.append(f"LDL-C {fmt_int(p.get('ldl'))}")
        elif LDL_BUFFER_MIN <= ld <= LDL_BUFFER_MAX:
            life.append(f"LDL-C {fmt_int(p.get('ldl'))} (near boundary)")
        elif ld >= 130:
            life.append(f"LDL-C {fmt_int(p.get('ldl'))}")

    if lpa_elevated_no_trace(p):
        life.append("Lp(a) elevated")

    if p.get("fhx") is True:
        life.append("Premature family history")

    a1s = a1c_status(p)
    if a1s == "near_diabetes_boundary":
        life.append("A1c near diabetes threshold")
    elif a1s == "prediabetes":
        life.append("Prediabetes")
    elif a1s == "diabetes_range" or p.get("diabetes") is True:
        life.append("Diabetes")

    if not life:
        life.append("No major lifetime accelerators detected")

    return {
        "nearTerm": {"summary": " / ".join(near), "factors": near},
        "lifetime": {"summary": " / ".join(life), "factors": life},
    }

# -------------------------------------------------------------------
# Level labels (taxonomy preserved)
# -------------------------------------------------------------------
LEVEL_LABELS = {
    0: "Level 0 — Not assessed",
    1: "Level 1 — Minimal risk signal",
    2: "Level 2 — Emerging risk signals",  # UI uses 2A/2B
    3: "Level 3 — Actionable biologic risk",
    4: "Level 4 — Subclinical atherosclerosis present",
    5: "Level 5 — Very high risk / ASCVD intensity",
}

def posture_label(level: int, sublevel: Optional[str] = None) -> str:
    base = LEVEL_LABELS.get(level, f"Level {level}")
    if sublevel:
        if level in (2, 3):
            parts = base.split("—", 1)
            if len(parts) == 2:
                return f"Level {sublevel} — {parts[1].strip()}"
    return base

# -------------------------------------------------------------------
# Level assignment (2A/2B + 3A/3B only)
# -------------------------------------------------------------------
def _mild_signals(p: Patient) -> List[str]:
    """
    Mild signals = emerging risk signals that should NOT, by themselves, force Level 3.
    Includes: prediabetes, near-diabetes-boundary A1c, modest ApoB/LDL, isolated hsCRP,
    and (optionally) premature family history as an enhancer-class signal.
    """
    sig: List[str] = []

    # Modest atherogenic markers
    if p.has("apob") and 80 <= safe_float(p.get("apob")) <= 99:
        sig.append("ApoB 80–99")
    if p.has("ldl") and 100 <= safe_float(p.get("ldl")) <= 129:
        sig.append("LDL 100–129")

    # Glycemia (emerging)
    a1s = a1c_status(p)
    if a1s == "prediabetes":
        sig.append("Prediabetes")
    elif a1s == "near_diabetes_boundary":
        sig.append("A1c 6.2–6.4 (near diabetes threshold)")

    # Isolated hsCRP without a chronic inflammatory condition
    if p.has("hscrp") and safe_float(p.get("hscrp")) >= 2 and not has_chronic_inflammatory_disease(p):
        sig.append("hsCRP≥2")

    # Premature family history is an important modifier/enhancer, but not a sole Level 3 trigger
    if p.get("fhx") is True:
        sig.append("Premature family history")

    return sig


def _high_signals(p: Patient, trace: List[Dict[str, Any]]) -> List[str]:
    """
    High signals = MAJOR actionable biologic drivers required to justify Level 3.
    Intentionally excludes:
      - Prediabetes
      - A1c 6.2–6.4 (near diabetes threshold)
      - Premature family history as a sole trigger
    """
    sig: List[str] = []

    # Atherogenic burden (major)
    if p.has("apob") and safe_float(p.get("apob")) >= 100:
        sig.append("ApoB≥100")
    elif p.has("ldl") and safe_float(p.get("ldl")) >= 130:
        sig.append("LDL≥130")

    # Genetics (major)
    if lpa_elevated(p, trace):
        sig.append("Lp(a) elevated")

    # Inflammation (major)
    if has_chronic_inflammatory_disease(p) or inflammation_flags(p):
        sig.append("Inflammation present")

    # Metabolic disease (major only when diabetes-range / true diabetes)
    a1s = a1c_status(p)
    if a1s == "diabetes_range" or p.get("diabetes") is True:
        sig.append("Diabetes")

    # Smoking (major)
    if p.get("smoking") is True:
        sig.append("Smoking")

    return sig


def assign_level(p: Patient, plaque: Dict[str, Any], risk10: Dict[str, Any], trace: List[Dict[str, Any]]) -> Tuple[int, Optional[str], List[str]]:
    triggers: List[str] = []

    if p.get("ascvd") is True:
        triggers.append("Clinical ASCVD")
        add_trace(trace, "Level_override_ASCVD", True, "Level=5")
        return 5, None, triggers

    if plaque.get("plaque_present") is True and plaque.get("cac_value") is not None:
        cac = int(plaque["cac_value"])
        triggers.append(f"CAC {cac}")
        if cac >= 100:
            add_trace(trace, "Level_CAC_100_plus", cac, "Level=5")
            return 5, None, triggers
        add_trace(trace, "Level_CAC_1_99", cac, "Level=4")
        return 4, None, triggers

    hs = _high_signals(p, trace)
    if hs:
        triggers.extend(hs)
        enh = 0
        if lpa_elevated_no_trace(p): enh += 1
        if p.get("fhx") is True: enh += 1
        if has_chronic_inflammatory_disease(p) or inflammation_flags(p): enh += 1

        sub = "3B" if enh >= 1 else "3A"
        add_trace(trace, "Level3_sublevel", sub, "Assigned 3A/3B")
        add_trace(trace, "Level_high_biology", hs[:4], "Level=3")
        return 3, sub, triggers

    ms = _mild_signals(p)
    if ms:
        triggers.extend(ms)
        rp = risk10.get("risk_pct")
        intermediate = (rp is not None and float(rp) >= 7.5)
        converging = (len(ms) >= 2) or intermediate
        sub = "2B" if converging else "2A"
        add_trace(trace, "Level2_sublevel", sub, "Assigned 2A/2B")
        add_trace(trace, "Level_emerging_risk", ms[:4], "Level=2")
        return 2, sub, triggers

    if p.data:
        add_trace(trace, "Level_low_biology", None, "Level=1")
        return 1, None, triggers

    return 0, None, triggers

# -------------------------------------------------------------------
# Decision Confidence (label only: High/Moderate/Low)
# -------------------------------------------------------------------
def decision_confidence(p: Patient, level: int, conf: Dict[str, Any], plaque: Dict[str, Any]) -> str:
    if plaque.get("plaque_present") in (True, False) or plaque.get("plaque_evidence") == "Clinical ASCVD":
        return "High"
    if level >= 4:
        return "High"
    c = (conf or {}).get("confidence", "Low")
    if c == "High":
        return "High"
    if c == "Moderate":
        return "Moderate"
    return "Low"

# -------------------------------------------------------------------
# Decision Stability (how likely plan changes with additional data)
# -------------------------------------------------------------------
def decision_stability(p: Patient, level: int, conf: Dict[str, Any], plaque: Dict[str, Any], risk10: Dict[str, Any]) -> Tuple[str, str]:
    if plaque.get("plaque_present") in (True, False) or plaque.get("plaque_evidence") == "Clinical ASCVD":
        return "High", "plaque assessed"

    dominant = False
    if p.get("diabetes") is True:
        dominant = True
    if p.has("apob") and safe_float(p.get("apob")) >= 130:
        dominant = True
    if (not p.has("apob")) and p.has("ldl") and safe_float(p.get("ldl")) >= 190:
        dominant = True
    if p.get("smoking") is True and p.has("sbp") and safe_float(p.get("sbp")) >= 150:
        dominant = True
    if dominant:
        return "High", "dominant risk drivers"

    rp = risk10.get("risk_pct")
    if pce_zone(rp) == "buffer":
        return "Low", "near boundary; plaque unmeasured"

    missing_clarifiers = []
    if not p.has("apob"):
        missing_clarifiers.append("ApoB")
    if not p.has("lpa"):
        missing_clarifiers.append("Lp(a)")
    if missing_clarifiers and level in (2, 3):
        return "Low", "key clarifiers incomplete"

    return "Moderate", "plaque status unmeasured"
# =========================
# CHUNK 5 / 6 — END
# =========================
# =========================
# CHUNK 6 / 6 — START
# =========================

# -------------------------------------------------------------------
# CAC decision support (suppressed / deferred / optional; never recommended)
# (Tightened language: direct, non-filler)
# -------------------------------------------------------------------
def cac_decision_support(
    p: Patient,
    plaque: Dict[str, Any],
    risk10: Dict[str, Any],
    level: int,
    trace: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if plaque.get("plaque_present") in (True, False) or plaque.get("plaque_evidence") == "Clinical ASCVD":
        add_trace(trace, "CAC_support_suppressed_known", plaque.get("plaque_evidence"), "Plaque already assessed")
        return {"status": "suppressed", "message": None, "reasons": ["Plaque already assessed"]}

    rp = risk10.get("risk_pct")
    zone = pce_zone(rp)

    if zone == "hard_no":
        add_trace(trace, "CAC_support_suppressed_hard_no", rp, f"PCE <{PCE_HARD_NO_MAX}%")
        return {
            "status": "suppressed",
            "message": "Not indicated (low near-term risk).",
            "reasons": [f"ASCVD PCE <{PCE_HARD_NO_MAX:.0f}%"],
        }

    if zone == "high":
        add_trace(trace, "CAC_support_suppressed_high_risk", rp, "High risk → low incremental value")
        return {
            "status": "suppressed",
            "message": "Not needed (management proceeds without CAC at this risk level).",
            "reasons": [f"ASCVD PCE ≥{PCE_ACTION_MAX:.0f}%"],
        }

    labs_needed: List[str] = []
    if not p.has("apob"):
        labs_needed.append("ApoB")
    if not p.has("lpa"):
        labs_needed.append("Lp(a)")

    if labs_needed:
        add_trace(trace, "CAC_support_deferred_labs_first", labs_needed, "Defer CAC until key labs available")
        return {
            "status": "deferred",
            "message": f"Defer until {', '.join(labs_needed)} are available; CAC only matters if it would change intensity/timing.",
            "reasons": [f"Missing {', '.join(labs_needed)}"],
            "labs_first": labs_needed,
        }

    if zone == "buffer":
        add_trace(trace, "CAC_support_deferred_buffer", rp, "Buffer zone → defer default")
        return {
            "status": "deferred",
            "message": "Defer by default in the buffer zone; use CAC only if it will change intensity/timing.",
            "reasons": [f"ASCVD PCE {PCE_BUFFER_MIN:.0f}–{PCE_BUFFER_MAX:.0f}%"],
        }

    preference_sensitive = (level in (2, 3))
    if preference_sensitive:
        add_trace(trace, "CAC_support_optional_actionable", {"risk": rp, "level": level}, "Optional in preference-sensitive zone")
        return {
            "status": "optional",
            "message": "Optional; use only if it will change intensity/timing.",
            "reasons": ["Preference-sensitive zone; key labs available; plaque unmeasured"],
        }

    add_trace(trace, "CAC_support_suppressed_not_preference_sensitive", {"risk": rp, "level": level}, "Low incremental value in current posture")
    return {
        "status": "suppressed",
        "message": "Not indicated (low incremental value).",
        "reasons": ["Low incremental value in current posture"],
    }


# -------------------------------------------------------------------
# Therapy status
# -------------------------------------------------------------------
def on_lipid_therapy(p: Patient) -> bool:
    for k in ("lipid_lowering", "on_statin", "statin", "lipidTherapy"):
        if p.has(k) and bool(p.get(k)) is True:
            return True
    return False


def at_target(p: Patient, targets: Dict[str, int]) -> bool:
    have = False
    ok = True
    if p.has("apob"):
        have = True
        ok = ok and (safe_float(p.get("apob")) <= float(targets.get("apob", 10**9)))
    if p.has("ldl"):
        have = True
        ok = ok and (safe_float(p.get("ldl")) <= float(targets.get("ldl", 10**9)))
    return bool(have and ok)


# -------------------------------------------------------------------
# Plan sentence (used in UI elsewhere; keep but tighten tone)
# -------------------------------------------------------------------
def plan_sentence(level: int, sublevel: Optional[str], therapy_on: bool, at_tgt: bool, risk10: Dict[str, Any], plaque: Dict[str, Any]) -> str:
    zone = pce_zone(risk10.get("risk_pct"))

    if level == 1:
        return "Reassurance posture; routine follow-up."

    if level == 2:
        if zone == "buffer":
            return "Data completion first; reassess. No escalation is required at this time."
        return "Data completion and reassessment."

    if level == 3:
        if therapy_on and at_tgt:
            return "Continue current lipid-lowering intensity; periodic reassessment."
        if therapy_on and not at_tgt:
            return "Optimize lipid-lowering intensity to achieve targets."

        if sublevel == "3B":
            return "Initiation of lipid-lowering therapy is favored unless strong reasons to defer."
        return "Lipid-lowering therapy is reasonable; timing is preference-sensitive."

    if level == 4:
        if therapy_on and at_tgt:
            return "Continue high-intensity lipid lowering; periodic reassessment."
        return "High-intensity lipid lowering is appropriate to achieve targets."

    if therapy_on and at_tgt:
        return "Continue secondary-prevention intensity lipid lowering; periodic reassessment."
    return "Secondary-prevention intensity lipid lowering is indicated; add-ons may be needed."


# -------------------------------------------------------------------
# Next actions (direct; no target repetition unless acting on it)
# -------------------------------------------------------------------
def next_actions(p: Patient, targets: Dict[str, int]) -> List[str]:
    acts: List[str] = []

    # If key clarifiers are missing, that is the actionable next step.
    missing: List[str] = []
    if not p.has("apob"):
        missing.append("ApoB")
    if not p.has("lpa"):
        missing.append("Lp(a)")

    if missing:
        acts.append(f"Obtain {', '.join(missing)} to define atherogenic burden and inherited risk.")
        return acts[:3]

    # If on therapy and not at target, action is optimization (not restating targets).
    if on_lipid_therapy(p) and not at_target(p, targets):
        acts.append("Assess adherence/tolerance; optimize lipid-lowering intensity.")
        return acts[:3]

    # If off therapy and above targets, make the decision explicit.
    if (not on_lipid_therapy(p)) and (
        (p.has("apob") and safe_float(p.get("apob")) > targets.get("apob", 10**9))
        or (p.has("ldl") and safe_float(p.get("ldl")) > targets.get("ldl", 10**9))
    ):
        acts.append("Initiate lipid-lowering therapy; recheck response after initiation.")
        return acts[:3]

    # Otherwise: no urgent action from lipids alone.
    acts.append("No immediate escalation indicated; reassess per clinical cadence.")
    return acts[:3]


# -------------------------------------------------------------------
# Aspirin module
# -------------------------------------------------------------------
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
    rs = [str(x).strip() for x in (rationale or []) if str(x).strip()]
    if not rs:
        return ""
    return "Reasons: " + "; ".join(rs[:3]) + "."


def aspirin_advice(p: Patient, risk10: Dict[str, Any], plaque: Dict[str, Any], trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    age = int(p.get("age", 0)) if p.has("age") else None
    ascvd = (p.get("ascvd") is True)
    bleed_high, bleed_flags = _bleeding_flags(p)

    if ascvd:
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
        status = "Avoid (primary prevention)"
        rationale = [f"Age {age}"]
        return {
            "status": status,
            "rationale": rationale,
            "explanation": aspirin_explanation(status, rationale),
            "bleeding_risk_high": bleed_high,
            "bleeding_flags": bleed_flags,
        }

    if bleed_flags:
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
    cac = plaque.get("cac_value")
    risk_ok = (risk_pct is not None and float(risk_pct) >= 10.0)
    cac_ok = (cac is not None and isinstance(cac, int) and cac >= 100)

    if cac_ok or risk_ok:
        reasons: List[str] = []
        if cac_ok:
            reasons.append("CAC ≥100")
        if risk_ok:
            reasons.append(f"ASCVD PCE ≥10% ({risk_pct}%)")
        reasons.append("No bleeding risk flags identified")
        status = "Consider (shared decision)"
        return {
            "status": status,
            "rationale": reasons,
            "explanation": aspirin_explanation(status, reasons),
            "bleeding_risk_high": bleed_high,
            "bleeding_flags": bleed_flags,
        }

    status = "Avoid / individualize"
    rationale = ["Primary prevention benefit likely small at current risk level"]
    return {
        "status": status,
        "rationale": rationale,
        "explanation": aspirin_explanation(status, rationale),
        "bleeding_risk_high": bleed_high,
        "bleeding_flags": bleed_flags,
    }


# -------------------------------------------------------------------
# Report helpers
# -------------------------------------------------------------------
def trajectory_note(p: Patient, risk10: Dict[str, Any]) -> str:
    if p.has("apob") and safe_float(p.get("apob")) >= 100:
        return "Rising atherogenic burden — track ApoB over time."
    if risk10.get("risk_pct") is not None and float(risk10.get("risk_pct")) >= 15:
        return "Elevated near-term risk — closer follow-up advised."
    if p.has("hscrp") and safe_float(p.get("hscrp")) >= 3:
        return "Inflammatory signal — address drivers and recheck."
    return "Stable profile with available data."


def _primary_driver(drivers: List[str]) -> str:
    return drivers[0] if drivers else "—"


def _context_anchors_sentence(anchors: Dict[str, Any]) -> Tuple[str, str]:
    near = (anchors.get("nearTerm") or {}).get("summary", "—")
    life = (anchors.get("lifetime") or {}).get("summary", "—")
    near = near.replace(" / CAC unknown", "").replace(" / Plaque unmeasured", "")
    return near, life


# -------------------------------------------------------------------
# Public API: evaluate()
# -------------------------------------------------------------------
def evaluate(p: Patient) -> Dict[str, Any]:
    trace: List[Dict[str, Any]] = []
    add_trace(trace, "Engine_start", VERSION["levels"], "Begin evaluation")

    plaque = plaque_state(p, trace)
    risk10 = ascvd_pce_10y_risk(p, trace)
    conf = completeness(p)
    rss = risk_signal_score(p, trace)
    anchors = build_anchors(p, risk10, plaque)
    prevent10 = prevent10_total_and_ascvd(p, trace)

    level, sublevel, level_triggers = assign_level(p, plaque, risk10, trace)
    targets = levels_targets(level)

    therapy_on = on_lipid_therapy(p)
    at_tgt = at_target(p, targets)

    dec_conf = decision_confidence(p, level, conf, plaque)
    stab_band, stab_note = decision_stability(p, level, conf, plaque, risk10)

    cac_support = cac_decision_support(p, plaque, risk10, level, trace)
    asp = aspirin_advice(p, risk10, plaque, trace)

    drivers_all = ranked_drivers(p, plaque, trace)
    drivers_top = drivers_all[:3]

    plan = plan_sentence(level, sublevel, therapy_on, at_tgt, risk10, plaque)
    next_acts = next_actions(p, targets)

    levels_obj = {
        "postureLevel": level,
        "managementLevel": level,
        "sublevel": sublevel,
        "label": posture_label(level, sublevel=sublevel),
        "meaning": LEVEL_LABELS.get(level, f"Level {level}"),
        "triggers": sorted(set(level_triggers or [])),
        "managementPlan": plan,
        "defaultPosture": plan,
        "decisionConfidence": dec_conf,
        "decisionStability": stab_band,
        "decisionStabilityNote": stab_note,
        "plaqueEvidence": plaque.get("plaque_evidence", "—"),
        "plaqueBurden": plaque.get("plaque_burden", "—"),
        "evidence": {
            "clinical_ascvd": True if p.get("ascvd") is True else False,
            "cac_status": plaque.get("plaque_evidence", "Unknown"),
            "burden_band": plaque.get("plaque_burden", "Not quantified"),
            "cac_value": plaque.get("cac_value"),
        },
        "anchorsSummary": {
            "nearTerm": (anchors.get("nearTerm") or {}).get("summary", "—"),
            "lifetime": (anchors.get("lifetime") or {}).get("summary", "—"),
        },
        "legend": levels_legend_compact(),
        "trajectoryNote": trajectory_note(p, risk10),
    }

    disease_burden = "Unknown"
    if p.get("ascvd") is True:
        disease_burden = "Present (clinical ASCVD)"
    elif plaque.get("plaque_present") is True and plaque.get("cac_value") is not None:
        disease_burden = f"Present (CAC {int(plaque['cac_value'])})"
    elif plaque.get("plaque_present") is False:
        disease_burden = "Not detected (CAC=0)"
    elif plaque.get("plaque_evidence", "").startswith("Unknown"):
        disease_burden = "Unknown (CAC not available)"

    insights = {
        "cac_decision_support": cac_support,
        "structural_clarification": cac_support.get("message"),
        "phenotype_label": None,
        "phenotype_definition": None,
        "decision_stability": stab_band,
        "decision_stability_note": stab_note,
        "decision_robustness": stab_band,
        "decision_robustness_note": stab_note,
        "pce_zone": pce_zone(risk10.get("risk_pct")),
    }

    out = {
        "version": VERSION,
        "system": SYSTEM_NAME,
        "levels": levels_obj,
        "riskSignal": {**rss, "drivers": drivers_top},
        "pooledCohortEquations10yAscvdRisk": risk10,
        "ascvdPce10yRisk": risk10,
        "prevent10": prevent10,
        "targets": targets,
        "confidence": conf,
        "diseaseBurden": disease_burden,
        "drivers": drivers_top,
        "drivers_all": drivers_all,
        "nextActions": next_acts,
        "escGoals": esc_numeric_goals(level, clinical_ascvd=bool(p.get("ascvd") is True)),
        "aspirin": asp,
        "anchors": anchors,
        "lpaInfo": lpa_info(p, trace),
        "insights": insights,
        "trace": trace,
        "trajectoryNote": levels_obj.get("trajectoryNote"),
    }

    add_trace(trace, "Engine_end", VERSION["levels"], "Evaluation complete")
    return out


# -------------------------------------------------------------------
# Canonical EMR output (locked style) — tightened: no filler, direct "why / do / optional"
# -------------------------------------------------------------------
def render_quick_text(p: Patient, out: Dict[str, Any]) -> str:
    lvl = out.get("levels") or {}
    rs = out.get("riskSignal") or {}
    risk10 = out.get("pooledCohortEquations10yAscvdRisk") or {}
    prev = out.get("prevent10") or {}
    asp = out.get("aspirin") or {}
    anchors = out.get("anchors") or {}
    ins = out.get("insights") or {}
    trace = out.get("trace") or []

    level = int(lvl.get("managementLevel") or lvl.get("postureLevel") or 0)
    sub = lvl.get("sublevel")

    plaque_evidence = lvl.get("plaqueEvidence") or "—"
    plaque_burden = lvl.get("plaqueBurden") or "—"
    plaque_status = "Unmeasured"
    pe_l = str(plaque_evidence).lower()
    if "cac = 0" in pe_l or "cac=0" in pe_l:
        plaque_status = "CAC = 0"
    elif "cac positive" in pe_l:
        plaque_status = "CAC positive"
    elif "clinical ascvd" in pe_l:
        plaque_status = "Clinical ASCVD"
    elif "unknown" in pe_l or "no structural" in pe_l or "unmeasured" in pe_l:
        plaque_status = "Unmeasured"

    dec_conf = lvl.get("decisionConfidence", "—")

    # PREVENT
    p_total = prev.get("total_cvd_10y_pct")
    p_ascvd = prev.get("ascvd_10y_pct")

    # CAC support status
    cac_support = ins.get("cac_decision_support") or {}
    cac_status = (cac_support.get("status") or "").strip().lower()

    # Aspirin
    asp_status_raw = str(asp.get("status", "Not assessed") or "").strip()
    asp_l = asp_status_raw.lower()
    if asp_l.startswith("avoid"):
        asp_line = "Aspirin: Not indicated"
    elif asp_l.startswith("consider"):
        asp_line = "Aspirin: Consider (shared decision)"
    elif asp_l.startswith("secondary prevention"):
        asp_line = "Aspirin: Secondary prevention (if no contraindication)"
    else:
        asp_line = f"Aspirin: {asp_status_raw}" if asp_status_raw else "Aspirin: —"

    lvl_name = "—"
    if level == 1:
        lvl_name = "Minimal risk signal"
    elif level == 2:
        lvl_name = "Emerging risk signals"
    elif level == 3:
        lvl_name = "Actionable biologic risk"
    elif level == 4:
        lvl_name = "Subclinical atherosclerosis present"
    elif level == 5:
        lvl_name = "Very high risk / ASCVD intensity"

    subtxt = f"{sub}" if sub else None

    # Standardize driver wording (display only)
    def _fmt_driver(s: str) -> str:
        x = (s or "").strip().replace("≥", ">=").replace("≤", "<=")
        mapping = {
            "ApoB>=100": "ApoB ≥100 mg/dL",
            "ApoB≥100": "ApoB ≥100 mg/dL",
            "LDL>=130": "LDL-C ≥130 mg/dL",
            "LDL-C>=130": "LDL-C ≥130 mg/dL",
            "LDL≥130": "LDL-C ≥130 mg/dL",
            "ApoB 80–99": "ApoB 80–99 mg/dL",
            "LDL 100–129": "LDL-C 100–129 mg/dL",
            "hsCRP>=2": "hsCRP ≥2 mg/L",
            "Lp(a) elevated": "Lp(a) elevated",
            "Inflammation present": "Inflammation present",
            "Premature family history": "Premature family history",
            "A1c near diabetes threshold": "A1c 6.2–6.4% (near diabetes threshold)",
            "Prediabetes": "Prediabetes",
            "Diabetes": "Diabetes",
            "Smoking": "Smoking",
        }
        if x in mapping:
            return mapping[x]
        return x.replace(">=", "≥").replace("<=", "≤")

    # Compose report (tight)
    lines: List[str] = []
    lines.append("RISK CONTINUUM — CLINICAL REPORT")
    lines.append("-" * 60)
    if subtxt:
        lines.append(f"Level: {subtxt} — {lvl_name}")
    else:
        lines.append(f"Level: {level} — {lvl_name}")

    # Level drivers (most important “why”)
    level_drivers = lvl.get("triggers") or []
    if level_drivers:
        lines.append("Why this level:")
        for d in level_drivers[:3]:
            lines.append(f"- {_fmt_driver(str(d))}")

    # Plaque
    lines.append(f"Plaque: {plaque_status}")
    if plaque_status in ("CAC positive", "CAC = 0", "Clinical ASCVD"):
        lines.append(f"Plaque burden: {plaque_burden}")

    # Key metrics (one line each, no fluff)
    lines.append("")
    lines.append("Key metrics:")
    lines.append(f"- RSS: {rs.get('score','—')} / 100 ({rs.get('band','—')})")
    if risk10.get("risk_pct") is not None:
        lines.append(f"- ASCVD PCE 10y: {risk10.get('risk_pct')}% ({risk10.get('category','—')})")
    else:
        lines.append("- ASCVD PCE 10y: —")
    lines.append(f"- PREVENT 10y: Total CVD {p_total if p_total is not None else '—'}% | ASCVD {p_ascvd if p_ascvd is not None else '—'}%")

    # Action plan (direct)
    lines.append("")
    lines.append("Action plan:")
    na = out.get("nextActions") or []
    if na:
        for a in na[:3]:
            aa = str(a).strip()
            if aa.endswith("."):
                aa = aa[:-1]
            lines.append(f"- {aa}")
    else:
        lines.append("- —")
    lines.append(f"- {asp_line}")

    # CAC line (single)
    if cac_status == "suppressed":
        lines.append("- CAC: Not indicated")
    elif cac_status == "deferred":
        lines.append("- CAC: Defer (does not change management now)")
    elif cac_status == "optional":
        lines.append("- CAC: Optional (only if it changes intensity/timing)")
    else:
        msg = (ins.get("structural_clarification") or "").strip()
        if msg:
            lines.append(f"- CAC: {msg}")
        else:
            lines.append("- CAC: —")

    # Context (one line)
    near = (anchors.get("nearTerm") or {}).get("summary", "—")
    life = (anchors.get("lifetime") or {}).get("summary", "—")
    lines.append("")
    lines.append(f"Context: Near-term: {near} | Lifetime: {life}")
    lines.append(f"Decision confidence: {dec_conf}")

    return "\n".join(lines)

# =========================
# CHUNK 6 / 6 — END
# =========================
