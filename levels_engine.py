# levels_engine.py
# LEVELS v1.4 — Quick mode + Pooled Cohort Equations label spelled out + target language fixed
# - Quick note (default) + Full note (details)
# - "Atherosclerotic disease burden" replaces "substrate"
# - Targets: Levels default + guideline context (ACC threshold vs ESC goals)
# - Pooled Cohort Equations (10-year ASCVD risk) is fully spelled out everywhere

import math
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

VERSION = {
    "levels": "v1.4",
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
    # chronic inflammatory disease
    if p.get("ra") is True: flags.append("RA")
    if p.get("psoriasis") is True: flags.append("Psoriasis")
    if p.get("sle") is True: flags.append("SLE")
    if p.get("ibd") is True: flags.append("IBD")
    if p.get("hiv") is True: flags.append("HIV")
    # optional drivers
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

    # Atherogenic burden (0–25): prefer ApoB else LDL
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

    # Genetics (0–15): Lp(a) + FHx
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

    # Inflammation (0–10): hsCRP ≥10 downweighted (+3), chronic inflammatory disease +5
    infl = 0
    if p.has("hscrp"):
        h = float(p.get("hscrp", 0))
        if h < 2: infl += 0
        elif h < 10: infl += 5
        else: infl += 3
    if has_chronic_inflammatory_disease(p):
        infl += 5
    infl = min(infl, 10)

    # Metabolic (0–10): diabetes +6, smoking +4, prediabetes +2
    metab = 0
    if p.get("diabetes") is True: metab += 6
    if p.get("smoking") is True: metab += 4
    if a1c_status(p) == "prediabetes": metab += 2
    metab = min(metab, 10)

    total = _clamp(burden + athero + genetics + infl + metab)

    return {
        "score": total,
        "band": _rss_band(total),
        "breakdown": {
            "Atherosclerotic disease burden": burden,
            "Atherogenic burden": athero,
            "Genetic acceleration": genetics,
            "Inflammatory acceleration": infl,
            "Metabolic acceleration": metab,
        },
        "note": "Not an event probability (biologic + plaque signal).",
    }


# ----------------------------
# Pooled Cohort Equations (10-year ASCVD risk)
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

def pooled_cohort_equations_10y_ascvd_risk(p: Patient) -> Dict[str, Any]:
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
    # Other -> non-Black coefficients
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

    return {"risk_pct": risk_pct, "category": cat, "notes": "Population estimate (does not include CAC/ApoB/Lp(a))."}


# ----------------------------
# Aspirin module (C)
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
# Levels banding and targets language
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
        if inflammation_flags(p) or has_chronic_inflammatory_disease(p):
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

def levels_targets(level: int, enh_count: int) -> Dict[str, int]:
    # User choice A: Level 2 defaults LDL <100 (not 70)
    if level <= 1:
        return {"apob_goal": 80, "ldl_goal": 100}
    if level == 2:
        return {"apob_goal": 80, "ldl_goal": 100}
    if level == 3:
        return {"apob_goal": 70, "ldl_goal": 70}
    return {"apob_goal": 60, "ldl_goal": 70}

def guideline_target_line(level: int) -> str:
    # High-yield statement: ACC uses LDL thresholds for add-on; ESC uses LDL goals.
    # We keep this generic and defensible.
    if level >= 4:
        return "Guidelines: ACC/AHA uses LDL-C 70 mg/dL threshold for add-on therapy in very-high-risk ASCVD; ESC/EAS goal often <55 mg/dL in very high risk."
    if level == 3:
        return "Guidelines: ESC/EAS goal often <70 mg/dL in high risk; ACC/AHA commonly treats CAC>0 as supporting intensified prevention."
    return "Guidelines: calculators provide population risk; CAC/biology help refine individual intensity."

def completeness(p: Patient) -> Dict[str, Any]:
    key = ["apob","lpa","cac","hscrp","a1c","tc","hdl","sbp","bp_treated","smoking","diabetes","sex","race","age"]
    present = [k for k in key if p.has(k)]
    missing = [k for k in key if not p.has(k)]
    pct = int(round(100 * (len(present)/len(key))))
    conf = "High" if pct >= 85 else ("Moderate" if pct >= 60 else "Low")
    top_missing = missing[:2]
    return {"pct": pct, "confidence": conf, "missing": missing, "top_missing": top_missing}

def atherosclerotic_disease_burden(p: Patient) -> str:
    if p.get("ascvd") is True:
        return "Present (clinical ASCVD)"
    if p.has("cac"):
        cac = int(p.get("cac", 0))
        if cac == 0: return "Not detected (CAC=0)"
        return f"Present (CAC {cac})"
    return "Unknown (CAC not available)"

def discordance_notes(p: Patient, lvl: Dict[str, Any], risk10: Dict[str, Any]) -> List[str]:
    notes = []
    cac = p.get("cac", None)
    if lvl["level"] == 2 and cac is None:
        notes.append("CAC missing: consider CAC to clarify disease burden.")
    if cac == 0 and lvl["level"] == 2 and ((p.has("apob") and float(p.get("apob")) >= 120) or (p.has("ldl") and float(p.get("ldl")) >= 160) or (lpa_elevated(p) and p.get("fhx") is True)):
        notes.append("CAC=0 with high biology: staged escalation reasonable; consider repeat CAC in 3–5 years.")
    if a1c_status(p) == "prediabetes":
        notes.append("Prediabetes range A1c: metabolic acceleration; address lifestyle/cardiometabolic drivers.")
    if has_chronic_inflammatory_disease(p):
        notes.append("Chronic inflammatory disease: inflammatory acceleration; optimize disease control.")
    rp = risk10.get("risk_pct")
    if cac and int(cac) > 0 and rp is not None and rp < 5:
        notes.append("Low 10-year risk estimate but CAC>0: disease burden present; intensity may exceed calculators.")
    return notes

def top_drivers(p: Patient) -> List[str]:
    drivers = []
    # order matters: disease burden first if present
    if p.get("ascvd") is True:
        drivers.append("Clinical ASCVD")
    elif p.has("cac"):
        cac = int(p.get("cac"))
        if cac > 0:
            drivers.append(f"CAC {cac}")
    # biology
    if p.has("apob") and float(p.get("apob")) >= 100:
        drivers.append(f"ApoB {int(round(float(p.get('apob'))))}")
    elif p.has("ldl") and float(p.get("ldl")) >= 130:
        drivers.append(f"LDL-C {int(round(float(p.get('ldl'))))}")
    if lpa_elevated(p):
        drivers.append("Lp(a) elevated")
    if p.get("fhx") is True:
        drivers.append("Premature family history")
    if a1c_status(p) == "prediabetes":
        drivers.append("Prediabetes range A1c")
    if has_chronic_inflammatory_disease(p) or (p.has("hscrp") and float(p.get("hscrp")) >= 2):
        drivers.append("Inflammatory signal")
    # keep top 3
    return drivers[:3]

def next_actions(p: Patient, lvl: Dict[str, Any], targets: Dict[str, int]) -> List[str]:
    acts = []
    # 1) close the biggest gap first
    if p.has("apob"):
        apob = int(round(float(p.get("apob"))))
        gap = apob - targets["apob_goal"]
        if gap > 0:
            acts.append(f"Reduce ApoB toward <{targets['apob_goal']} (Δ ~{gap} mg/dL).")
    elif p.has("ldl"):
        ldl = int(round(float(p.get("ldl"))))
        gap = ldl - targets["ldl_goal"]
        if gap > 0:
            acts.append(f"Reduce LDL-C toward <{targets['ldl_goal']} (Δ ~{gap} mg/dL).")

    # 2) imaging trajectory if needed
    if p.has("cac") and int(p.get("cac")) == 0 and lvl["level"] == 2:
        acts.append("Given CAC=0, staged escalation reasonable; consider repeat CAC in 3–5 years if risk persists/worsens.")
    elif not p.has("cac") and lvl["level"] >= 2:
        acts.append("Consider CAC to clarify atherosclerotic disease burden and refine intensity.")

    return acts[:2]


# ----------------------------
# Master evaluate + render (Quick + Full)
# ----------------------------

def evaluate(p: Patient) -> Dict[str, Any]:
    lvl = levels_band(p)
    rs = risk_signal_score(p)
    risk10 = pooled_cohort_equations_10y_ascvd_risk(p)
    comp = completeness(p)
    burden = atherosclerotic_disease_burden(p)
    aspirin = aspirin_advice(p, risk10)

    enh = 0
    enh += 1 if p.get("fhx") is True else 0
    enh += 1 if lpa_elevated(p) else 0
    enh += 1 if (a1c_status(p) == "prediabetes") else 0
    enh += 1 if bool(inflammation_flags(p)) else 0
    enh += 1 if p.get("smoking") is True else 0
    enh += 1 if p.get("diabetes") is True else 0

    targets = levels_targets(lvl["level"], enh)
    drivers = top_drivers(p)
    disc = discordance_notes(p, lvl, risk10)
    acts = next_actions(p, lvl, targets)

    return {
        "version": VERSION,
        "levels": lvl,
        "risk_signal": rs,
        "pooled_cohort_equations_10y_ascvd_risk": risk10,
        "targets": targets,
        "confidence": comp,
        "atherosclerotic_disease_burden": burden,
        "top_drivers": drivers,
        "next_actions": acts,
        "discordance_notes": disc,
        "aspirin": aspirin,
        "guideline_targets_line": guideline_target_line(lvl["level"]),
    }

def _fmt_int(x):
    try: return int(round(float(x)))
    except: return x

def render_note_quick(p: Patient, out: Dict[str, Any]) -> str:
    lvl = out["levels"]
    rs = out["risk_signal"]
    risk10 = out["pooled_cohort_equations_10y_ascvd_risk"]
    targets = out["targets"]
    conf = out["confidence"]
    burden = out["atherosclerotic_disease_burden"]
    asp = out["aspirin"]

    lines: List[str] = []
    lines.append(f"LEVELS™ {out['version']['levels']} — Quick Reference")
    lines.append(f"Risk band: {lvl['label'].split('—',1)[1].strip()}")
    lines.append(f"Atherosclerotic disease burden: {burden}")
    miss = conf.get("top_missing", [])
    miss_txt = (", ".join(miss)) if miss else "none"
    lines.append(f"Confidence: {conf['confidence']} (missing: {miss_txt})")
    lines.append("")
    # numeric context
    lines.append(f"Risk Signal Score: {rs['score']}/100 ({rs['band']}) — {rs['note']}")
    if risk10.get("risk_pct") is not None:
        lines.append(f"Pooled Cohort Equations (10-year ASCVD risk): {risk10['risk_pct']}% ({risk10['category']})")
    else:
        if risk10.get("missing"):
            lines.append(f"Pooled Cohort Equations (10-year ASCVD risk): not calculated (missing {', '.join(risk10['missing'][:3])})")
        else:
            lines.append("Pooled Cohort Equations (10-year ASCVD risk): not calculated")
    # drivers
    if out["top_drivers"]:
        lines.append("Drivers: " + "; ".join(out["top_drivers"]))
    # targets + deltas
    deltas = []
    if p.has("apob"):
        deltas.append(f"ΔApoB {max(0, _fmt_int(p.get('apob')) - targets['apob_goal'])}")
    if p.has("ldl"):
        deltas.append(f"ΔLDL {max(0, _fmt_int(p.get('ldl')) - targets['ldl_goal'])}")
    lines.append(f"Targets: ApoB<{targets['apob_goal']} | LDL<{targets['ldl_goal']}  ({' | '.join(deltas)})")
    # next actions
    if out["next_actions"]:
        lines.append("Next: " + " / ".join(out["next_actions"]))
    # aspirin
    lines.append(f"Aspirin 81 mg: {asp['status']}")
    return "\n".join(lines)

def render_note_full(p: Patient, out: Dict[str, Any]) -> str:
    # Full is still concise, but includes key drivers + discordance + guideline line
    base = render_note_quick(p, out).splitlines()
    lines = base + ["", "Guideline context:", f"- {out['guideline_targets_line']}"]
    if out["discordance_notes"]:
        lines += ["", "Discordance notes:"] + [f"- {x}" for x in out["discordance_notes"][:4]]
    # Add triggers at end
    lines += ["", "Triggers: " + ", ".join(out["levels"]["triggers"])]
    return "\n".join(lines)

