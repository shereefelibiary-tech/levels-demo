# =========================
# CHUNK 1 / 6 — START
# =========================
# levels_engine.py
# Risk Continuum™ Engine — v3.1 (buffer-based thresholds; locked language; Epic-aligned PCE; CAC gating; modality-aware plan)
#
# Goals:
# - Outputs "ease and confidence" in CV risk management decisions
# - Senior clinical tone (no second person; no marketing language)
# - CAC is reasonable to obtain when plaque status is unmeasured; results inform burden, intensity, and downstream evaluation
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
#
# NEW in this file (compat fixes):
# - levels["dominantAction"] flag (used by app.py recommended_action_line())
# - render_quick_text() no longer adds unconditional CAC lines (prevents duplication/contradictions)

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


def risk_model_mismatch(risk10: Dict[str, Any], prevent10: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare PCE vs PREVENT and return a conservative, clinician-safe interpretation.
    Decision-support framing only (does not change level/plan).
    """
    pce = risk10.get("risk_pct", None)
    prev_total = prevent10.get("total_cvd_10y_pct", None)

    try:
        pce_f = float(pce) if pce is not None else None
    except Exception:
        pce_f = None
    try:
        prev_f = float(prev_total) if prev_total is not None else None
    except Exception:
        prev_f = None

    if pce_f is None or prev_f is None:
        return {"status": "unavailable"}

    delta = round(pce_f - prev_f, 1)

    if abs(delta) < 1.5:
        tag = "aligned"
        label = "Aligned"
        should_surface = False
    elif delta >= 1.5:
        tag = "atherosclerosis_leading"
        label = "PCE higher than PREVENT"
        should_surface = True
    else:
        tag = "comorbidity_leading"
        label = "PREVENT higher than PCE"
        should_surface = True

    explainer_clinical = (
        "ASCVD PCE estimates atherosclerotic event risk and is sensitive to lipid burden, smoking, and diabetes. "
        "PREVENT estimates population cardiovascular event risk and is influenced more by age, kidney disease, diabetes, BMI, and social risk. "
        "When these estimates diverge, it may reflect different dominant risk drivers or early atherosclerotic risk before population event rates rise."
    )

    explainer_kid = (
        "One model looks for early warning signs, like seeing smoke. "
        "The other counts serious events, like a fire alarm going off. "
        "Smoke can appear before the alarm is triggered."
    )

    return {
        "status": "ok",
        "pce_pct": pce_f,
        "prevent_total_cvd_pct": prev_f,
        "delta_points": delta,
        "tag": tag,
        "label": label,
        "should_surface": bool(should_surface),
        "explainer_clinical": explainer_clinical,
        "explainer_kid": explainer_kid,
    }


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


def _format_ckd_stage_headline(p: Patient) -> Optional[str]:
    """
    Returns "CKD3a (eGFR 59)" style headline, or None if eGFR missing.
    """
    if not p.has("egfr"):
        return None
    try:
        egfr = float(safe_float(p.get("egfr")))
    except Exception:
        return None

    g = _ckd_g_category(float(egfr))
    egfr_int = int(round(float(egfr)))
    return f"CKD{g} (eGFR {egfr_int})"


def derive_ckm_stage_and_driver(p: Patient) -> Tuple[int, str]:
    """
    Returns (stage_num, stage_driver_label).
    """
    if p.get("ascvd") is True:
        return 3, "ASCVD-driven risk"

    egfr = None
    if p.has("egfr"):
        try:
            egfr = float(safe_float(p.get("egfr")))
        except Exception:
            egfr = None
    if egfr is not None and float(egfr) < 60:
        return 3, "CKD-driven risk"

    if p.get("diabetes") is True or a1c_status(p) == "diabetes_range":
        return 2, "metabolic disease"

    bmi = None
    if p.has("bmi"):
        try:
            bmi = float(safe_float(p.get("bmi")))
        except Exception:
            bmi = None
    if bmi is not None and float(bmi) >= 30:
        return 1, "risk factors"

    sbp = None
    if p.has("sbp"):
        try:
            sbp = float(safe_float(p.get("sbp")))
        except Exception:
            sbp = None
    if (sbp is not None and float(sbp) >= 130) or (p.get("bp_treated") is True):
        return 1, "risk factors"

    if a1c_status(p) in ("prediabetes", "near_diabetes_boundary"):
        return 1, "risk factors"

    if p.has("apob") or p.has("ldl"):
        return 1, "risk factors"

    return 0, "none identified"


def canonical_ckd_copy(p: Patient, decision_conf: str) -> Optional[Dict[str, Any]]:
    """
    Canonical CKD headline used by BOTH UI and EMR.
    Returns None if eGFR missing.
    """
    if str(decision_conf or "").strip().lower() not in ("high", "moderate"):
        return None

    head = _format_ckd_stage_headline(p)
    if not head:
        return None

    return {"headline": head, "detail": None}


def canonical_ckm_copy_stage(p: Patient, ckm: Dict[str, Any], decision_conf: str) -> Optional[Dict[str, Any]]:
    """
    Stage-based CKM headline used by BOTH UI and EMR.

    Produces: "Stage 3 (CKD-driven risk)"
    """
    if str(decision_conf or "").strip().lower() not in ("high", "moderate"):
        return None

    stage, driver = derive_ckm_stage_and_driver(p)

    contributors: List[str] = []
    if isinstance(ckm, dict):
        if ckm.get("ckd_present"):
            contributors.append("kidney factors")
        if ckm.get("metabolic_acceleration"):
            contributors.append("metabolic factors")
        if ckm.get("obesity_present"):
            contributors.append("obesity-related risk")
        if ckm.get("hypertension_burden"):
            contributors.append("blood pressure burden")

    # Suppress CKM copy when there are no CKM contributors (avoids "Stage 1 (dyslipidemia)" noise)
    if not contributors:
        return None

    headline = f"Stage {stage} ({driver})" if stage != 0 else "Stage 0 (none identified)"
    detail = ("Contributors: " + ", ".join(contributors) + ".") if contributors else None

    return {
        "headline": headline,
        "detail": detail,
        "stage": stage,
        "driver": driver,
        "contributors": contributors,
    }

# ============================================================
# Locked Definitions (single source of truth)
# Put this block OUTSIDE of any function (top-level)
# ============================================================

LEVEL_DEFS = {
    1: {
        "name": "Minimal risk signal",
        "definition": (
            "No established atherosclerotic disease and no dominant biologic risk driver is present on the available data."
        ),
        "typical_pattern": [
            "Plaque unmeasured or CAC=0",
            "No major atherogenic burden signal (ApoB <100; if ApoB unavailable, LDL-C <130)",
            "No diabetes-range signal, no current smoking, no inflammatory disease/flag driving risk",
            "Near-term risk (if available) typically low",
        ],
        "medication_action": "Lifestyle-first. No escalation in lipid-lowering intensity is required. Periodic reassessment.",
    },
    2: {
        "name": "Emerging risk signals",
        "definition": (
            "Pre-disease risk signals are present. Attention is directed toward data completion, trajectory, and risk clarification."
        ),
        "typical_pattern": [
            "Mild biologic signals without established plaque",
            "Preference-sensitive management after clarifiers and trajectory are assessed",
        ],
        "medication_action": "Complete missing data, run a lifestyle sprint, reassess; treatment may be reasonable depending on convergence (2B).",
    },
    3: {
        "name": "Actionable biologic risk",
        "definition": (
            "Actionable biologic drivers are present even without known plaque. Management becomes more medication-forward."
        ),
        "typical_pattern": [
            "Major actionable biologic driver present (ApoB/LDL, Lp(a), inflammatory disease/hsCRP context, diabetes-range, or smoking)",
            "Plaque may be unmeasured; CAC can be obtained to define disease burden when results would inform intensity/targets or downstream evaluation",
        ],
        "medication_action": "Lipid-lowering therapy is reasonable (3A) or generally favored (3B).",
    },
    4: {
        "name": "Subclinical atherosclerosis present",
        "definition": "Atherosclerotic disease is present on imaging without established clinical ASCVD events.",
        "typical_pattern": [
            "CAC >0 and <100",
            "Treat as early disease with target-driven lipid lowering",
        ],
        "medication_action": (
            "Lipid-lowering therapy is appropriate; intensity individualized based on targets, risk profile, and tolerance."
        ),
    },
    5: {
        "name": "Very high risk / ASCVD intensity",
        "definition": (
            "Clinical ASCVD is present or plaque burden is high enough that management is treated as very high risk."
        ),
        "typical_pattern": [
            "Clinical ASCVD true OR CAC ≥100",
            "Maximize tolerated therapy to achieve targets; consider add-ons if not at target",
        ],
        "medication_action": "Secondary-prevention intensity lipid lowering; maximize tolerated therapy; add-on therapy is reasonable if not at target.",
    },
}

# Explicit lists (no “etc”) used for rendering + transparency
MILD_SIGNALS_EXPLICIT = [
    "ApoB 80–99 mg/dL (if measured)",
    "LDL-C 100–129 mg/dL (used only if ApoB not measured)",
    "Prediabetes-range A1c 5.7–6.1% (if present)",
    "A1c 6.2–6.4% (near diabetes threshold; do not label diabetes)",
    "hsCRP ≥2 mg/L without chronic inflammatory disease present",
    "Premature family history (first-degree premature ASCVD) as an isolated enhancer",
]

MAJOR_ACTIONABLE_DRIVERS_EXPLICIT = [
    "ApoB ≥100 mg/dL (preferred marker)",
    "LDL-C ≥130 mg/dL (used only if ApoB not measured)",
    "Lp(a) elevated (≥125 nmol/L or ≥50 mg/dL; unit-aware)",
    "Chronic inflammatory disease present (RA, psoriasis, SLE, IBD, HIV, OSA, NAFLD/MASLD) or hsCRP ≥2 with supportive context",
    "Diabetes-range signal (A1c ≥6.5% or diabetes flag true)",
    "Current smoking",
]

SUBLEVEL_DEFS = {
    "2A": {
        "parent_level": 2,
        "name": "Emerging (isolated / mild)",
        "definition": (
            "Exactly one mild signal is present without convergence from other mild signals or near-term risk signals."
        ),
        "qualifying_criteria": [
            "One (and only one) mild signal from the explicit list below",
            "Does not meet any 2B criteria",
        ],
        "mild_signals_list": MILD_SIGNALS_EXPLICIT,
        "medication_action": "Do not treat routinely. Complete missing data, run a lifestyle sprint, reassess.",
    },
    "2B": {
        "parent_level": 2,
        "name": "Emerging (converging / rising)",
        "definition": (
            "Mild signals are converging such that near-term risk or trajectory is less likely to be noise."
        ),
        "qualifying_criteria": [
            "Two or more Level-2A mild signals present (any combination), OR",
            "ASCVD PCE ≥7.5% (if calculated) AND plaque is unmeasured, OR",
            "One mild signal plus key clarifiers missing (ApoB not measured or Lp(a) not measured)",
        ],
        "medication_action": "Treatment is reasonable and preference-sensitive after data completion; reassess after clarifiers and/or a defined lifestyle interval.",
    },
    "3A": {
        "parent_level": 3,
        "name": "Actionable biology (limited enhancers)",
        "definition": (
            "At least one major actionable biologic driver is present without additional accelerators beyond the driver itself."
        ),
        "qualifying_criteria": [
            "Meets one major actionable biologic driver from the explicit list below",
            "Does not meet 3B enhancer criteria",
        ],
        "major_drivers_list": MAJOR_ACTIONABLE_DRIVERS_EXPLICIT,
        "medication_action": "Lipid-lowering therapy is reasonable; timing is preference-sensitive, guided by targets and trajectory.",
    },
    "3B": {
        "parent_level": 3,
        "name": "Actionable biology + accelerators (enhancers)",
        "definition": (
            "Actionable biology is present and at least one additional accelerator increases the likelihood that earlier treatment is beneficial."
        ),
        "qualifying_criteria": [
            "Meets one major actionable biologic driver from the explicit list below, AND",
            "At least one enhancer/accelerator is present:",
            "  - Lp(a) elevated (≥125 nmol/L or ≥50 mg/dL), OR",
            "  - Premature family history (first-degree premature ASCVD), OR",
            "  - Chronic inflammatory disease present (RA/psoriasis/SLE/IBD/HIV/OSA/NAFLD/MASLD) or supportive hsCRP context, OR",
            "  - Diabetes-range (A1c ≥6.5 or diabetes true), OR",
            "  - Current smoking",
        ],
        "major_drivers_list": MAJOR_ACTIONABLE_DRIVERS_EXPLICIT,
        "medication_action": (
            "Therapy is generally favored unless there is a strong reason to defer. "
            "If plaque is unmeasured, CAC can be obtained to define disease burden and to inform intensity/targets or downstream evaluation."
        ),
    },
}

CAC_RULE_TEXT = (
    "Coronary artery calcium (CAC) can be obtained to define atherosclerotic disease burden when plaque status is unmeasured. "
    "It is most useful when the result would change treatment intensity/targets or inform downstream evaluation. "
    "If CAC is already known (CAC=0 or CAC positive), CAC messaging is suppressed."
)

def get_level_definition_payload(level: int, sublevel: Optional[str] = None) -> Dict[str, Any]:
    lvl = int(level or 0)
    base = LEVEL_DEFS.get(lvl, {})
    payload: Dict[str, Any] = {
        "level_name": base.get("name"),
        "level_definition": base.get("definition"),
        "level_typical_pattern": base.get("typical_pattern", []),
        "level_medication_action": base.get("medication_action"),
        "cac_rule": CAC_RULE_TEXT,
    }
    if sublevel:
        s = str(sublevel).strip()
        sd = SUBLEVEL_DEFS.get(s)
        if sd:
            payload.update({
                "sublevel": s,
                "sublevel_name": sd.get("name"),
                "sublevel_definition": sd.get("definition"),
                "sublevel_criteria": sd.get("qualifying_criteria", []),
                "sublevel_medication_action": sd.get("medication_action"),
                "mild_signals_list": sd.get("mild_signals_list"),
                "major_drivers_list": sd.get("major_drivers_list"),
            })
    return payload

def levels_legend_compact() -> List[str]:
    """
    UI legend lines that stay consistent with the locked definitions above.
    """
    return [
        "Level 1: minimal signal → lifestyle-first; periodic reassess",
        "Level 2A: emerging (isolated) → data completion; lifestyle sprint; reassess",
        "Level 2B: emerging (converging) → clarify risk; treatment reasonable (preference-sensitive)",
        "Level 3A: actionable biology → therapy reasonable; timing preference-sensitive",
        "Level 3B: actionable biology + enhancers → therapy generally favored; CAC can define disease burden if unmeasured",
        "Level 4: plaque present (CAC 1–99) → lipid-lowering appropriate; intensity individualized (target-driven)",
        "Level 5: very high risk (CAC ≥100 or clinical ASCVD) → secondary-prevention intensity",
        "CAC: reasonable to obtain when plaque status is unmeasured; informs burden, intensity, and downstream evaluation",
    ]

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
# CKM context (Cardio–Kidney–Metabolic) — v0.1 (display-first)
# -------------------------------------------------------------------
def ckm_context(p: Patient) -> Dict[str, Any]:
    """
    CKM v0.1: minimal, defensible, display-first context.
    Does NOT change level, targets, or actions (initially).
    """
    egfr = safe_float(p.get("egfr")) if p.has("egfr") else None
    uacr = safe_float(p.get("uacr")) if p.has("uacr") else None
    a1c = safe_float(p.get("a1c")) if p.has("a1c") else None
    bmi = safe_float(p.get("bmi")) if p.has("bmi") else None
    sbp = safe_float(p.get("sbp")) if p.has("sbp") else None

    # --- Kidney ---
    ckd_present = False
    ckd_stage = "Unknown"
    if egfr is not None or uacr is not None:
        ckd_present = (egfr is not None and egfr < 60) or (uacr is not None and uacr >= 30)
        if egfr is None:
            ckd_stage = "CKD status indeterminate (eGFR missing)"
        else:
            if egfr >= 60:
                ckd_stage = "No CKD" if (uacr is None or uacr < 30) else "CKD (albuminuric)"
            elif egfr >= 45:
                ckd_stage = "CKD G3a"
            elif egfr >= 30:
                ckd_stage = "CKD G3b"
            else:
                ckd_stage = "CKD G4–5"

    # --- Metabolic ---
    ms = a1c_status(p)  # uses your buffered thresholds
    if ms is None:
        metabolic_state = "Unknown"
    elif ms == "normal":
        metabolic_state = "Normal"
    elif ms == "prediabetes":
        metabolic_state = "Prediabetes"
    elif ms == "near_diabetes_boundary":
        metabolic_state = "Near diabetes threshold (6.2–6.4)"
    else:
        metabolic_state = "Diabetes"

    metabolic_acceleration = bool(
        (a1c is not None and a1c >= 6.2) or (p.get("diabetes") is True)
    )

    # --- Obesity ---
    obesity_present = bool(bmi is not None and bmi >= 30)

    # --- BP burden (minimal) ---
    hypertension_burden = bool((sbp is not None and sbp >= 140) or (p.get("bp_treated") is True))

    return {
        "ckd_present": bool(ckd_present),
        "ckd_stage": ckd_stage,
        "metabolic_state": metabolic_state,
        "metabolic_acceleration": bool(metabolic_acceleration),
        "obesity_present": bool(obesity_present),
        "hypertension_burden": bool(hypertension_burden),
        "values": {
            "egfr": (None if egfr is None else round(float(egfr), 0)),
            "uacr": (None if uacr is None else round(float(uacr), 0)),
            "a1c": (None if a1c is None else round(float(a1c), 1)),
            "bmi": (None if bmi is None else round(float(bmi), 1)),
            "sbp": (None if sbp is None else int(round(float(sbp)))),
        },
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
        rf_count, _rf_missing = _atp_rf_count_with_completeness(p)
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
# Secondary insight: Lifestyle-responsive vs Biology-dominant pattern
# -------------------------------------------------------------------
def classify_risk_driver(
    *,
    p: Patient,
    plaque: Dict[str, Any],
    rss: Dict[str, Any],
    risk10: Dict[str, Any],
    level: int,
    sublevel: Optional[str],
    decision_confidence: str,
    trace: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Conservative, clinician-facing driver pattern classifier.

    Goal:
      - Surface only when confidence is high and signals are concordant.
      - Never claims "genetic" — frames as biologic vs behavioral mediation.
      - Suppress when plaque is known (CAC=0 or CAC positive) or ASCVD is present.
      - Suppress in higher postures (Level 4+) and when decision confidence isn't High.

    Returns:
      {
        "should_surface": bool,
        "class": "biology_dominant"|"lifestyle_responsive"|"mixed",
        "confidence": "high"|"low",
        "headline": str|None,
        "detail": str|None,
        "debug": {...}  # optional; safe to omit from UI
      }
    """

    # ---- defaults (silent) ----
    out = {
        "should_surface": False,
        "class": "mixed",
        "confidence": "low",
        "headline": None,
        "detail": None,
        "debug": {},
    }

    # ---- suppressions: keep cardiology/medico-legal comfortable ----
    if str(decision_confidence or "").strip().lower() != "high":
        add_trace(trace, "RiskDriver_suppressed_confidence", decision_confidence, "Decision confidence not high")
        return out

    # If plaque already assessed (CAC known or ASCVD), do not label drivers.
    if p.get("ascvd") is True or plaque.get("plaque_present") in (True, False):
        add_trace(trace, "RiskDriver_suppressed_plaque_known", plaque.get("plaque_evidence"), "Plaque already assessed")
        return out

    # If higher posture (plaque-driven), do not distract.
    if int(level or 0) >= 4:
        add_trace(trace, "RiskDriver_suppressed_level4plus", level, "Higher posture")
        return out

    # Require key domains in play: need at least ApoB or LDL AND RSS AND age.
    if not p.has("age"):
        add_trace(trace, "RiskDriver_suppressed_missing_age", None, "Age missing")
        return out

    rss_score = None
    try:
        rss_score = int(rss.get("score"))
    except Exception:
        rss_score = None

    apob = safe_float(p.get("apob")) if p.has("apob") else None
    ldl = safe_float(p.get("ldl")) if p.has("ldl") else None
    lpa_hi = bool(lpa_elevated_no_trace(p))

    if apob is None and ldl is None:
        add_trace(trace, "RiskDriver_suppressed_missing_athero", None, "No ApoB/LDL available")
        return out
    if rss_score is None:
        add_trace(trace, "RiskDriver_suppressed_missing_rss", None, "RSS missing")
        return out

    age = int(p.get("age"))
    # optional near-term risk (may be None)
    pce = risk10.get("risk_pct")
    pce_f = float(pce) if pce is not None else None

    # ---- domain flags ----
    # Strong biologic marker signal
    bio_strong = False
    if apob is not None and apob >= 120:
        bio_strong = True
    if lpa_hi:
        bio_strong = True
    # LDL can contribute only when ApoB absent (avoid mixed messaging)
    if apob is None and ldl is not None and ldl >= 190:
        bio_strong = True

    # Strong lifestyle burden (RSS is your biologic+plaque signal, but
    # in practice high RSS without strong atherogenic markers suggests behavior/metabolic contributors.)
    lifestyle_burden = (rss_score >= 60)

    # Age–risk discordance (conservative)
    # Without plaque, use “very strong biology at young age” as discordance.
    age_discordant = False
    if age < 50 and (lpa_hi or (apob is not None and apob >= 130)):
        age_discordant = True

    # ---- voting (require >=3 "votes" for any surfacing) ----
    bio_votes = 0
    life_votes = 0

    # Domain 1: Atherogenic biology
    if bio_strong:
        bio_votes += 1
    else:
        # if clearly low-ish ApoB and no Lp(a), that supports lifestyle-responsiveness
        if (apob is not None and apob < 100) and (not lpa_hi):
            life_votes += 1

    # Domain 2: Lifestyle burden proxy
    if lifestyle_burden:
        life_votes += 1

    # Domain 3: Age proportionality
    if age_discordant:
        bio_votes += 1

    # Domain 4: Near-term risk discordance (optional)
    # If PCE is low but biology is strong, that's a “biology-dominant” pattern.
    if pce_f is not None and pce_f < 5.0 and bio_strong:
        bio_votes += 1
    # If PCE is elevated but biology is not strong and RSS high, that supports modifiable exposure.
    if pce_f is not None and pce_f >= 7.5 and (not bio_strong) and lifestyle_burden:
        life_votes += 1

    out["debug"] = {
        "age": age,
        "rss": rss_score,
        "apob": apob,
        "ldl": ldl,
        "lpa_hi": lpa_hi,
        "pce": pce_f,
        "bio_votes": bio_votes,
        "life_votes": life_votes,
    }

    # ---- high-confidence thresholds (asymmetric strictness) ----
    # Biology-dominant: requires strong biology + discordance + low lifestyle burden.
    biology_high = (
        bio_votes >= 3
        and bio_strong
        and (not lifestyle_burden or rss_score < 50)
    )

    # Lifestyle-responsive: requires strong lifestyle burden + lack of strong biology.
    lifestyle_high = (
        life_votes >= 3
        and lifestyle_burden
        and (not bio_strong)
        and (not age_discordant)
    )

    if biology_high:
        add_trace(trace, "RiskDriver_biology_high", out["debug"], "Biology-dominant pattern surfaced")
        return {
            "should_surface": True,
            "class": "biology_dominant",
            "confidence": "high",
            "headline": "Risk appears biologically driven rather than behaviorally mediated",
            "detail": "Risk signals appear disproportionate to modifiable exposures; lifestyle improves health but may not fully normalize atherosclerotic risk.",
            "debug": out["debug"],
        }

    if lifestyle_high:
        add_trace(trace, "RiskDriver_lifestyle_high", out["debug"], "Lifestyle-responsive pattern surfaced")
        return {
            "should_surface": True,
            "class": "lifestyle_responsive",
            "confidence": "high",
            "headline": "Risk pattern appears responsive to lifestyle change",
            "detail": "Modifiable exposures appear to be primary drivers on the available data; a time-bounded lifestyle interval is reasonable before escalation.",
            "debug": out["debug"],
        }

    add_trace(trace, "RiskDriver_not_surfaced", out["debug"], "Mixed/indeterminate")
    return out

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
# Level labels (management taxonomy; explicit sublevels 2A/2B/3A/3B)
# -------------------------------------------------------------------
LEVEL_LABELS = {
    0: "Level 0 — Not assessed",
    1: "Level 1 — Minimal risk signal",
    2: "Level 2 — Emerging risk signals",
    3: "Level 3 — Actionable biologic risk",
    4: "Level 4 — Subclinical atherosclerosis present",
    5: "Level 5 — Very high risk / ASCVD intensity",
}

SUBLEVEL_LABELS = {
    "2A": "Level 2A — Emerging (isolated / mild)",
    "2B": "Level 2B — Emerging (converging / rising)",
    "3A": "Level 3A — Actionable biology (limited enhancers)",
    "3B": "Level 3B — Actionable biology + enhancers",
}

# -------------------------------------------------------------------
# Explicit numeric cutoffs (single source of truth for 2A/2B/3A/3B)
# -------------------------------------------------------------------
# Mild (Level 2 candidates)
MILD_APOB_MIN = 80.0
MILD_APOB_MAX = 99.0
MILD_LDL_MIN = 100.0
MILD_LDL_MAX = 129.0
HSCRP_MILD_CUT = 2.0  # counts as mild ONLY if NO chronic inflammatory disease present

# Major actionable (Level 3 candidates)
MAJOR_APOB_CUT = 100.0
MAJOR_LDL_CUT = 130.0  # used ONLY if ApoB is NOT measured

# PCE convergence trigger for 2B
PCE_INTERMEDIATE_CUT = 7.5  # if PCE available and >=7.5 and plaque unmeasured, counts as converging

# CAC disease definitions
CAC_LEVEL4_MIN = 1
CAC_LEVEL4_MAX = 99
CAC_LEVEL5_CUT = 100

# Diabetes definition used for major driver:
# - diabetes flag true OR a1c_status == "diabetes_range" (your a1c_status uses >=6.5)
# Smoking: p.get("smoking") True

def management_label(level: int, sublevel: Optional[str] = None) -> str:
    """
    Human-facing label.
    Uses explicit sublevel label when present; otherwise uses base level label.
    """
    base = LEVEL_LABELS.get(int(level or 0), f"Level {level}")
    if sublevel:
        s = str(sublevel).strip().upper()
        if s in SUBLEVEL_LABELS:
            return SUBLEVEL_LABELS[s]
        # fallback: preserve older behavior if unexpected sublevel appears
        if int(level or 0) in (2, 3):
            parts = base.split("—", 1)
            if len(parts) == 2:
                return f"Level {s} — {parts[1].strip()}"
    return base


# -------------------------------------------------------------------
# Level assignment (2A/2B + 3A/3B only) — explicit logic
# Notes:
# - ApoB is the preferred atherogenic marker.
# - LDL-C thresholds are used ONLY when ApoB is missing.
# - Lp(a) uses unit-aware lpa_elevated().
# - Inflammation major driver: chronic inflammatory disease OR inflammation flags (hsCRP≥2 or condition flags).
# -------------------------------------------------------------------
def _mild_signals(p: Patient) -> List[str]:
    """
    Mild signals (Level 2 candidates).
    These are NOT sufficient to force Level 3 by themselves.

    Explicit list:
      - ApoB 80–99 mg/dL (if measured)
      - LDL-C 100–129 mg/dL (ONLY if ApoB not measured)
      - Prediabetes A1c (a1c_status == "prediabetes") [5.7–6.1 by your a1c_status thresholds]
      - A1c 6.2–6.4 (near diabetes threshold) [a1c_status == "near_diabetes_boundary"]
      - hsCRP ≥2 mg/L ONLY if no chronic inflammatory disease is present
      - Premature family history (fhx == True)
    """
    sig: List[str] = []

    # Atherogenic mild: ApoB preferred; LDL only if ApoB missing
    if p.has("apob"):
        ap = safe_float(p.get("apob"))
        if MILD_APOB_MIN <= ap <= MILD_APOB_MAX:
            sig.append(f"ApoB {int(MILD_APOB_MIN)}–{int(MILD_APOB_MAX)}")
    else:
        if p.has("ldl"):
            ld = safe_float(p.get("ldl"))
            if MILD_LDL_MIN <= ld <= MILD_LDL_MAX:
                sig.append(f"LDL {int(MILD_LDL_MIN)}–{int(MILD_LDL_MAX)} (ApoB not measured)")
            else:
                # Guardrail: when CAC=0 and ApoB is unmeasured, LDL 130–159 behaves as a mild signal
                # (avoid false Level 1 when LDL is slightly above major cut but plaque is absent and near-term risk is very low)
                cac0 = False
                try:
                    cac0 = p.has("cac") and int(safe_float(p.get("cac"), default=-1)) == 0
                except Exception:
                    cac0 = False
                if cac0 and 130 <= ld <= 159:
                    sig.append("LDL 130–159 (CAC=0; ApoB not measured)")

    # Glycemia mild / near-boundary (uses your a1c_status)
    a1s = a1c_status(p)
    if a1s == "prediabetes":
        sig.append("Prediabetes (A1c 5.7–6.1)")
    elif a1s == "near_diabetes_boundary":
        sig.append("A1c 6.2–6.4 (near diabetes threshold)")

    # hsCRP mild only if not chronic inflammatory disease
    if p.has("hscrp") and safe_float(p.get("hscrp")) >= HSCRP_MILD_CUT and not has_chronic_inflammatory_disease(p):
        sig.append("hsCRP≥2 (isolated)")

    # Family history as mild enhancer only
    if p.get("fhx") is True:
        sig.append("Premature family history")

    return sig

def _high_signals(p: Patient, risk10: Dict[str, Any], trace: List[Dict[str, Any]]) -> List[str]:
    """
    Major actionable biologic drivers (Level 3 candidates).

    Explicit list:
      - ApoB ≥100 mg/dL (preferred)
      - LDL-C ≥130 mg/dL ONLY if ApoB not measured
      - Lp(a) elevated (unit-aware): ≥125 nmol/L OR ≥50 mg/dL
      - Inflammation present: chronic inflammatory disease OR hsCRP≥2 OR inflammatory condition flags
      - Diabetes-range: a1c_status == "diabetes_range" OR diabetes flag True
      - Current smoking: smoking flag True
    """
    sig: List[str] = []

    # Major atherogenic: ApoB preferred; LDL only if ApoB missing
    if p.has("apob") and safe_float(p.get("apob")) >= MAJOR_APOB_CUT:
        sig.append(f"ApoB≥{int(MAJOR_APOB_CUT)}")
    elif (not p.has("apob")) and p.has("ldl") and safe_float(p.get("ldl")) >= MAJOR_LDL_CUT:
        # Guardrail: LDL-only major signal should not override CAC=0 + very low PCE
        cac0 = False
        try:
            cac0 = p.has("cac") and int(safe_float(p.get("cac"), default=-1)) == 0
        except Exception:
            cac0 = False

        rp = risk10.get("risk_pct") if isinstance(risk10, dict) else None
        rp_f = None
        try:
            rp_f = float(rp) if rp is not None else None
        except Exception:
            rp_f = None

        low_risk = (rp_f is not None and rp_f < PCE_HARD_NO_MAX)

        if cac0 and low_risk:
            add_trace(
                trace,
                "LDL_major_suppressed_CAC0_lowPCE",
                {"ldl": p.get("ldl"), "pce": rp_f, "cac": 0},
                "LDL-only major signal suppressed",
            )
        else:
            sig.append(f"LDL≥{int(MAJOR_LDL_CUT)} (ApoB not measured)")

    # Genetics
    if lpa_elevated(p, trace):
        sig.append("Lp(a) elevated")

    # Inflammation: disease OR flags (includes hsCRP≥2 in inflammation_flags)
    if has_chronic_inflammatory_disease(p) or inflammation_flags(p):
        sig.append("Inflammation present")

    # Diabetes-range
    a1s = a1c_status(p)
    if a1s == "diabetes_range" or p.get("diabetes") is True:
        sig.append("Diabetes-range (A1c ≥6.5 or diabetes flag)")

    # Smoking
    if p.get("smoking") is True:
        sig.append("Smoking")

    return sig

def assign_level(
    p: Patient,
    plaque: Dict[str, Any],
    risk10: Dict[str, Any],
    trace: List[Dict[str, Any]],
) -> Tuple[int, Optional[str], List[str]]:
    """
    Returns: (management_level, sublevel, triggers)

    Hard rules:
      - Level 5: clinical ASCVD OR CAC ≥100
      - Level 4: CAC 1–99
      - Level 3: major actionable biology present (3A vs 3B depends on enhancers)
      - Level 2: mild signals present (2A vs 2B depends on convergence)
      - Level 1: default when some data present but no mild/major signals
    """
    triggers: List[str] = []

    # Level 5: clinical ASCVD
    if p.get("ascvd") is True:
        triggers.append("Clinical ASCVD")
        add_trace(trace, "Level_override_ASCVD", True, "Level=5")
        return 5, None, triggers

    # Level 4/5: CAC known
    if plaque.get("plaque_present") is True and plaque.get("cac_value") is not None:
        cac = int(plaque["cac_value"])
        triggers.append(f"CAC {cac}")
        if cac >= CAC_LEVEL5_CUT:
            add_trace(trace, "Level_CAC_100_plus", cac, "Level=5")
            return 5, None, triggers
        # CAC 1–99 => Level 4
        if CAC_LEVEL4_MIN <= cac <= CAC_LEVEL4_MAX:
            add_trace(trace, "Level_CAC_1_99", cac, "Level=4")
            return 4, None, triggers

    # Level 3: major actionable biology
    hs = _high_signals(p, risk10, trace)
    if hs:
        triggers.extend(hs)

        # 3B enhancers (explicit, ≥1 triggers 3B)
        enh = 0
        # Lp(a)
        if lpa_elevated_no_trace(p):
            enh += 1
        # Premature family history
        if p.get("fhx") is True:
            enh += 1
        # Inflammation disease/flags
        if has_chronic_inflammatory_disease(p) or inflammation_flags(p):
            enh += 1
        # Diabetes-range
        if a1c_status(p) == "diabetes_range" or p.get("diabetes") is True:
            enh += 1
        # Smoking
        if p.get("smoking") is True:
            enh += 1

        sub = "3B" if enh >= 1 else "3A"
        add_trace(trace, "Level3_sublevel", sub, "Assigned 3A/3B")
        add_trace(trace, "Level_high_biology", hs[:6], "Level=3")
        return 3, sub, triggers

    # Level 2: mild signals
    ms = _mild_signals(p)
    if ms:
        triggers.extend(ms)

        rp = risk10.get("risk_pct")
        pce_intermediate = (rp is not None and float(rp) >= PCE_INTERMEDIATE_CUT)

        # “Key clarifiers missing” used as convergence rule:
        # If only 1 mild signal but ApoB missing or Lp(a) missing => treat as converging (2B),
        # because stability is low until clarifiers are obtained.
        clarifiers_missing = (not p.has("apob")) or (not p.has("lpa"))

        converging = (len(ms) >= 2) or pce_intermediate or (len(ms) == 1 and clarifiers_missing)
        sub = "2B" if converging else "2A"

        add_trace(trace, "Level2_sublevel", sub, "Assigned 2A/2B")
        add_trace(trace, "Level_emerging_risk", ms[:6], "Level=2")
        return 2, sub, triggers

    # Level 1: default when some data present
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
# CAC decision support (AGGRESSIVE, GUIDELINE-DEFENSIBLE, NEVER "RECOMMENDED")
# -------------------------------------------------------------------
def cac_decision_support(
    p: Patient,
    plaque: Dict[str, Any],
    risk10: Dict[str, Any],
    level: int,
    trace: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Returns a CAC decision-support object that is:
      - Aggressive (shows CAC more often)
      - Guideline-defensible (risk-clarification, uncertainty, enhancers)
      - Never uses "recommended"
      - Suppresses when plaque already assessed (CAC known or ASCVD)
      - Includes a defensible tag + short rationale string
    """

    # ---- Suppress if plaque already assessed ----
    if plaque.get("plaque_present") in (True, False) or plaque.get("plaque_evidence") == "Clinical ASCVD" or p.get("ascvd") is True:
        add_trace(trace, "CAC_support_suppressed_known", plaque.get("plaque_evidence"), "Plaque already assessed")
        out = {
            "status": "suppressed",
            "message": "Do not obtain a CAC at this time.",
            "reasons": ["Plaque already assessed"],
            "tag": "CAC_SUPPRESSED_PLAQUE_KNOWN",
            "rationale": "Plaque status is already established; CAC would not add meaningful decision value.",
        }
        out["intents"] = {
            "therapy_decision": {"status": out["status"], "message": out["message"], "reasons": out["reasons"], "tag": out["tag"], "rationale": out["rationale"]},
            "classification": {"value": False, "message": None},
        }
        return out

    # ---- Helpers ----
    def _in_age_band() -> bool:
        if not p.has("age"):
            return False
        try:
            a = int(p.get("age"))
        except Exception:
            return False
        # Aggressive but still conventional CAC window
        return 40 <= a <= 75

    def _enhancer_count() -> int:
        enh = 0
        # "enhancers" in your own taxonomy (>=1 should often justify CAC if uncertain)
        if lpa_elevated_no_trace(p):
            enh += 1
        if p.get("fhx") is True:
            enh += 1
        if has_chronic_inflammatory_disease(p) or inflammation_flags(p):
            enh += 1
        if a1c_status(p) == "diabetes_range" or p.get("diabetes") is True:
            enh += 1
        if p.get("smoking") is True:
            enh += 1
        return enh

    def _discordant_or_uncertain(risk_pct: Optional[float]) -> bool:
        """
        Aggressive uncertainty detector:
        - Missing core calc (PCE unavailable)
        - PCE in buffer zone (near boundary)
        - Level 2B / 3A / 3B inherently preference-sensitive
        - Missing key clarifiers (ApoB/Lp(a)) → uncertainty high
        """
        if risk_pct is None:
            return True
        if pce_zone(risk_pct) == "buffer":
            return True
        if int(level or 0) in (2, 3):
            # Preference-sensitive levels are "uncertainty-friendly"
            return True
        # Missing clarifiers increases uncertainty, but should NOT block CAC
        if (not p.has("apob")) or (not p.has("lpa")):
            return True
        return False

    # ---- Core inputs ----
    rp = risk10.get("risk_pct")
    rp_f = float(rp) if rp is not None else None
    zone = pce_zone(rp_f)
    enh = _enhancer_count()
    in_age = _in_age_band()
    uncertain = _discordant_or_uncertain(rp_f)

    # ---- Classification intent (your prior logic; keep but broaden to 2–3) ----
    classification_value = False
    classification_message = None
    if int(level or 0) in (2, 3):
        ap = safe_float(p.get("apob")) if p.has("apob") else None
        ld = safe_float(p.get("ldl")) if p.has("ldl") else None

        # "classification" here = whether CAC would reclassify posture/intensity
        if p.get("diabetes") is True:
            classification_value = True
        if ap is not None and (110 <= ap <= 129):
            classification_value = True
        if ap is None and ld is not None and (160 <= ld <= 189):
            classification_value = True

        if classification_value:
            classification_message = (
                "CAC may be obtained to determine whether subclinical atherosclerosis is present and to personalize intensity/targets (Level 3 vs Level 4)."
            )

    # ---- Build defensible tag + rationale ----
    tag = None
    rationale = None

    # Highest-yield defensible lane: borderline/intermediate (or actionable/buffer) + uncertainty/enhancers
    if in_age and (zone in ("buffer", "actionable")) and (uncertain or enh >= 1):
        if zone == "actionable":
            tag = "CAC_RISK_CLARIFICATION_ACTIONABLE"
            rationale = "Plaque is unmeasured and decision-making is preference-sensitive; CAC can clarify risk and personalize treatment intensity."
        else:
            tag = "CAC_RISK_CLARIFICATION_BUFFER"
            rationale = f"ASCVD PCE is near a decision boundary ({PCE_BUFFER_MIN:.0f}–{PCE_BUFFER_MAX:.0f}%). CAC can reduce uncertainty when results would change timing or intensity."
        add_trace(trace, "CAC_support_optional_aggressive", {"risk": rp_f, "zone": zone, "enh": enh, "level": level}, tag)

        out = {
            "status": "optional",
            "message": "CAC is reasonable if the result would change treatment timing or intensity.",
            "reasons": [
                "Plaque unmeasured",
                f"PCE zone: {zone}",
                ("Risk enhancers present" if enh >= 1 else "Decision uncertainty present"),
            ],
            "tag": tag,
            "rationale": rationale,
            "classification_value": bool(classification_value),
            "classification_message": classification_message,
        }
        out["intents"] = {
            "therapy_decision": {"status": out["status"], "message": out["message"], "reasons": out["reasons"], "tag": out["tag"], "rationale": out["rationale"]},
            "classification": {"value": out["classification_value"], "message": out["classification_message"]},
        }
        return out

    # Selective low-risk lane (still optional): low PCE but enhancers/uncertainty
    if in_age and zone == "hard_no" and (enh >= 1 or uncertain):
        tag = "CAC_LOW_RISK_SELECTIVE_ENHANCERS"
        rationale = "Near-term estimated risk is low, but uncertainty/enhancers raise concern; CAC can be used selectively to guide intensity and support shared decision-making."
        add_trace(trace, "CAC_support_optional_low_risk_selective", {"risk": rp_f, "enh": enh, "level": level}, tag)

        out = {
            "status": "optional",
            "message": "CAC may be considered selectively if results would change management or improve adherence.",
            "reasons": [
                f"ASCVD PCE <{PCE_HARD_NO_MAX:.0f}% (low near-term risk)",
                ("Risk enhancers present" if enh >= 1 else "Decision uncertainty present"),
                "Plaque unmeasured",
            ],
            "tag": tag,
            "rationale": rationale,
            "classification_value": bool(classification_value),
            "classification_message": classification_message,
        }
        out["intents"] = {
            "therapy_decision": {"status": out["status"], "message": out["message"], "reasons": out["reasons"], "tag": out["tag"], "rationale": out["rationale"]},
            "classification": {"value": out["classification_value"], "message": out["classification_message"]},
        }
        return out

    # High risk lane: suppress (incremental value low, proceed with treatment)
    if zone == "high":
        add_trace(trace, "CAC_support_suppressed_high_risk", rp_f, "High risk → proceed without CAC")
        out = {
            "status": "suppressed",
            "message": "Do not obtain a CAC at this time.",
            "reasons": [f"ASCVD PCE ≥{PCE_ACTION_MAX:.0f}% (management proceeds without CAC)"],
            "tag": "CAC_SUPPRESSED_HIGH_RISK",
            "rationale": "At high near-term risk, CAC has low incremental decision value because treatment proceeds regardless.",
            "classification_value": bool(classification_value),
            "classification_message": classification_message,
        }
        out["intents"] = {
            "therapy_decision": {"status": out["status"], "message": out["message"], "reasons": out["reasons"], "tag": out["tag"], "rationale": out["rationale"]},
            "classification": {"value": out["classification_value"], "message": out["classification_message"]},
        }
        return out

    # Not in age band or not a case where CAC adds value → suppress
    add_trace(trace, "CAC_support_suppressed_default", {"risk": rp_f, "zone": zone, "level": level}, "Default suppression")
    out = {
        "status": "suppressed",
        "message": "Do not obtain a CAC at this time.",
        "reasons": ["Low incremental value in current posture"],
        "tag": "CAC_SUPPRESSED_DEFAULT",
        "rationale": "Current information does not support CAC as a decision-changing test in this context.",
        "classification_value": bool(classification_value),
        "classification_message": classification_message,
    }
    out["intents"] = {
        "therapy_decision": {"status": out["status"], "message": out["message"], "reasons": out["reasons"], "tag": out["tag"], "rationale": out["rationale"]},
        "classification": {"value": out["classification_value"], "message": out["classification_message"]},
    }
    return out

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
# Plan sentence (kept for UI/backward compatibility; tightened)
# -------------------------------------------------------------------
def plan_sentence(
    level: int,
    sublevel: Optional[str],
    therapy_on: bool,
    at_tgt: bool,
    risk10: Dict[str, Any],
    plaque: Dict[str, Any],
) -> str:
    zone = pce_zone(risk10.get("risk_pct"))

    if level == 1:
        return "Routine follow-up. No escalation is required."

    if level == 2:
        if zone == "buffer":
            return "Data completion first. Reassess. No escalation is required at this time."
        return "Data completion and reassessment."

    if level == 3:
        if therapy_on and at_tgt:
            return "Continue current lipid-lowering intensity."
        if therapy_on and not at_tgt:
            return "Optimize lipid-lowering intensity to achieve targets."
        if sublevel == "3B":
            return "Initiate lipid-lowering therapy unless strong reasons to defer."
        return "Lipid-lowering therapy is reasonable; timing is preference-sensitive."

    if level == 4:
        # CAC 1–99 = subclinical disease; intensity is individualized, not reflex high-intensity
        if therapy_on and at_tgt:
            return "Continue lipid-lowering therapy at the current intensity."
        if therapy_on and not at_tgt:
            return "Optimize lipid-lowering intensity to achieve targets."
        return "Lipid-lowering therapy appropriate; intensity individualized based on targets and risk profile."

    if therapy_on and at_tgt:
        return "Continue secondary-prevention intensity lipid lowering."
    return "Secondary-prevention intensity lipid lowering is indicated; add-ons may be needed."

# -------------------------------------------------------------------
# Canonical action language helpers (single source of truth)
# -------------------------------------------------------------------
def _action_line(title: str, verb_phrase: str, detail: Optional[str] = None) -> List[str]:
    """
    Returns 1–2 lines in a clinician-facing 'Action' style.
    Used by compose_actions() only.
    """
    lines = [f"{title}: {verb_phrase}."]
    if detail:
        lines.append(detail.strip())
    return lines


def canonical_cac_copy(
    p: Patient,
    plaque: Dict[str, Any],
    cac_support: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Canonical coronary calcium language used by BOTH UI and EMR.

    Design rules:
    - Never uses: optional / deferred / consider / tie-breaker
    - Treats CAC as a disease-finding test
    - Explicitly supports referral when burden is high
    - Ignores cac_support.status wording entirely
    """

    # CAC already assessed (including ASCVD)
    if p.get("ascvd") is True or plaque.get("plaque_present") in (True, False):
        cac_val = plaque.get("cac_value")

        if isinstance(cac_val, int):
            headline = f"Coronary calcium: Already assessed (CAC {cac_val})."
        else:
            headline = "Coronary calcium: Already assessed."

        referral = None
        if isinstance(cac_val, int):
            if cac_val >= 1000:
                referral = (
                    "Cardiology referral: Indicated for further evaluation "
                    "given marked coronary calcium burden."
                )
            elif cac_val >= 400:
                referral = (
                    "Cardiology referral: Appropriate for further evaluation "
                    "given high coronary calcium burden."
                )

        return {
            "status": "assessed",
            "headline": headline,
            "detail": None,
            "referral": referral,
        }

    # CAC not yet obtained
    return {
        "status": "unmeasured",
        "headline": "Coronary calcium: Reasonable to obtain.",
        "detail": (
            "Useful to define disease burden or if results would change treatment "
            "intensity or downstream evaluation."
        ),
        "referral": None,
    }


def canonical_aspirin_copy(asp: Dict[str, Any]) -> Dict[str, Any]:
    """
    Canonical aspirin language used by BOTH UI and EMR.

    Keeps wording short, consistent, and non-hedged.
    """
    raw = str((asp or {}).get("status") or "").strip().lower()

    if raw.startswith("secondary prevention"):
        return {
            "headline": "Aspirin: Indicated (secondary prevention).",
            "detail": None,
        }

    if raw.startswith("avoid"):
        return {
            "headline": "Aspirin: Avoid.",
            "detail": None,
        }

    if raw.startswith("consider"):
        return {
            "headline": "Aspirin: Reasonable (shared decision).",
            "detail": None,
        }

    if raw in ("", "not assessed"):
        return {
            "headline": "Aspirin: Not assessed.",
            "detail": None,
        }

    return {
        "headline": "Aspirin: Not indicated.",
        "detail": None,
    }
def canonical_ckm_copy(ckm: Dict[str, Any], decision_conf: str) -> Optional[Dict[str, Any]]:
    """
    Canonical CKM context language used by BOTH UI and EMR.
    Display-first: does NOT direct therapy.
    Returns None when not worth surfacing.
    """
    if str(decision_conf or "").strip().lower() not in ("high", "moderate"):
        return None

    if not ckm:
        return None

    contributors: List[str] = []
    if ckm.get("ckd_present"):
        contributors.append("kidney factors")
    if ckm.get("metabolic_acceleration"):
        contributors.append("metabolic factors")
    if ckm.get("obesity_present"):
        contributors.append("obesity-related risk")
    if ckm.get("hypertension_burden"):
        contributors.append("blood pressure burden")

    if not contributors:
        return None

    headline = (
        "CKM context: Cardiovascular risk may be influenced by kidney and/or metabolic factors "
        "that can accelerate disease progression independent of plaque burden."
    )
    detail = "Contributors: " + ", ".join(contributors) + "."

    return {
        "headline": headline,
        "detail": detail,
        "contributors": contributors,
    }


# -------------------------------------------------------------------
# Authoritative action composer (WHY → WHAT)
# -------------------------------------------------------------------
APOB_INITIATE_CUT = 110.0

def compose_actions(p: Patient, out: Dict[str, Any]) -> List[str]:
    """
    Canonical action outputs (WHY → WHAT).
    CAC language is NOT emitted here to avoid duplication/contradiction.
    CAC is rendered from insights["cac_copy"] in both UI and EMR.
    """
    actions: List[str] = []

    lvl = out.get("levels") or {}
    evidence = (lvl.get("evidence") or {})
    targets = out.get("targets") or {}
    risk10 = out.get("ascvdPce10yRisk") or {}
    zone = pce_zone(risk10.get("risk_pct"))

    therapy_on = on_lipid_therapy(p)
    at_tgt = at_target(p, targets)

    # -----------------------------
    # 1) ASCVD / plaque established
    # -----------------------------
    if p.get("ascvd") is True:
        actions += _action_line("Lipid-lowering therapy", "Indicated (secondary-prevention intensity)")
        return actions

    cac_val = evidence.get("cac_value", None)

    # Plaque assessed: CAC strata should drive posture before "missing clarifiers" logic.
    if isinstance(cac_val, int):
        if cac_val >= 100:
            actions += _action_line("Lipid-lowering therapy", "Appropriate (target-driven; plaque present)")
            if therapy_on and not at_tgt:
                actions += _action_line(
                    "Therapy optimization",
                    "Appropriate",
                    "Above target on current therapy → assess tolerance/adherence and intensify to achieve targets.",
                )
            return actions

        # CAC 1–99: guideline-aligned, non-mandatory intensity language
        if 1 <= cac_val <= 99:
            actions += _action_line(
                "Lipid-lowering therapy",
                "Appropriate",
                "Intensity individualized based on targets and risk profile.",
            )
            if therapy_on and not at_tgt:
                actions += _action_line(
                    "Therapy optimization",
                    "Appropriate",
                    "Above target on current therapy → assess tolerance/adherence and optimize intensity.",
                )
            return actions

        # CAC=0: do not force therapy; proceed to other biology/risk logic
        if cac_val == 0:
            pass

    # -----------------------------
    # 2) Missing key clarifiers (keep concise)
    # -----------------------------
    missing: List[str] = []
    if not p.has("apob"):
        missing.append("ApoB")
    if not p.has("lpa"):
        missing.append("Lp(a)")

    if missing:
        actions += _action_line(
            "Data completion",
            "Reasonable",
            f"{', '.join(missing)} missing → obtain to define atherogenic burden / inherited risk.",
        )
        # NOTE: do not output CAC text here (handled by insights['cac_copy'])
        return actions

    # -----------------------------
    # 3) Atherogenic burden triggers
    # -----------------------------
    apob = safe_float(p.get("apob")) if p.has("apob") else None
    ldl = safe_float(p.get("ldl")) if p.has("ldl") else None

    if apob is not None and apob >= APOB_INITIATE_CUT:
        if not therapy_on:
            actions += _action_line(
                "Lipid-lowering therapy",
                "Appropriate",
                f"ApoB {int(apob)} mg/dL suggests actionable atherogenic burden.",
            )
        elif not at_tgt:
            actions += _action_line(
                "Therapy optimization",
                "Appropriate",
                f"ApoB {int(apob)} mg/dL on therapy → intensify to achieve targets.",
            )
        else:
            actions += _action_line(
                "Lipid-lowering therapy",
                "Appropriate",
                "Targets achieved → continue current therapy.",
            )
        return actions

    if ldl is not None and ldl >= 190:
        if not therapy_on:
            actions += _action_line(
                "Lipid-lowering therapy",
                "Appropriate",
                f"LDL-C {int(ldl)} mg/dL (severe hypercholesterolemia range).",
            )
        elif not at_tgt:
            actions += _action_line(
                "Therapy optimization",
                "Appropriate",
                f"LDL-C {int(ldl)} mg/dL on therapy → intensify to achieve targets.",
            )
        else:
            actions += _action_line(
                "Lipid-lowering therapy",
                "Appropriate",
                "Targets achieved → continue current therapy.",
            )
        return actions

    # -----------------------------
    # 4) On therapy but not at target
    # -----------------------------
    if therapy_on and not at_tgt:
        actions += _action_line(
            "Therapy optimization",
            "Appropriate",
            "Above target on current therapy → assess tolerance/adherence and optimize intensity.",
        )
        return actions

    # -----------------------------
    # 5) Low near-term risk with no dominant drivers
    # -----------------------------
    rp = risk10.get("risk_pct")
    if zone == "hard_no":
        actions += _action_line(
            "Lipid-lowering therapy",
            "Not required at this time",
            f"ASCVD PCE {rp}% with no dominant biologic drivers.",
        )
        return actions

    # -----------------------------
    # 6) Default
    # -----------------------------
    actions += _action_line(
        "Management",
        "Not required at this time",
        "No immediate escalation required; reassess with interval follow-up.",
    )
    return actions

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
    asp_copy = canonical_aspirin_copy(asp)

    drivers_all = ranked_drivers(p, plaque, trace)
    drivers_top = drivers_all[:3]
    ckm = ckm_context(p)
    ckm_copy = canonical_ckm_copy_stage(p, ckm, decision_conf=dec_conf)
    ckd_copy = canonical_ckd_copy(p, decision_conf=dec_conf)


    # ------------------------------------------------------------
    # Secondary Insight: lifestyle vs biology driver pattern
    # ------------------------------------------------------------
    risk_driver = classify_risk_driver(
        p=p,
        plaque=plaque,
        rss=rss,
        risk10=risk10,
        level=level,
        sublevel=sublevel,
        decision_confidence=dec_conf,
        trace=trace,
    )

    plan = plan_sentence(level, sublevel, therapy_on, at_tgt, risk10, plaque)

    # NEW: dominantAction flag (consumed by app.py)
    dominant_action = False

    # Dominant action should mean "treatment-forward today", not merely "plaque assessed".
    if p.get("ascvd") is True:
        dominant_action = True
    elif int(level or 0) >= 4:
        dominant_action = True
    elif (stab_band or "").strip().lower() == "high" and "dominant" in (stab_note or "").strip().lower():
        dominant_action = True

    # ---- FIX: label builder (no posture dependency) ----
    # Uses management label when sublevels exist (2A/2B/3A/3B).
    # Falls back safely if label helper was renamed elsewhere.
    try:
        label_txt = management_label(level, sublevel=sublevel)  # preferred
    except Exception:
        try:
            label_txt = posture_label(level, sublevel=sublevel)  # backward-compat
        except Exception:
            # absolute fallback (never crash)
            base = LEVEL_LABELS.get(level, f"Level {level}")
            if sublevel and level in (2, 3):
                parts = base.split("—", 1)
                label_txt = f"Level {sublevel} — {parts[1].strip()}" if len(parts) == 2 else base
            else:
                label_txt = base

    levels_obj = {
        "postureLevel": level,          # kept for backward compatibility
        "managementLevel": level,
        "sublevel": sublevel,
        "label": label_txt,
        "meaning": LEVEL_LABELS.get(level, f"Level {level}"),
        "triggers": sorted(set(level_triggers or [])),

        "managementPlan": plan,
        "defaultPosture": plan,         # kept for backward compatibility

        "decisionConfidence": dec_conf,
        "decisionStability": stab_band,
        "decisionStabilityNote": stab_note,

        "plaqueEvidence": plaque.get("plaque_evidence", "—"),
        "plaqueBurden": plaque.get("plaque_burden", "—"),

        # NEW: aligns with app.py recommended_action_line()
        "dominantAction": bool(dominant_action),

        "evidence": {
            "clinical_ascvd": bool(p.get("ascvd") is True),
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
    elif str(plaque.get("plaque_evidence", "")).startswith("Unknown"):
        disease_burden = "Unknown (CAC not available)"

    _clar = (cac_support.get("message") or "").strip()
    _cclass = (cac_support.get("classification_message") or "").strip()
    if _cclass:
        _clar = (_clar + " " + _cclass).strip()

    cac_copy = canonical_cac_copy(p, plaque, cac_support)
    # CKM context (display-first; does not change level/actions)
    ckm = ckm_context(p)
    ckm_copy = canonical_ckm_copy(ckm, decision_conf=dec_conf)

    insights = {
        "cac_decision_support": cac_support,  # keep for Details/Debug
        "structural_clarification": _clar if _clar else None,

        # Canonical CAC + aspirin language (UI + EMR should use this)
        "cac_copy": cac_copy,
        "aspirin_copy": asp_copy,

        # CKM context (UI + EMR can use this)
        "ckm_context": ckm,
        "ckm_copy": ckm_copy,
        "ckd_copy": ckd_copy,

        # Secondary insight (engine-gated)
        "risk_driver_pattern": risk_driver,

        "phenotype_label": None,
        "phenotype_definition": None,

        "decision_stability": stab_band,
        "decision_stability_note": stab_note,
        "decision_robustness": stab_band,
        "decision_robustness_note": stab_note,

        "pce_zone": pce_zone(risk10.get("risk_pct")),
    }

    # NEW: teachable moment — PREVENT vs PCE divergence (engine-owned)
    insights["risk_model_mismatch"] = risk_model_mismatch(risk10, prevent10)

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

        "nextActions": [],

        "escGoals": esc_numeric_goals(
            level,
            clinical_ascvd=bool(p.get("ascvd") is True),
        ),

        "aspirin": asp,
        "anchors": anchors,
        "lpaInfo": lpa_info(p, trace),

        "insights": insights,
        "trace": trace,
        "trajectoryNote": levels_obj.get("trajectoryNote"),
    }

    out["nextActions"] = compose_actions(p, out)

    add_trace(trace, "Engine_end", VERSION["levels"], "Evaluation complete")
    return out


# -------------------------------------------------------------------
# Canonical EMR output (locked style) — direct: WHY → WHAT
# -------------------------------------------------------------------
# -------------------------------------------------------------------
# FINAL-POLISH LAYER (engine-owned, single source of truth)
# -------------------------------------------------------------------
def recommended_action_line(out: Dict[str, Any]) -> str:
    """
    Single-sentence, decision-today recommended action.
    - No next-step tasks (CAC/labs/reassess)
    - No aspirin mention (handled elsewhere)
    - Uses dominantAction when present
    """
    lvl = out.get("levels") or {}
    level = int(lvl.get("managementLevel") or lvl.get("postureLevel") or 0)
    sub = (lvl.get("sublevel") or None)

    dominant = bool(lvl.get("dominantAction") is True)

    # Prefer the managementPlan sentence if it is "decision today" (it often is).
    plan = str(lvl.get("managementPlan") or lvl.get("defaultPosture") or "").strip()

    # Take first sentence-ish chunk
    s = " ".join(plan.split())
    if "." in s:
        s = s.split(".", 1)[0].strip()
    if s and not s.endswith("."):
        s += "."

    # Hard forbid next-step content for the single action line
    forbidden = ("reassess", "follow", "obtain", "order", "cac", "calcium", "aspirin", "labs", "repeat", "check")
    if not s or any(w in s.lower() for w in forbidden):
        # Safe fallbacks by posture
        if level >= 5:
            return "Continue secondary-prevention intensity lipid-lowering."
        if level == 4:
            return "Lipid-lowering therapy appropriate; intensity individualized based on targets and risk profile."
        if dominant and level >= 3:
            return "Initiate treatment now."
        if level == 3 and sub == "3B":
            return "Initiate lipid-lowering therapy."
        if level == 3:
            return "Treatment is reasonable."
        if level <= 2:
            return "No escalation today."
        return "—"

    # Optional: if dominant, avoid hedgy phrasing
    if dominant and ("reasonable" in s.lower() or "preference" in s.lower()):
        return "Initiate treatment now."

    return s

def _normalize_space(s: str) -> str:
    return " ".join((s or "").strip().split())

def _dedup_lines(lines: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in lines:
        t = _normalize_space(x).lower()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(x)
    return out

def _pick_primary_action(next_actions: List[str], dominant: bool) -> Tuple[Optional[str], List[str]]:
    """
    Returns (primary_action_line, remaining_action_lines)

    Strategy:
    - If dominantAction=True: prefer the first "Lipid-lowering therapy:" / "Therapy optimization:" / "Treatment escalation:" line
    - Else: prefer the first non-defensive line (avoid stacking "not required/no escalation" repeats)
    """
    if not next_actions:
        return None, []

    lines = [str(x).strip() for x in next_actions if str(x).strip()]
    if not lines:
        return None, []

    # Candidates by clinical salience
    preferred_prefixes = (
        "Lipid-lowering therapy:",
        "Therapy optimization:",
        "Treatment escalation:",
        "Management:",
        "Data completion:",
        "Reassessment:",
    )

    def is_preferred(s: str) -> bool:
        return any(s.startswith(p) for p in preferred_prefixes)

    if dominant:
        for i, s in enumerate(lines):
            if is_preferred(s):
                primary = s
                rest = lines[:i] + lines[i+1:]
                return primary, rest

    # Non-dominant: choose first preferred; otherwise first line.
    for i, s in enumerate(lines):
        if is_preferred(s):
            primary = s
            rest = lines[:i] + lines[i+1:]
            return primary, rest

    return lines[0], lines[1:]


def _action_to_plan_bullets(primary: Optional[str], rest: List[str]) -> List[str]:
    """
    Converts nextActions (already canonical) into a minimal, non-redundant Plan section.
    Removes repeated negations and collapses boilerplate.
    """
    bullets: List[str] = []

    # Helper: strip trailing period; keep colon formatting intact
    def tidy(s: str) -> str:
        s = _normalize_space(s)
        if s.endswith("."):
            s = s[:-1]
        return s

    primary_t = tidy(primary) if primary else None
    rest_t = [tidy(x) for x in rest if tidy(x)]

    # Drop redundant "no escalation / not required" echoes if primary already conveys it
    redundant_starts = (
        "No escalation",
        "No immediate escalation",
        "Management: Not required at this time",
        "Management: Not required",
        "Lipid-lowering therapy: Not required at this time",
    )

    def is_redundant(s: str) -> bool:
        low = s.lower()
        if any(s.startswith(r) for r in redundant_starts):
            return True
        # also catch “No immediate escalation required; reassess …” if we already include reassessment
        if "no immediate escalation" in low:
            return True
        return False

    # Always include primary (if present)
    if primary_t:
        bullets.append(primary_t)

    # Include up to 2 additional lines that add *new* info
    keep: List[str] = []
    for s in rest_t:
        if is_redundant(s):
            continue
        keep.append(s)
        if len(keep) >= 2:
            break

    bullets.extend(keep)
    return _dedup_lines([f"- {b}" for b in bullets])


# -------------------------------------------------------------------
# CANONICAL CLINICAL REPORT (polished; single source of truth)
# -------------------------------------------------------------------
def render_quick_text(p: Patient, out: Dict[str, Any]) -> str:
    lvl = out.get("levels") or {}
    rs = out.get("riskSignal") or {}
    risk10 = out.get("ascvdPce10yRisk") or out.get("pooledCohortEquations10yAscvdRisk") or {}
    prev = out.get("prevent10") or {}
    anchors = out.get("anchors") or {}
    insights = out.get("insights") or {}

    level = int(lvl.get("managementLevel") or lvl.get("postureLevel") or 0)
    sub = (lvl.get("sublevel") or None)
    label = (lvl.get("label") or "").strip()
    label_fallback = LEVEL_LABELS.get(level, f"Level {level}")
    level_line = f"{label}" if label else label_fallback

    # Plaque lines (use your explicit evidence/burden)
    plaque_evidence = (lvl.get("plaqueEvidence") or "—").strip()
    plaque_burden = (lvl.get("plaqueBurden") or "—").strip()

    # Decision lines
    dec_conf = (lvl.get("decisionConfidence") or "—").strip()
    stab = (lvl.get("decisionStability") or "—").strip()
    stab_note = (lvl.get("decisionStabilityNote") or "").strip()
    stab_line = stab + (f" — {stab_note}" if stab_note else "")

    # Drivers (already deterministic + explicit in your assign_level logic)
    drivers = (out.get("drivers") or lvl.get("triggers") or [])[:3]
    drivers = [str(d).strip() for d in drivers if str(d).strip()]

    # Metrics
    rss_score = rs.get("score", "—")
    rss_band = rs.get("band", "—")
    pce_pct = risk10.get("risk_pct", None)
    pce_cat = risk10.get("category", "—")
    p_total = prev.get("total_cvd_10y_pct", None)
    p_ascvd = prev.get("ascvd_10y_pct", None)

    # Targets
    targets = out.get("targets") or {}
    targets_label = "Targets (if treated)"

    # Aspirin / CAC canonical copy (single source of truth already exists)
    asp_copy = insights.get("aspirin_copy") or {}
    asp_head = _normalize_space(str(asp_copy.get("headline") or "Aspirin: —"))

    cac_copy = insights.get("cac_copy") or {}
    cac_head = _normalize_space(str(cac_copy.get("headline") or ""))

    # Build Plan from nextActions with dominance + dedup
    dominant = bool(lvl.get("dominantAction") is True)
    primary, rest = _pick_primary_action(out.get("nextActions") or [], dominant=dominant)
    plan_bullets = _action_to_plan_bullets(primary, rest)

    # --- NEW: CKM + CKD inline (v4 adapter places these in insights) ---
    ins = insights or {}

    ckm_head = ""
    try:
        ckm_head = str((ins.get("ckm_copy") or {}).get("headline") or "").strip()
    except Exception:
        ckm_head = ""

    ckd_head = ""
    try:
        ckd_head = str((ins.get("ckd_copy") or {}).get("headline") or "").strip()
    except Exception:
        ckd_head = ""

    # --- Report assembly (clinician voice, low redundancy) ---
    lines: List[str] = []
    lines.append("RISK CONTINUUM — CLINICAL REPORT")
    lines.append("-" * 60)
    lines.append(f"Level: {level_line}")

    # Inline CKM/CKD directly under Level (when present)
    if ckm_head or ckd_head:
        if ckm_head and ckd_head:
            lines.append(f"{ckm_head} | {ckd_head}")
        else:
            lines.append(ckm_head or ckd_head)

    lines.append(f"Plaque: {plaque_evidence} | Burden: {plaque_burden}")
    lines.append(f"Confidence: {dec_conf} | Stability: {stab_line}")
    lines.append("")

    # If CKM is surfaced, suppress "Why (top drivers)" to avoid redundancy.
    if (not ckm_head) and drivers:
        lines.append("Why (top drivers):")
        for d in drivers:
            lines.append(f"- {d}")
        lines.append("")

    lines.append("Risk estimates:")
    lines.append(f"- RSS: {rss_score}/100 ({rss_band})")
    if pce_pct is not None:
        lines.append(f"- ASCVD PCE (10y): {pce_pct}% ({pce_cat})")
    else:
        lines.append("- ASCVD PCE (10y): —")
    lines.append(
        f"- PREVENT (10y): Total CVD {p_total if p_total is not None else '—'}% | "
        f"ASCVD {p_ascvd if p_ascvd is not None else '—'}%"
    )
    lines.append("")

    # Targets (if treated)
    if isinstance(targets, dict) and targets:
        t_parts: List[str] = []
        if "ldl" in targets:
            t_parts.append(f"LDL-C <{int(targets['ldl'])} mg/dL")
        if "apob" in targets:
            t_parts.append(f"ApoB <{int(targets['apob'])} mg/dL")
        if t_parts:
            lines.append(f"{targets_label}:")
            for t in t_parts:
                lines.append(f"- {t}")
            lines.append("")

    # Plan
    lines.append("Plan:")
    lines.extend(plan_bullets)

    # Aspirin + CAC (canonical)
    if asp_head:
        lines.append(f"- {asp_head}")

    # CAC: keep headline only (avoid filler)
    if cac_head:
        lines.append(f"- {cac_head}")

    # Context anchors
    near = (anchors.get("nearTerm") or {}).get("summary", "—")
    life = (anchors.get("lifetime") or {}).get("summary", "—")
    lines.append("")
    lines.append(f"Context: Near-term: {near} | Lifetime: {life}")

    return "\n".join(_dedup_lines(lines))


































