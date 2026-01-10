# levels_engine.py
# LEVELS v2.0 (restored functional baseline) + v2.3-style explanation fields
# - Preserves: inflammatory states, hsCRP, Lp(a) (unit-aware), CAC logic, PCE, aspirin, ESC goals
# - Adds: levels.meaning / levels.why / levels.defaultPosture / levels.sublevel (2A/2B/2C)
# - Adds: short_why() helper expected by UI
#
# IMPORTANT: Does NOT remove any existing output keys; only adds fields.

import math
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

VERSION = {
    "levels": "v2.0+exp",
    "riskSignal": "RSS v1.0",
    "riskCalc": "Pooled Cohort Equations (ACC/AHA 2013; Race other→non-Black)",
    "aspirin": "Aspirin v1.0 (CAC≥100 OR 10y risk≥10%, age 40–69, low bleed risk)",
}

@dataclass
class Patient:
    data: Dict[str, Any]
    def get(self, k, d=None): return self.data.get(k, d)
    def has(self, k): return k in self.data and self.data[k] is not None


# ----------------------------
# Helpers
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
    """UI helper: join the first N rationale items into a readable snippet."""
    if not items:
        return ""
    trimmed = [str(x).strip() for x in items if str(x).strip()]
    return "; ".join(trimmed[:max_items])

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

def lpa_elevated(p: Patient) -> bool:
    if not p.has("lpa"):
        return False
    try:
        v = float(p.get("lpa", 0))
    except Exception:
        return False
    unit = str(p.get("lpa_unit", "")).lower()
    if "mg" in unit:
        return v >= 50
    # default assume nmol/L
    return v >= 125


# ----------------------------
# Risk Signal Score (0–100)
# ----------------------------
def clamp(x: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, x))

def rss_band(score: int) -> str:
    if score <= 19: return "Low"
    if score <= 39: return "Mild"
    if score <= 59: return "Moderate"
    if score <= 79: return "High"
    return "Very high"

def risk_signal_score(p: Patient) -> Dict[str, Any]:
    # Atherosclerotic disease burden (0–55)
    burden = 0
    if p.get("ascvd") is True:
        burden = 55
    elif p.has("cac"):
        cac = int(p.get("cac", 0))
        if cac == 0: burden = 0
        elif 1 <= cac <= 9: burden = 20
        elif 10 <= cac <= 99: burden = 30
        elif 100 <= cac <= 399: burden = 45
        else: burden = 55

    # Atherogenic burden (0–25)
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

    # Genetics (0–15)
    genetics = 0
    if p.has("lpa"):
        unit = str(p.get("lpa_unit", "")).lower()
        lpa = float(p.get("lpa", 0))
        if "mg" in unit:
            genetics += 12 if lpa >= 100 else (8 if lpa >= 50 else 0)
        else:
            genetics += 12 if lpa >= 250 else (8 if lpa >= 125 else 0)
    if p.get("fhx") is True:
        genetics += 5
    genetics = min(genetics, 15)

    # Inflammation (0–10)
    infl = 0
    if p.has("hscrp"):
        h = float(p.get("hscrp", 0))
        if h < 2: infl += 0
        elif h < 10: infl += 5
        else: infl += 3  # downweight possible acute illness
    if has_chronic_inflammatory_disease(p):
        infl += 5
    infl = min(infl, 10)

    # Metabolic (0–10)
    metab = 0
    if p.get("diabetes") is True: metab += 6
    if p.get("smoking") is True: metab += 4
    if a1c_status(p) == "prediabetes": metab += 2
    metab = min(metab, 10)

    total = clamp(int(round(burden + athero + genetics + infl + metab)))
    return {
        "score": total,
        "band": rss_band(total),
        "note": "Not an event probability (biologic + plaque signal)."
    }


# ----------------------------
# Pooled Cohort Equations (10-year ASCVD risk)
# Race other -> non-Black (white) coefficients
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

def pooled_cohort_equations_10y_ascvd_risk(p: Patient) -> Dict[str, Any]:
    req = ["age","sex","race","tc","hdl","sbp","bp_treated","smoking","diabetes"]
    missing = [k for k in req if not p.has(k)]
    if missing:
        return {"risk_pct": None, "missing": missing}

    age = int(p.get("age"))
    if age < 40 or age > 79:
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

    return {"risk_pct": risk_pct, "category": cat, "notes": "Population estimate (does not include CAC/ApoB/Lp(a))."}


# ----------------------------
# Aspirin module
# ----------------------------
def aspirin_advice(p: Patient, risk10: Dict[str, Any]) -> Dict[str, Any]:
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

    risk_pct = risk10.get("risk_pct")
    risk_ok = (risk_pct is not None and risk_pct >= 10.0)
    cac_ok = (cac is not None and cac >= 100)

    if cac_ok or risk_ok:
        reasons = []
        if cac_ok: reasons.append("CAC ≥100")
        if risk_ok: reasons.append(f"Pooled Cohort Equations 10-year risk ≥10% ({risk_pct}%)")
        return {"status": "Consider (shared decision)", "rationale": reasons + ["Bleeding risk low by available flags"]}

    return {"status": "Avoid / individualize", "rationale": ["Primary prevention benefit likely small at current risk level"]}


# ----------------------------
# Levels banding + targets + ESC goals
# ----------------------------
def levels_band(p: Patient) -> Dict[str, Any]:
    triggers=[]; level=0

    if p.get("ascvd") is True:
        level=4; triggers.append("ASCVD")
    if p.has("cac") and int(p.get("cac",0))>=100:
        level=max(level,4); triggers.append("CAC>=100")
    if p.has("cac") and int(p.get("cac",0))>0:
        level=max(level,3); triggers.append("CAC>0")

    if level<3:
        if p.has("apob") and float(p.get("apob",0))>=100:
            level=max(level,2); triggers.append("ApoB>=100")
        if p.has("ldl") and float(p.get("ldl",0))>=130:
            level=max(level,2); triggers.append("LDL>=130")
        if lpa_elevated(p):
            level=max(level,2); triggers.append("Lp(a) elevated")
        if p.get("fhx") is True:
            level=max(level,2); triggers.append("FHx_premature")
        if a1c_status(p)=="prediabetes":
            triggers.append("Prediabetes_A1c")
        if inflammation_flags(p) or has_chronic_inflammatory_disease(p):
            triggers.append("Inflammation_present")

    if level==0 and p.data:
        level=1; triggers.append("Any_risk_signal_present")

    labels={
        0:"Level 0 — No atherosclerotic risk detected",
        1:"Level 1 — Mild biologic risk (no disease)",
        2:"Level 2 — High biologic risk (disease not yet proven)",
        3:"Level 3 — Subclinical atherosclerotic disease",
        4:"Level 4 — Advanced / clinical atherosclerotic disease"
    }
    return {"level":level, "label":labels[level], "triggers":sorted(set(triggers))}

def levels_targets(level:int)->Dict[str,int]:
    if level<=1: return {"apob":80, "ldl":100}
    if level==2: return {"apob":80, "ldl":100}
    if level==3: return {"apob":70, "ldl":70}
    return {"apob":60, "ldl":70}

def esc_numeric_goals(level:int)->str:
    if level>=4:
        return "ESC/EAS goals: LDL-C <55 mg/dL; ApoB <65 mg/dL."
    if level==3:
        return "ESC/EAS goals: LDL-C <70 mg/dL; ApoB <80 mg/dL."
    if level==2:
        return "ESC/EAS goals (often): LDL-C <100 mg/dL; ApoB <100 mg/dL (tighten with enhancers)."
    return "ESC/EAS goals: individualized by risk tier."

def atherosclerotic_disease_burden(p: Patient)->str:
    if p.get("ascvd") is True:
        return "Present (clinical ASCVD)"
    if p.has("cac"):
        cac=int(p.get("cac",0))
        return "Not detected (CAC=0)" if cac==0 else f"Present (CAC {cac})"
    return "Unknown (CAC not available)"

def completeness(p: Patient)->Dict[str,Any]:
    key=["apob","lpa","cac","hscrp","a1c","tc","hdl","sbp","bp_treated","smoking","diabetes","sex","race","age"]
    present=[k for k in key if p.has(k)]
    missing=[k for k in key if not p.has(k)]
    pct=int(round(100*(len(present)/len(key))))
    conf="High" if pct>=85 else ("Moderate" if pct>=60 else "Low")
    return {"pct":pct, "confidence":conf, "top_missing":missing[:2], "missing":missing}

def top_drivers(p: Patient)->List[str]:
    d=[]
    if p.get("ascvd") is True:
        d.append("Clinical ASCVD")
    elif p.has("cac") and int(p.get("cac",0))>0:
        d.append(f"CAC {int(p.get('cac'))}")
    if p.has("apob") and float(p.get("apob",0))>=100:
        d.append(f"ApoB {fmt_int(p.get('apob'))}")
    elif p.has("ldl") and float(p.get("ldl",0))>=130:
        d.append(f"LDL-C {fmt_int(p.get('ldl'))}")
    if lpa_elevated(p):
        d.append("Lp(a) elevated")
    if p.get("fhx") is True:
        d.append("Premature family history")
    if a1c_status(p)=="prediabetes":
        d.append("Prediabetes A1c")
    if inflammation_flags(p) or has_chronic_inflammatory_disease(p):
        d.append("Inflammatory signal")
    return d[:3]

def next_actions(p: Patient, level:int, targets:Dict[str,int])->List[str]:
    acts=[]
    if p.has("apob"):
        ap=fmt_int(p.get("apob"))
        try:
            if float(ap) > targets["apob"]:
                acts.append(f"Reduce ApoB toward <{targets['apob']} mg/dL.")
        except Exception:
            pass
    if p.has("cac") and int(p.get("cac"))==0 and level==2:
        acts.append("CAC=0 supports staged escalation; consider repeat CAC in 3–5y if risk persists.")
    elif (not p.has("cac")) and level>=2:
        acts.append("Consider CAC to clarify disease burden and refine intensity.")
    return acts[:2]


# ----------------------------
# v2.3-style explanations (meaning/why/defaultPosture/sublevel)
# ----------------------------
def _level_sublevel_and_explain(p: Patient, lvl: Dict[str, Any], risk10: Dict[str, Any]) -> Dict[str, Any]:
    """
    Adds:
      - meaning: clinician-facing summary sentence
      - why: short bullet list for UI
      - defaultPosture: the "default move"
      - sublevel (Level 2 only): 2A / 2B / 2C
    Keeps the underlying level determination unchanged.
    """
    level = int(lvl.get("level", 0))
    triggers = lvl.get("triggers", []) or []
    why: List[str] = []

    # Build why bullets from triggers + major values
    if p.get("ascvd") is True:
        why.append("Clinical ASCVD present")
    if p.has("cac") and int(p.get("cac", 0)) >= 100:
        why.append(f"CAC {int(p.get('cac'))} (≥100)")
    elif p.has("cac") and int(p.get("cac", 0)) > 0:
        why.append(f"CAC {int(p.get('cac'))} (>0)")
    if p.has("apob") and float(p.get("apob", 0)) >= 100:
        why.append(f"ApoB {fmt_int(p.get('apob'))} (≥100)")
    if (not p.has("apob")) and p.has("ldl") and float(p.get("ldl", 0)) >= 130:
        why.append(f"LDL-C {fmt_int(p.get('ldl'))} (≥130)")
    if lpa_elevated(p):
        why.append("Lp(a) elevated")
    if p.get("fhx") is True:
        why.append("Premature family history")
    if a1c_status(p) == "prediabetes":
        why.append("Prediabetes range A1c")
    if inflammation_flags(p) or has_chronic_inflammatory_disease(p):
        why.append("Inflammatory risk enhancer(s)")

    # Keep list short for UI
    why = [w for w in why if w][:3]

    meaning = ""
    posture = ""
    sublevel: Optional[str] = None

    if level <= 0:
        meaning = "No clear plaque or high-risk signals detected with current data."
        posture = "Maintain lifestyle foundations; reassess if risk profile changes."
    elif level == 1:
        meaning = "Mild biologic risk signals without proven plaque."
        posture = "Lifestyle-first; confirm key labs and trend over time."
    elif level == 2:
        # Sublevels: keep simple + consistent with your earlier descriptions
        enhancers = 0
        if lpa_elevated(p): enhancers += 1
        if p.get("fhx") is True: enhancers += 1
        if inflammation_flags(p) or has_chronic_inflammatory_disease(p): enhancers += 1

        risk_pct = risk10.get("risk_pct")
        intermediate_risk = (risk_pct is not None and risk_pct >= 7.5)

        if enhancers >= 1:
            sublevel = "2B"
        elif intermediate_risk:
            sublevel = "2C"
        else:
            sublevel = "2A"

        meaning = "High biologic risk without proven plaque; intensity depends on enhancers and confirmation testing."
        posture = "Shared decision toward lipid lowering; consider CAC if unknown; treat enhancers."

        # Add one sublevel-specific why hint
        if sublevel == "2A":
            why = why[:2] + ["Risk drift without major enhancers"] if why else ["Risk drift without major enhancers"]
        elif sublevel == "2B":
            why = why[:2] + ["Risk enhancers present"] if why else ["Risk enhancers present"]
        elif sublevel == "2C":
            why = why[:2] + ["Intermediate risk profile"] if why else ["Intermediate risk profile"]

        why = why[:3]
    elif level == 3:
        meaning = "Subclinical atherosclerosis is present (plaque signal)."
        posture = "Treat like early disease: statin default; intensify to targets; reassess response."
    else:
        meaning = "Advanced risk: clinical ASCVD or high plaque burden."
        posture = "Secondary-prevention posture: high-intensity therapy; aggressive ApoB/LDL targets."

    return {
        "meaning": meaning,
        "why": why,
        "defaultPosture": posture,
        "sublevel": sublevel,
    }


# ----------------------------
# Public API
# ----------------------------
def evaluate(p: Patient)->Dict[str,Any]:
    lvl = levels_band(p)
    rs  = risk_signal_score(p)
    risk10 = pooled_cohort_equations_10y_ascvd_risk(p)
    t = levels_targets(lvl["level"])
    conf = completeness(p)
    burden = atherosclerotic_disease_burden(p)
    asp = aspirin_advice(p, risk10)

    # Add v2.3-style explanation fields (does not change level)
    explain = _level_sublevel_and_explain(p, lvl, risk10)
    lvl = {**lvl, **explain}

    return {
        "version": VERSION,
        "levels": lvl,
        "riskSignal": rs,
        "pooledCohortEquations10yAscvdRisk": risk10,
        "targets": t,
        "confidence": conf,
        "diseaseBurden": burden,
        "drivers": top_drivers(p),
        "nextActions": next_actions(p, lvl["level"], t),
        "escGoals": esc_numeric_goals(lvl["level"]),
        "aspirin": asp,
    }

def render_quick_text(p: Patient, out: Dict[str,Any])->str:
    lvl=out["levels"]; rs=out["riskSignal"]; risk10=out["pooledCohortEquations10yAscvdRisk"]
    t=out["targets"]; conf=out["confidence"]

    lines=[]
    lines.append(f"LEVELS™ {out['version']['levels']} — Quick Reference")
    # Include sublevel if present
    sub = f" ({lvl.get('sublevel')})" if lvl.get("sublevel") else ""
    lines.append(f"Level {lvl['level']}{sub}: {lvl['label'].split('—',1)[1].strip()}")
    lines.append(f"Atherosclerotic disease burden: {out['diseaseBurden']}")
    miss=", ".join(conf["top_missing"]) if conf["top_missing"] else "none"
    lines.append(f"Confidence: {conf['confidence']} (missing: {miss})")
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

    # Targets: current -> goal (NO deltas)
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

