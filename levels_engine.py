# levels_engine.py
# LEVELS v1.3 — Clinician-technical, high-yield output (no redundant therapy ladder)
# Includes: Levels 0–4, Risk Signal Score, Pooled Cohort Equations (10-year ASCVD risk),
# A1c/prediabetes + inflammatory states, aspirin logic, targets, discordance insights.

import math
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

VERSION = {
    "levels": "v1.3",
    "risk_signal": "RSS v1.0",
    "pce": "Pooled Cohort Equations (ACC/AHA 2013; Race other->non-Black)",
    "aspirin": "Aspirin v1.0 (CAC≥100 OR 10y risk≥10%, age 40–69, low bleed risk)"
}

@dataclass
class Patient:
    data: Dict[str, Any]
    def get(self, k, d=None): return self.data.get(k, d)
    def has(self, k): return k in self.data and self.data[k] is not None


# ----------------------------
# A1c / inflammation helpers
# ----------------------------

def a1c_status(p: Patient) -> Optional[str]:
    if not p.has("a1c"):
        return None
    try:
        a1c = float(p.get("a1c"))
    except:
        return None
    if a1c < 5.7: return "normal"
    if a1c < 6.5: return "prediabetes"
    return "diabetes_range"

def has_chronic_inflammatory_disease(p: Patient) -> bool:
    return any(p.get(k) is True for k in ["ra", "psoriasis", "sle", "ibd", "hiv"])

def inflammation_flags(p: Patient) -> List[str]:
    flags = []
    if p.has("hscrp"):
        try:
            if float(p.get("hscrp")) >= 2:
                flags.append("hsCRP>=2")
        except:
            pass
    if p.get("ra") is True: flags.append("RA")
    if p.get("psoriasis") is True: flags.append("Psoriasis")
    if p.get("sle") is True: flags.append("SLE")
    if p.get("ibd") is True: flags.append("IBD")
    if p.get("hiv") is True: flags.append("HIV")
    if p.get("osa") is True: flags.append("OSA")
    if p.get("nafld") is True: flags.append("NAFLD/MASLD")
    return flags

def lpa_elevated(p: Patient) -> bool:
    if not p.has("lpa"): return False
    v = float(p.get("lpa", 0))
    unit = str(p.get("lpa_unit", "")).lower()
    if "mg" in unit: return v >= 50
    return v >= 125


# ----------------------------
# Risk Signal Score (0–100)
# ----------------------------

def _clamp(x: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, x))

def _rss_band(score: int) -> str:
    if score <= 19: return "Low"
    if score <= 39: return "Mild"
    if score <= 59: return "Moderate"
    if score <= 79: return "High"
    return "Very high"

def risk_signal_score(p: Patient) -> Dict[str, Any]:
    # Substrate (0–55): ASCVD dominates, then CAC bands
    substrate = 0
    if p.get("ascvd") is True:
        substrate = 55
    elif p.has("cac"):
        cac = int(p.get("cac", 0))
        if cac == 0: substrate = 0
        elif 1 <= cac <= 9: substrate = 20
        elif 10 <= cac <= 99: substrate = 30
        elif 100 <= cac <= 399: substrate = 45
        else: substrate = 55

    # Atherogenic (0–25): prefer ApoB else LDL
    athero = 0
    if p.has("apob"):
        apob = float(p.get("apob", 0))
        if apob < 80: athero = 0
        elif apob <= 99: athero = 8
        elif apob <= 119: athero = 15
        elif apob <= 149: athero = 20
        else: athero = 25
    elif p.has("ldl"):
        ldl = float(p.get("ldl", 0))
        if ldl < 100: athero = 0
        elif ldl <= 129: athero = 5
        elif ldl <= 159: athero = 10
        elif ldl <= 189: athero = 15
        else: athero = 20

    # Genetics (0–15): Lp(a) + FHx capped
    genetics = 0
    if p.has("lpa"):
        unit = str(p.get("lpa_unit", "")).lower()
        lpa = float(p.get("lpa", 0))
        if "mg" in unit:
            if lpa >= 100: genetics += 12
            elif lpa >= 50: genetics += 8
        else:
            if lpa >= 250: genetics += 12
            elif lpa >= 125: genetics += 8
    if p.get("fhx") is True:
        genetics += 5
    genetics = min(genetics, 15)

    # Inflammation (0–10): hsCRP>=10 downweighted (+3), chronic inflammatory disease +5
    inflammation = 0
    if p.has("hscrp"):
        h = float(p.get("hscrp", 0))
        if h < 2: inflammation += 0
        elif h < 10: inflammation += 5
        else: inflammation += 3
    if has_chronic_inflammatory_disease(p):
        inflammation += 5
    inflammation = min(inflammation, 10)

    # Metabolic (0–10): diabetes +6, smoking +4, prediabetes +2
    metabolic = 0
    if p.get("diabetes") is True: metabolic += 6
    if p.get("smoking") is True: metabolic += 4
    if a1c_status(p) == "prediabetes": metabolic += 2
    metabolic = min(metabolic, 10)

    total = _clamp(substrate + athero + genetics + inflammation + metabolic)
    return {
        "score": total,
        "band": _rss_band(total),
        "breakdown": {
            "Atherosclerotic disease burden": substrate,
            "Atherogenic burden": athero,
            "Genetic acceleration": genetics,
            "Inflammatory acceleration": inflammation,
            "Metabolic acceleration": metabolic,
        },
        "note": "Not an event probability (biologic + plaque signal).",
    }


# ----------------------------
# Pooled Cohort Equations (PCE) 10-year ASCVD risk
# Race: Other -> non-Black coefficients
# ----------------------------

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

def pce_10y(p: Patient) -> Dict[str, Any]:
    req = ["age", "sex", "race", "tc", "hdl", "sbp", "bp_treated", "smoking", "diabetes"]
    missing = [k for k in req if not p.has(k)]
    if missing:
        return {"risk_pct": None, "missing": missing}

    age = int(p.get("age"))
    if age < 40 or age > 79:
        return {"risk_pct": None, "missing": [], "notes": "Valid for ages 40–79."}

    sex = str(p.get("sex", "")).lower()
    sex_key = "male" if sex in ("m", "male") else "female"

    race = str(p.get("race", "")).lower()
    race_key = "black" if race in ("black", "african american", "african-american") else "white"

    c = PCE[(race_key, sex_key)]
    tc = float(p.get("tc"))
    hdl = float(p.get("hdl"))
    sbp = float(p.get("sbp"))
    treated = bool(p.get("bp_treated"))
    smoker = bool(p.get("smoking"))
    dm = bool(p.get("diabetes"))

    ln_age = math.log(age)
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

    s0 = c["s0"]
    mean = c["mean"]
    risk = 1 - (s0 ** math.exp(lp - mean))
    risk = max(0.0, min(1.0, risk))
    risk_pct = round(risk * 100, 1)

    if risk_pct < 5:
        cat = "Low (<5%)"
    elif risk_pct < 7.5:
        cat = "Borderline (5–7.4%)"
    elif risk_pct < 20:
        cat = "Intermediate (7.5–19.9%)"
    else:
        cat = "High (≥20%)"

    return {"risk_pct": risk_pct, "category": cat, "notes": "Pooled Cohort Equations 10-year ASCVD risk (population estimate)."}


# ----------------------------
# Aspirin module (C)
# ----------------------------

def aspirin_advice(p: Patient, pce: Dict[str, Any]) -> Dict[str, Any]:
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
        if bleed_flags:
            return {"status": "Secondary prevention: typically indicated, but bleeding risk flags present", "rationale": bleed_flags}
        return {"status": "Secondary prevention: typically indicated if no contraindication", "rationale": ["ASCVD present"]}

    if age is None:
        return {"status": "Not assessed", "rationale": ["Age missing"]}

    if age < 40 or age >= 70:
        return {"status": "Avoid (primary prevention)", "rationale": [f"Age {age} (bleeding risk likely outweighs benefit)"]}

    if bleed_flags:
        return {"status": "Avoid (primary prevention)", "rationale": ["High bleeding risk: " + "; ".join(bleed_flags)]}

    pce_risk = pce.get("risk_pct")
    pce_ok = (pce_risk is not None and pce_risk >= 10.0)
    cac_ok = (cac is not None and cac >= 100)

    if cac_ok or pce_ok:
        reasons = []
        if cac_ok: reasons.append("CAC ≥100")
        if pce_ok: reasons.append(f"Pooled Cohort Equations 10-year risk ≥10% ({pce_risk}%)")
        return {"status": "Consider low-dose aspirin (shared decision)", "rationale": reasons + ["Bleeding risk low by available flags"]}

    return {"status": "Usually avoid / individualize", "rationale": ["Primary prevention benefit likely small; prioritize risk factor optimization"]}


# ----------------------------
# Levels banding + targets + customized next steps
# ----------------------------

def levels_band(p: Patient) -> Dict[str, Any]:
    triggers = []
    level = 0

    if p.get("ascvd") is True:
        level = 4; triggers.append("ASCVD")

    if p.has("cac") and int(p.get("cac", 0)) >= 100:
        level = max(level, 4); triggers.append("CAC>=100")

    if p.has("cac") and int(p.get("cac", 0)) > 0:
        level = max(level, 3); triggers.append("CAC>0")

    if level < 3:
        if p.has("apob") and float(p.get("apob", 0)) >= 100:
            level = max(level, 2); triggers.append("ApoB>=100")
        if p.has("ldl") and float(p.get("ldl", 0)) >= 130:
            level = max(level, 2); triggers.append("LDL>=130")
        if lpa_elevated(p):
            level = max(level, 2); triggers.append("Lp(a) elevated")
        if p.get("fhx") is True:
            level = max(level, 2); triggers.append("FHx_premature")
        if a1c_status(p) == "prediabetes":
            triggers.append("Prediabetes_A1c")
        if has_chronic_inflammatory_disease(p):
            triggers.append("Chronic_inflammation")
        if inflammation_flags(p):
            triggers.append("Inflammation_present")

    if level == 0 and p.data:
        level = 1; triggers.append("Any_risk_signal_present")

    labels = {
        0: "Level 0 — No atherosclerotic risk detected",
        1: "Level 1 — Mild biologic risk (no disease)",
        2: "Level 2 — High biologic risk (disease not yet proven)",
        3: "Level 3 — Subclinical atherosclerotic disease",
        4: "Level 4 — Advanced / clinical atherosclerotic disease",
    }
    return {"level": level, "label": labels[level], "triggers": sorted(set(triggers))}

def _targets(level: int, enh_count: int) -> Dict[str, int]:
    if level <= 1:
        return {"apob_goal": 80, "ldl_goal": 100}
    if level == 2:
        return {"apob_goal": 70 if enh_count >= 2 else 80, "ldl_goal": 70 if enh_count >= 2 else 100}
    if level == 3:
        return {"apob_goal": 70, "ldl_goal": 70}
    return {"apob_goal": 60, "ldl_goal": 70}

def _completeness(p: Patient) -> Dict[str, Any]:
    key_items = ["apob", "lpa", "cac", "hscrp", "a1c", "tc", "hdl", "sbp", "bp_treated", "smoking", "diabetes", "sex", "race", "age"]
    present = [k for k in key_items if p.has(k)]
    missing = [k for k in key_items if not p.has(k)]
    score = int(round(100 * (len(present) / len(key_items))))
    band = "High" if score >= 85 else ("Moderate" if score >= 60 else "Low")
    return {"completeness_pct": score, "confidence": band, "missing": missing}

def _atherosclerotic_disease_burden(p: Patient) -> str:
    if p.get("ascvd") is True:
        return "Present (clinical ASCVD)"
    if p.has("cac"):
        cac = int(p.get("cac", 0))
        if cac == 0:
            return "Not detected (CAC=0)"
        return f"Present (CAC {cac})"
    return "Unknown (CAC not available)"

def _discordance_insights(p: Patient, lvl: Dict[str, Any], pce: Dict[str, Any]) -> List[str]:
    insights = []
    cac = p.get("cac", None)

    if lvl["level"] == 2 and cac is None:
        insights.append("CAC missing: consider CAC to clarify atherosclerotic disease burden and refine intensity.")

    if cac == 0 and lvl["level"] == 2 and (
        (p.has("apob") and float(p.get("apob")) >= 120) or
        (p.has("ldl") and float(p.get("ldl")) >= 160) or
        (lpa_elevated(p) and p.get("fhx") is True)
    ):
        insights.append("CAC=0 with high biologic risk: staged escalation reasonable; consider repeat CAC in 3–5 years.")

    if a1c_status(p) == "prediabetes":
        insights.append("A1c in prediabetes range: metabolic acceleration; address lifestyle and cardiometabolic drivers.")

    if has_chronic_inflammatory_disease(p):
        insights.append("Chronic inflammatory disease present: inflammatory acceleration; optimize disease control and ASCVD prevention intensity.")

    if cac and int(cac) > 0 and pce.get("risk_pct") is not None and pce["risk_pct"] < 5:
        insights.append("Low PCE but CAC>0: disease burden present; intensity may exceed what calculators suggest.")

    if cac == 0 and pce.get("risk_pct") is not None and pce["risk_pct"] >= 20:
        insights.append("High PCE but CAC=0: risk estimate may be age-driven; individualize based on enhancers and preferences.")

    return insights

def _next_prevention_focus(p: Patient, lvl: Dict[str, Any], targets: Dict[str, int], pce: Dict[str, Any]) -> List[str]:
    bullets = []

    # Target gaps
    if p.has("apob"):
        apob = int(round(float(p.get("apob"))))
        gap = apob - targets["apob_goal"]
        if gap > 0:
            bullets.append(f"ApoB reduction needed (~{gap} mg/dL) to reach goal (<{targets['apob_goal']}).")
    if p.has("ldl"):
        ldl = int(round(float(p.get("ldl"))))
        gap = ldl - targets["ldl_goal"]
        if gap > 0:
            bullets.append(f"LDL-C reduction needed (~{gap} mg/dL) to reach goal (<{targets['ldl_goal']}).")

    # CAC nuance
    if p.has("cac"):
        cac = int(p.get("cac"))
        if cac == 0 and lvl["level"] == 2:
            bullets.append("CAC=0 supports staged escalation rather than immediate intensification (if symptoms absent and no other contraindications).")
        if cac > 0 and lvl["level"] >= 3:
            bullets.append("CAC>0 indicates subclinical disease burden; prevention intensity typically higher.")

    # Genetic/inflammation acceleration
    if lpa_elevated(p) or p.get("fhx") is True:
        bullets.append("Genetic acceleration (Lp(a) and/or FHx) lowers threshold for intensification over time.")
    if inflammation_flags(p) or has_chronic_inflammatory_disease(p):
        bullets.append("Inflammatory acceleration may increase progression risk; optimize inflammatory drivers and reassess.")

    # PCE context (brief)
    if pce.get("risk_pct") is not None:
        bullets.append(f"Pooled Cohort Equations (10-year ASCVD risk): {pce['risk_pct']}% ({pce['category']}) — interpret alongside disease burden and biology.")

    # Keep it tight (max 4 bullets)
    return bullets[:4]

def evaluate(p: Patient) -> Dict[str, Any]:
    lvl = levels_band(p)
    rs = risk_signal_score(p)
    pce = pce_10y(p)

    enh_count = 0
    enh_count += 1 if p.get("fhx") is True else 0
    enh_count += 1 if lpa_elevated(p) else 0
    enh_count += 1 if (a1c_status(p) == "prediabetes") else 0
    enh_count += 1 if bool(inflammation_flags(p)) else 0
    enh_count += 1 if p.get("smoking") is True else 0
    enh_count += 1 if p.get("diabetes") is True else 0

    targets = _targets(lvl["level"], enh_count)
    completeness = _completeness(p)
    burden = _atherosclerotic_disease_burden(p)
    discordance = _discordance_insights(p, lvl, pce)
    aspirin = aspirin_advice(p, pce)
    focus = _next_prevention_focus(p, lvl, targets, pce)

    return {
        "version": VERSION,
        "levels": lvl,
        "risk_signal": rs,
        "pce_10y": pce,
        "targets": targets,
        "completeness": completeness,
        "atherosclerotic_disease_burden": burden,
        "discordance_insights": discordance,
        "next_prevention_focus": focus,
        "aspirin": aspirin,
    }

def render_note(p: Patient, out: Dict[str, Any]) -> str:
    lvl = out["levels"]
    rs = out["risk_signal"]
    pce = out["pce_10y"]
    targets = out["targets"]
    completeness = out["completeness"]
    burden = out["atherosclerotic_disease_burden"]
    discordance = out["discordance_insights"]
    focus = out["next_prevention_focus"]
    aspirin = out["aspirin"]

    def fmt_int(x):
        try: return int(round(float(x)))
        except: return x

    lines: List[str] = []
    lines.append(f"LEVELS™ {out['version']['levels']} — Cardiovascular Risk Summary")
    lines.append(f"Confidence: {completeness['confidence']} (data completeness {completeness['completeness_pct']}%)")
    lines.append("")
    lines.append(f"Risk band: {lvl['label']}")
    lines.append(f"Atherosclerotic disease burden: {burden}")
    lines.append("")

    # Numeric context
    lines.append("Numeric context")
    lines.append(f"• Risk Signal Score: {rs['score']}/100 ({rs['band']}) — {rs['note']}")
    if pce.get("risk_pct") is not None:
        lines.append(f"• Pooled Cohort Equations (10-year ASCVD risk): {pce['risk_pct']}% — {pce['category']} (population estimate)")
    else:
        if pce.get("missing"):
            lines.append(f"• Pooled Cohort Equations (10-year ASCVD risk): Not calculated (missing: {', '.join(pce['missing'])})")
        elif pce.get("notes"):
            lines.append(f"• Pooled Cohort Equations (10-year ASCVD risk): Not calculated ({pce['notes']})")
    lines.append("")

    # Key drivers (keep concise)
    lines.append("Key drivers")
    if p.has("apob"): lines.append(f"• ApoB {fmt_int(p.get('apob'))} mg/dL")
    if p.has("ldl"): lines.append(f"• LDL-C {fmt_int(p.get('ldl'))} mg/dL")
    if p.has("lpa"):
        unit = p.get("lpa_unit", "")
        lines.append(f"• Lp(a) {fmt_int(p.get('lpa'))} {unit}".strip())
    if p.get("fhx") is True: lines.append("• Premature family history")
    if p.has("hscrp") and float(p.get("hscrp")) >= 2: lines.append("• hsCRP ≥2 (inflammatory signal)")
    if a1c_status(p) == "prediabetes": lines.append("• Prediabetes range A1c (metabolic acceleration)")
    if has_chronic_inflammatory_disease(p): lines.append("• Chronic inflammatory disease present")
    lines.append("")

    # Targets
    lines.append("Targets")
    lines.append(f"• ApoB <{targets['apob_goal']} mg/dL")
    lines.append(f"• LDL-C <{targets['ldl_goal']} mg/dL")
    lines.append("")

    # Next focus
    lines.append("Next prevention focus")
    for b in focus:
        lines.append(f"• {b}")
    lines.append("")

    # Discordance (only if present)
    if discordance:
        lines.append("Discordance notes")
        for d in discordance[:3]:
            lines.append(f"• {d}")
        lines.append("")

    # Aspirin (one line)
    lines.append("Aspirin 81 mg")
    lines.append(f"• {aspirin['status']}")
    if aspirin.get("rationale"):
        lines.append(f"• Rationale: {', '.join(aspirin['rationale'][:3])}")
    lines.append("")

    # Triggers (compact)
    lines.append("Triggers")
    lines.append("• " + ", ".join(lvl["triggers"]))
    return "\n".join(lines)

