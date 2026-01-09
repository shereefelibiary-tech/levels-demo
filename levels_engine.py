# levels_engine.py
# LEVELS v2.3 — Engine + structured explanations for UI (Meaning / Why / Default posture)
# Includes:
# - Levels 0–5 with Level 2A/2B/2C sublevels
# - Risk Signal Score (RSS)
# - Pooled Cohort Equations (10-year ASCVD risk)
# - Aspirin module with clean status labels + rationale
# - ESC numeric goals, ACC/AHA context, time horizon framing
#
# New in v2.3:
# - levels_band() returns:
#   levels: { level, sublevel, label, triggers, meaning, why, defaultPosture }

import math
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

VERSION = {
    "levels": "v2.3",
    "riskSignal": "RSS v1.0",
    "riskCalc": "Pooled Cohort Equations (ACC/AHA 2013; Race other→non-Black)",
    "aspirin": "Aspirin v1.1 (clean status labels + rationale)",
}

# ----------------------------
# Data model
# ----------------------------
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
    except:
        return x

def safe_float(x, default=None) -> Optional[float]:
    try:
        if x is None:
            return default
        return float(x)
    except:
        return default

def safe_int(x, default=None) -> Optional[int]:
    try:
        if x is None:
            return default
        return int(round(float(x)))
    except:
        return default

def short_why(reasons: List[str], max_items: int = 2) -> str:
    if not reasons:
        return ""
    cleaned = [str(r).strip() for r in reasons if str(r).strip()]
    drop = {"Bleeding risk low by available flags"}
    if len(cleaned) > 1:
        cleaned = [r for r in cleaned if r not in drop]
    return "; ".join(cleaned[:max_items])

def a1c_status(p: Patient) -> Optional[str]:
    if not p.has("a1c"):
        return None
    a1c = safe_float(p.get("a1c"))
    if a1c is None:
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
        h = safe_float(p.get("hscrp"))
        if h is not None and h >= 2:
            flags.append("hsCRP≥2")
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
    v = safe_float(p.get("lpa", 0), default=0.0)
    unit = str(p.get("lpa_unit", "")).lower()
    # ACC enhancer threshold: ≥50 mg/dL or ≥125 nmol/L
    if "mg" in unit:
        return v >= 50
    return v >= 125

def premature_fhx(p: Patient) -> bool:
    """
    Backward compatible:
      - fhx=True assumed "premature FHx" in existing UI
    Optional richer fields:
      - fhx_premature (bool)
      - fhx_relation, fhx_sex, fhx_age_event
    """
    if p.get("fhx_premature") is True:
        return True
    if p.get("fhx") is True:
        return True

    age_evt = safe_int(p.get("fhx_age_event"))
    sex = str(p.get("fhx_sex", "")).lower()
    if age_evt is None or sex not in ("male", "m", "female", "f"):
        return False
    is_male = sex in ("male", "m")

    rel = str(p.get("fhx_relation", "")).lower()
    # Only treat as qualifying when relation implies first-degree; otherwise do not promote.
    if rel and rel not in ("father", "mother", "brother", "sister", "son", "daughter", "parent", "sibling", "child"):
        return False

    if is_male and age_evt < 55:
        return True
    if (not is_male) and age_evt < 65:
        return True
    return False

def metabolic_syndrome(p: Patient) -> bool:
    if p.get("metabolic_syndrome") is True:
        return True

    tg = safe_float(p.get("tg"))
    hdl = safe_float(p.get("hdl"))
    waist = safe_float(p.get("waist_cm"))
    treated_htn = bool(p.get("bp_treated")) is True
    a1 = a1c_status(p)

    criteria = 0
    if tg is not None and tg >= 150: criteria += 1
    if hdl is not None:
        sex = str(p.get("sex", "")).lower()
        male = sex in ("m", "male")
        if (male and hdl < 40) or ((not male) and hdl < 50):
            criteria += 1
    if waist is not None and waist >= 102: criteria += 1
    if treated_htn: criteria += 1
    if a1 in ("prediabetes", "diabetes_range"): criteria += 1
    return criteria >= 3

def enhancer_list(p: Patient) -> List[str]:
    enh = []
    if premature_fhx(p): enh.append("premature_FHx")
    if lpa_elevated(p): enh.append("Lp(a)")
    if has_chronic_inflammatory_disease(p): enh.append("chronic_inflammation")
    if p.get("ckd") is True: enh.append("CKD")
    if p.has("egfr") and safe_float(p.get("egfr")) is not None and safe_float(p.get("egfr")) < 60:
        enh.append("CKD(eGFR<60)")
    if p.get("high_risk_ethnicity") is True: enh.append("high_risk_ethnicity")
    if metabolic_syndrome(p): enh.append("metabolic_syndrome")
    tg = safe_float(p.get("tg"))
    if tg is not None and tg >= 175: enh.append("TG≥175")
    return enh


# ----------------------------
# Risk Signal Score
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
    burden = 0
    if p.get("ascvd") is True:
        burden = 55
    elif p.has("cac"):
        cac = safe_int(p.get("cac", 0), default=0) or 0
        if cac == 0: burden = 0
        elif 1 <= cac <= 9: burden = 20
        elif 10 <= cac <= 99: burden = 30
        elif 100 <= cac <= 399: burden = 45
        else: burden = 55

    athero = 0
    if p.has("apob"):
        apob = safe_float(p.get("apob", 0), default=0.0)
        if apob < 80: athero = 0
        elif apob <= 99: athero = 8
        elif apob <= 119: athero = 15
        elif apob <= 149: athero = 20
        else: athero = 25
    elif p.has("ldl"):
        ldl = safe_float(p.get("ldl", 0), default=0.0)
        if ldl < 100: athero = 0
        elif ldl <= 129: athero = 5
        elif ldl <= 159: athero = 10
        elif ldl <= 189: athero = 15
        else: athero = 20

    genetics = 0
    if p.has("lpa"):
        unit = str(p.get("lpa_unit", "")).lower()
        lpa = safe_float(p.get("lpa", 0), default=0.0)
        if "mg" in unit:
            genetics += 12 if lpa >= 100 else (8 if lpa >= 50 else 0)
        else:
            genetics += 12 if lpa >= 250 else (8 if lpa >= 125 else 0)
    if premature_fhx(p):
        genetics += 5
    genetics = min(genetics, 15)

    infl = 0
    if p.has("hscrp"):
        h = safe_float(p.get("hscrp", 0), default=0.0)
        if h < 2: infl += 0
        elif h < 10: infl += 5
        else: infl += 3
    if has_chronic_inflammatory_disease(p):
        infl += 5
    infl = min(infl, 10)

    metab = 0
    if p.get("diabetes") is True: metab += 6
    if p.get("smoking") is True: metab += 4
    if a1c_status(p) == "prediabetes": metab += 2
    metab = min(metab, 10)

    total = clamp(burden + athero + genetics + infl + metab)
    return {"score": total, "band": rss_band(total), "note": "Not an event probability (biologic + plaque signal)."}


# ----------------------------
# Pooled Cohort Equations (10-year ASCVD risk)
# Race "other" -> non-Black (white) coefficients
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
# Aspirin module (clean labels + rationale)
# ----------------------------
def aspirin_advice(p: Patient, risk10: Dict[str, Any]) -> Dict[str, Any]:
    age = safe_int(p.get("age")) if p.has("age") else None
    cac = safe_int(p.get("cac")) if p.has("cac") else None
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

    # Secondary prevention
    if ascvd:
        if bleed_flags:
            return {"status": "Consider aspirin (shared decision)",
                    "rationale": ["Clinical ASCVD present"] + ["Bleeding risk flags: " + "; ".join(bleed_flags)]}
        return {"status": "Recommend aspirin",
                "rationale": ["Clinical ASCVD present (no bleeding risk flags identified)"]}

    # Primary prevention
    if age is None:
        return {"status": "Not assessed", "rationale": ["Age missing"]}

    if age < 40 or age >= 70:
        return {"status": "Would not recommend aspirin",
                "rationale": [f"Age {age} (primary prevention net benefit unlikely)"]}

    if bleed_flags:
        return {"status": "Would not recommend aspirin",
                "rationale": ["Bleeding risk flags: " + "; ".join(bleed_flags)]}

    risk_pct = risk10.get("risk_pct")
    risk_ok = (risk_pct is not None and risk_pct >= 10.0)
    cac_ok = (cac is not None and cac >= 100)

    if cac_ok or risk_ok:
        reasons = []
        if cac_ok: reasons.append("CAC ≥100")
        if risk_ok: reasons.append(f"Pooled Cohort Equations 10-year risk ≥10% ({risk_pct}%)")
        return {"status": "Consider aspirin (shared decision)",
                "rationale": reasons + ["Bleeding risk low by available flags"]}

    return {"status": "Would not recommend aspirin",
            "rationale": ["Primary prevention benefit likely small at current risk level"]}


# ----------------------------
# Levels assignment helpers
# ----------------------------
def _domains_abnormal(p: Patient) -> int:
    domains = 0

    apob = safe_float(p.get("apob"))
    ldl = safe_float(p.get("ldl"))
    if apob is not None:
        if apob >= 90: domains += 1
    elif ldl is not None:
        if ldl >= 130: domains += 1

    sbp = safe_float(p.get("sbp"))
    if sbp is not None and sbp >= 130: domains += 1
    if p.get("bp_treated") is True: domains += 1

    if p.get("diabetes") is True:
        domains += 1
    else:
        a1 = a1c_status(p)
        if a1 == "prediabetes":
            a1c = safe_float(p.get("a1c"))
            if a1c is not None and a1c >= 6.0:
                domains += 1

    return min(domains, 3)

def _mild_abnormalities_count(p: Patient) -> int:
    count = 0

    apob = safe_float(p.get("apob"))
    ldl = safe_float(p.get("ldl"))
    tg = safe_float(p.get("tg"))
    sbp = safe_float(p.get("sbp"))
    a1c = safe_float(p.get("a1c"))

    if apob is not None:
        if 80 <= apob <= 89: count += 1
    elif ldl is not None:
        if 100 <= ldl <= 129: count += 1

    if tg is not None and 150 <= tg <= 199: count += 1

    if sbp is not None and 130 <= sbp <= 139: count += 1
    if p.get("bp_treated") is True: count += 1

    if a1c is not None and 5.7 <= a1c <= 5.9: count += 1

    return count

def _humanize_triggers(triggers: List[str]) -> List[str]:
    bullets: List[str] = []
    for t in triggers:
        tt = t.strip()

        if tt.startswith("CAC "):
            bullets.append(tt.replace("(1–99)", "").strip())
            continue
        if "CAC≥100" in tt:
            bullets.append("CAC indicates established plaque burden")
            continue
        if tt == "ASCVD":
            bullets.append("Clinical ASCVD history")
            continue
        if "LDL≥190" in tt:
            bullets.append("Very high LDL-C (possible familial hypercholesterolemia)")
            continue
        if "ApoB 90–99" in tt:
            bullets.append("ApoB suggests elevated atherogenic particle burden")
            continue
        if "LDL 130–159" in tt:
            bullets.append("LDL-C is moderately elevated")
            continue
        if "A1c 6.0–6.4" in tt:
            bullets.append("A1c suggests higher-risk prediabetes")
            continue
        if "Metabolic syndrome" in tt:
            bullets.append("Metabolic syndrome increases long-term risk")
            continue
        if "Lp(a)" in tt:
            bullets.append("Lp(a) is elevated (inherited risk enhancer)")
            continue
        if "Premature family history" in tt or "premature" in tt.lower():
            bullets.append("Premature family history suggests earlier plaque development")
            continue
        if "Chronic inflammatory disease" in tt:
            bullets.append("Chronic inflammation accelerates atherosclerosis risk")
            continue
        if "CKD" in tt:
            bullets.append("Kidney disease increases cardiovascular risk")
            continue
        if "ApoB discordance" in tt:
            bullets.append("ApoB is high despite lower LDL (hidden particle burden)")
            continue
        if "PCE" in tt:
            bullets.append(tt.replace("PCE", "10-year risk estimate"))
            continue
        if "mild abnormalities" in tt:
            bullets.append("Multiple mild risk signals cluster together")
            continue
        if "Enhancers:" in tt:
            bullets.append(tt.replace("Enhancers:", "Risk enhancers:").strip())
            continue

        bullets.append(tt)

    seen = set()
    out = []
    for b in bullets:
        if b not in seen:
            out.append(b)
            seen.add(b)
    return out[:4]

def _meaning_and_posture(level: int, sublevel: Optional[str]) -> Dict[str, str]:
    if level == 0:
        return {
            "meaning": "No major atherosclerotic risk signal detected based on available data.",
            "posture": "Maintain healthy habits; periodic re-check."
        }
    if level == 1:
        return {
            "meaning": "Early drift: mild, low-grade risk signals without evidence of plaque.",
            "posture": "Lifestyle-first; repeat/confirm outliers; monitor trajectory."
        }
    if level == 2:
        if sublevel == "2A":
            return {
                "meaning": "Biologic risk is present, but structural disease is not established.",
                "posture": "Aggressive lifestyle; shared decision on medication based on exposure, preferences, and trend."
            }
        if sublevel == "2B":
            return {
                "meaning": "Risk is driven by enhancers (inherited/inflammatory/CKD) that can accelerate plaque even when short-term risk looks modest.",
                "posture": "Statin favored; address enhancers; consider CAC if unknown to refine intensity."
            }
        if sublevel == "2C":
            return {
                "meaning": "Probability of silent/subclinical disease is higher (often CAC 1–99 or multi-domain intermediate risk).",
                "posture": "Treat more like early disease: statin default; use CAC/structure to guide intensity and follow-up."
            }
        return {"meaning": "Moderate prevention zone (Level 2).",
                "posture": "Escalate prevention intensity based on biology, enhancers, and/or structure."}
    if level == 3:
        return {
            "meaning": "Subclinical atherosclerosis is established (imaging/plaque evidence).",
            "posture": "Secondary-prevention mindset: statin strong default; intensify to reach targets."
        }
    if level == 4:
        return {
            "meaning": "Clinical ASCVD or risk-equivalent disease is present.",
            "posture": "High-intensity lipid lowering typical; add-on therapy based on response/thresholds."
        }
    if level >= 5:
        return {
            "meaning": "Extreme/progressive ASCVD risk (recurrent events or polyvascular disease).",
            "posture": "Maximal risk reduction strategy; combination lipid therapy often appropriate."
        }
    return {"meaning": "Risk tier assigned.", "posture": "Individualize management."}


# ----------------------------
# Levels banding (v2.3)
# ----------------------------
def levels_band(p: Patient, risk10: Dict[str, Any]) -> Dict[str, Any]:
    triggers: List[str] = []
    sublevel: Optional[str] = None

    cac = safe_int(p.get("cac")) if p.has("cac") else None
    apob = safe_float(p.get("apob")) if p.has("apob") else None
    ldl = safe_float(p.get("ldl")) if p.has("ldl") else None
    a1c = safe_float(p.get("a1c")) if p.has("a1c") else None
    pce = risk10.get("risk_pct")
    enh = enhancer_list(p)

    # Level 5 — extreme/progressive ASCVD
    if p.get("ascvd") is True and any(p.get(k) is True for k in ["recurrent_ascvd", "polyvascular", "event_on_therapy"]):
        triggers.append("ASCVD (progressive/extreme features)")
        m = _meaning_and_posture(5, None)
        return {"level": 5, "sublevel": None, "label": "Level 5 — Extreme / progressive ASCVD risk",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    # Level 4 — clinical ASCVD / risk equivalent
    if p.get("ascvd") is True:
        triggers.append("ASCVD")
        m = _meaning_and_posture(4, None)
        return {"level": 4, "sublevel": None, "label": "Level 4 — Clinical ASCVD / risk-equivalent disease",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    if ldl is not None and ldl >= 190:
        triggers.append("LDL≥190")
        m = _meaning_and_posture(4, None)
        return {"level": 4, "sublevel": None, "label": "Level 4 — Severe hypercholesterolemia (risk-equivalent)",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    if p.get("diabetes") is True and any(p.get(k) is True for k in ["ckd", "retinopathy", "neuropathy", "albuminuria", "target_organ_damage"]):
        triggers.append("Diabetes + target organ damage")
        m = _meaning_and_posture(4, None)
        return {"level": 4, "sublevel": None, "label": "Level 4 — Diabetes with target organ damage (risk-equivalent)",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    # Level 3 — subclinical disease established
    if cac is not None and (cac >= 100 or p.get("cac_ge_75pctl") is True):
        triggers.append("CAC≥100 or ≥75th percentile")
        m = _meaning_and_posture(3, None)
        return {"level": 3, "sublevel": None, "label": "Level 3 — Subclinical atherosclerotic disease (imaging+)",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    if any(p.get(k) is True for k in ["carotid_plaque", "femoral_plaque"]):
        triggers.append("Carotid/femoral plaque")
        m = _meaning_and_posture(3, None)
        return {"level": 3, "sublevel": None, "label": "Level 3 — Subclinical atherosclerotic disease (plaque)",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    abi = safe_float(p.get("abi")) if p.has("abi") else None
    if abi is not None and abi < 0.9:
        triggers.append("ABI<0.9")
        m = _meaning_and_posture(3, None)
        return {"level": 3, "sublevel": None, "label": "Level 3 — Subclinical atherosclerotic disease (ABI+)",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    # Level 2C — silent disease probability
    if cac is not None and 1 <= cac <= 99:
        sublevel = "2C"
        triggers.append(f"CAC {cac} (1–99)")
        m = _meaning_and_posture(2, sublevel)
        return {"level": 2, "sublevel": sublevel, "label": "Level 2C — Silent disease probability",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    domains = _domains_abnormal(p)
    if pce is not None and pce >= 7.5 and domains >= 2:
        sublevel = "2C"
        triggers.append(f"PCE≥7.5% ({pce}%) + ≥2 abnormal domains")
        m = _meaning_and_posture(2, sublevel)
        return {"level": 2, "sublevel": sublevel, "label": "Level 2C — Silent disease probability",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    # Level 2B — enhancer-driven acceleration
    discordance = (apob is not None and apob >= 90 and ldl is not None and ldl < 100)

    if lpa_elevated(p):
        sublevel = "2B"
        triggers.append("Lp(a) elevated (enhancer)")
        m = _meaning_and_posture(2, sublevel)
        return {"level": 2, "sublevel": sublevel, "label": "Level 2B — Enhancer-driven acceleration",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    if premature_fhx(p):
        sublevel = "2B"
        triggers.append("Premature family history (enhancer)")
        m = _meaning_and_posture(2, sublevel)
        return {"level": 2, "sublevel": sublevel, "label": "Level 2B — Enhancer-driven acceleration",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    if has_chronic_inflammatory_disease(p):
        sublevel = "2B"
        triggers.append("Chronic inflammatory disease (enhancer)")
        m = _meaning_and_posture(2, sublevel)
        return {"level": 2, "sublevel": sublevel, "label": "Level 2B — Enhancer-driven acceleration",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    if discordance:
        sublevel = "2B"
        triggers.append("ApoB discordance (ApoB≥90 with LDL<100)")
        m = _meaning_and_posture(2, sublevel)
        return {"level": 2, "sublevel": sublevel, "label": "Level 2B — Enhancer-driven acceleration",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    if p.get("ckd") is True or (p.has("egfr") and safe_float(p.get("egfr")) is not None and safe_float(p.get("egfr")) < 60):
        sublevel = "2B"
        triggers.append("CKD (enhancer)")
        m = _meaning_and_posture(2, sublevel)
        return {"level": 2, "sublevel": sublevel, "label": "Level 2B — Enhancer-driven acceleration",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    # Level 2A — biologic risk, low structural risk
    if apob is not None and 90 <= apob <= 99:
        sublevel = "2A"
        triggers.append("ApoB 90–99")
        m = _meaning_and_posture(2, sublevel)
        return {"level": 2, "sublevel": sublevel, "label": "Level 2A — Biologic risk, low structural risk",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    if ldl is not None and 130 <= ldl <= 159:
        sublevel = "2A"
        triggers.append("LDL 130–159")
        m = _meaning_and_posture(2, sublevel)
        return {"level": 2, "sublevel": sublevel, "label": "Level 2A — Biologic risk, low structural risk",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    if a1c is not None and 6.0 <= a1c < 6.5:
        sublevel = "2A"
        triggers.append("A1c 6.0–6.4")
        m = _meaning_and_posture(2, sublevel)
        return {"level": 2, "sublevel": sublevel, "label": "Level 2A — Biologic risk, low structural risk",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    if metabolic_syndrome(p):
        sublevel = "2A"
        triggers.append("Metabolic syndrome")
        m = _meaning_and_posture(2, sublevel)
        return {"level": 2, "sublevel": sublevel, "label": "Level 2A — Biologic risk, low structural risk",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    # Use PCE to populate 2A when not 2C
    if pce is not None and (5.0 <= pce < 20.0):
        sublevel = "2A"
        triggers.append(f"PCE {pce}% ({risk10.get('category','')})")
        m = _meaning_and_posture(2, sublevel)
        return {"level": 2, "sublevel": sublevel, "label": "Level 2A — Biologic risk, low structural risk",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    # Level 1 — tightened sensitivity
    mild_count = _mild_abnormalities_count(p)
    if (mild_count >= 2) or (mild_count >= 1 and len(enh) >= 1):
        triggers.append(f"≥2 mild abnormalities (count={mild_count})" if mild_count >= 2 else "Mild abnormality + enhancer")
        if enh:
            triggers.append("Enhancers: " + ", ".join(sorted(set(enh))))
        m = _meaning_and_posture(1, None)
        return {"level": 1, "sublevel": None, "label": "Level 1 — Early drift (low structural risk)",
                "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                "defaultPosture": m["posture"]}

    # Level 0 — optimal
    diabetes = (p.get("diabetes") is True) or (a1c_status(p) == "diabetes_range")
    if (not diabetes) and (p.get("smoking") is not True) and (len(enh) == 0):
        ok_lipids = False
        if apob is not None and apob < 80:
            ok_lipids = True
        if apob is None and ldl is not None and ldl < 100:
            ok_lipids = True
        if ok_lipids:
            if cac == 0:
                triggers.append("CAC=0")
            triggers.append("No enhancers; lipids optimal")
            m = _meaning_and_posture(0, None)
            return {"level": 0, "sublevel": None, "label": "Level 0 — Optimal / no major atherosclerotic signal",
                    "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
                    "defaultPosture": m["posture"]}

    # Fallback: Level 1
    triggers.append("Non-optimal signal(s) without higher-level criteria")
    if enh:
        triggers.append("Enhancers: " + ", ".join(sorted(set(enh))))
    m = _meaning_and_posture(1, None)
    return {"level": 1, "sublevel": None, "label": "Level 1 — Early drift (low structural risk)",
            "triggers": sorted(set(triggers)), "meaning": m["meaning"], "why": _humanize_triggers(triggers),
            "defaultPosture": m["posture"]}


# ----------------------------
# Targets + ESC + ACC + time horizon
# ----------------------------
def levels_targets(level: int, sublevel: Optional[str]) -> Dict[str, int]:
    if level <= 0:
        return {"apob": 80, "ldl": 100}
    if level == 1:
        return {"apob": 80, "ldl": 100}
    if level == 2:
        if sublevel in ("2B", "2C"):
            return {"apob": 70, "ldl": 70}
        return {"apob": 80, "ldl": 100}
    if level == 3:
        return {"apob": 70, "ldl": 70}
    if level == 4:
        return {"apob": 60, "ldl": 70}
    return {"apob": 55, "ldl": 55}

def esc_numeric_goals(level: int, sublevel: Optional[str]) -> str:
    if level >= 5:
        return "ESC/EAS goals (very high/extreme): LDL-C <55 mg/dL; ApoB <65 mg/dL (consider even lower in recurrent disease)."
    if level == 4:
        return "ESC/EAS goals: LDL-C <55 mg/dL; ApoB <65 mg/dL."
    if level == 3:
        return "ESC/EAS goals: LDL-C <70 mg/dL; ApoB <80 mg/dL."
    if level == 2:
        if sublevel in ("2B","2C"):
            return "ESC/EAS goals (often): treat more like high risk—consider LDL-C <70 mg/dL; ApoB <80 mg/dL when enhancers/CAC+ probability present."
        return "ESC/EAS goals (often): LDL-C <100 mg/dL; ApoB <100 mg/dL (tighten with enhancers/trajectory)."
    return "ESC/EAS goals: individualized by risk tier."

def acc_context(p: Patient, lvl: Dict[str, Any], risk10: Dict[str, Any]) -> str:
    if p.get("ascvd") is True:
        return "ACC/AHA context: Secondary prevention—high-intensity lipid lowering typical; add-on therapy considered when LDL-C remains ≥70 mg/dL despite statin."

    enh = []
    if premature_fhx(p): enh.append("FHx")
    if lpa_elevated(p): enh.append("Lp(a)")
    if inflammation_flags(p): enh.append("inflammation")
    if a1c_status(p) == "prediabetes": enh.append("prediabetes")
    if p.get("smoking") is True: enh.append("smoking")
    if p.get("diabetes") is True: enh.append("diabetes")
    enh_txt = (", ".join(enh)) if enh else "none identified"

    cac = safe_int(p.get("cac")) if p.has("cac") else None
    sub = lvl.get("sublevel")

    if cac == 0:
        if sub == "2B":
            return f"ACC/AHA context: Risk enhancers ({enh_txt}); CAC=0 lowers near-term risk but does not erase enhancer-driven lifetime risk—shared decision on intensity."
        return f"ACC/AHA context: Risk enhancers ({enh_txt}); CAC=0 supports staged escalation depending on preference and trajectory."
    if cac is not None and cac > 0:
        return f"ACC/AHA context: Risk enhancers ({enh_txt}); CAC>0 supports more intensive prevention."

    rp = risk10.get("risk_pct")
    if rp is not None:
        return f"ACC/AHA context: Risk enhancers ({enh_txt}); 10-year risk {rp}% ({risk10.get('category','')}); CAC can refine intensity."
    return f"ACC/AHA context: Risk enhancers ({enh_txt}); CAC can be used to refine intensity."

def time_horizon(p: Patient, lvl: Dict[str, Any]) -> str:
    if p.get("ascvd") is True:
        return "Time horizon: Near-term and lifetime risk elevated (clinical ASCVD)."

    sub = lvl.get("sublevel")
    if p.has("cac"):
        cac = safe_int(p.get("cac",0), default=0) or 0
        if cac == 0:
            if lvl["level"] >= 2 and sub in ("2A","2B","2C"):
                return "Time horizon: Near-term risk low (CAC=0); lifetime risk elevated (biology/enhancers)."
            return "Time horizon: Near-term risk low (CAC=0); lifetime risk likely low–moderate."
        if cac >= 100:
            return "Time horizon: Near-term and lifetime risk elevated (CAC≥100)."
        return "Time horizon: Near-term risk moderate; lifetime risk elevated (CAC>0)."

    if sub == "2B":
        return "Time horizon: Near-term risk uncertain (CAC unavailable); lifetime risk elevated (enhancers)."
    if sub in ("2A","2C"):
        return "Time horizon: Near-term risk uncertain (CAC unavailable); lifetime risk elevated (biology)."
    return "Time horizon: Indeterminate (CAC unavailable); interpret biology and risk estimate together."

def atherosclerotic_disease_burden(p: Patient) -> str:
    if p.get("ascvd") is True:
        return "Present (clinical ASCVD)"
    if p.has("cac"):
        cac = safe_int(p.get("cac", 0), default=0) or 0
        return "Not detected (CAC=0)" if cac == 0 else f"Present (CAC {cac})"
    return "Unknown (CAC not available)"

def completeness(p: Patient) -> Dict[str, Any]:
    key = ["apob","lpa","cac","hscrp","a1c","tc","hdl","sbp","bp_treated","smoking","diabetes","sex","race","age"]
    present = [k for k in key if p.has(k)]
    missing = [k for k in key if not p.has(k)]
    pct = int(round(100*(len(present)/len(key))))
    conf = "High" if pct >= 85 else ("Moderate" if pct >= 60 else "Low")
    return {"pct": pct, "confidence": conf, "top_missing": missing[:2], "missing": missing}

def top_drivers(p: Patient, lvl: Dict[str, Any]) -> List[str]:
    d: List[str] = []
    if lvl.get("level") == 2 and lvl.get("sublevel"):
        d.append(f"Level {lvl['sublevel']} pattern")

    if p.get("ascvd") is True:
        d.append("Clinical ASCVD")
    elif p.has("cac") and (safe_int(p.get("cac", 0), default=0) or 0) > 0:
        d.append(f"CAC {safe_int(p.get('cac'))}")

    apob = safe_float(p.get("apob"))
    ldl = safe_float(p.get("ldl"))

    if apob is not None and apob >= 90:
        d.append(f"ApoB {fmt_int(apob)}")
    elif ldl is not None and ldl >= 130:
        d.append(f"LDL-C {fmt_int(ldl)}")

    if lpa_elevated(p): d.append("Lp(a) elevated")
    if premature_fhx(p): d.append("Premature family history")
    if a1c_status(p) == "prediabetes": d.append("Prediabetes A1c")
    if inflammation_flags(p) or has_chronic_inflammatory_disease(p): d.append("Inflammatory signal")

    return d[:3]

def next_actions(p: Patient, lvl: Dict[str, Any], targets: Dict[str, int]) -> List[str]:
    acts: List[str] = []
    sub = lvl.get("sublevel")

    if p.has("apob") and fmt_int(p.get("apob")) > targets["apob"]:
        acts.append(f"Reduce ApoB toward <{targets['apob']} mg/dL.")
    if (not p.has("apob")) and p.has("ldl") and fmt_int(p.get("ldl")) > targets["ldl"]:
        acts.append(f"Reduce LDL-C toward <{targets['ldl']} mg/dL (or measure ApoB to guide intensity).")

    if p.has("cac"):
        cac = safe_int(p.get("cac"), default=0) or 0
        if cac == 0:
            if lvl["level"] == 2 and sub == "2C":
                acts.append("CAC=0 would typically de-risk near-term; reconcile with risk estimate and domains (consider repeat CAC 3–5y if risk persists).")
            elif lvl["level"] == 2 and sub == "2B":
                acts.append("CAC=0 lowers near-term risk; enhancer-driven lifetime risk persists—shared decision on pharmacotherapy and follow-up.")
            elif lvl["level"] >= 2:
                acts.append("CAC=0 supports staged escalation; consider repeat CAC in 3–5y if risk persists.")
    else:
        if lvl["level"] >= 2:
            acts.append("Consider CAC to clarify disease burden and refine intensity.")

    if lpa_elevated(p) and not p.has("apob"):
        acts.append("Lp(a) elevated: measure ApoB (preferred) or non–HDL-C to quantify atherogenic burden and guide intensity.")

    return acts[:2]


# ----------------------------
# Public API
# ----------------------------
def evaluate(p: Patient) -> Dict[str, Any]:
    risk10 = pooled_cohort_equations_10y_ascvd_risk(p)
    lvl = levels_band(p, risk10)
    rs  = risk_signal_score(p)
    t = levels_targets(lvl["level"], lvl.get("sublevel"))
    conf = completeness(p)
    burden = atherosclerotic_disease_burden(p)
    asp = aspirin_advice(p, risk10)

    return {
        "version": VERSION,
        "levels": lvl,
        "riskSignal": rs,
        "pooledCohortEquations10yAscvdRisk": risk10,
        "targets": t,
        "confidence": conf,
        "diseaseBurden": burden,
        "drivers": top_drivers(p, lvl),
        "nextActions": next_actions(p, lvl, t),
        "escGoals": esc_numeric_goals(lvl["level"], lvl.get("sublevel")),
        "accContext": acc_context(p, lvl, risk10),
        "timeHorizon": time_horizon(p, lvl),
        "aspirin": asp,
    }

def render_quick_text(p: Patient, out: Dict[str, Any]) -> str:
    lvl = out["levels"]
    rs = out["riskSignal"]
    risk10 = out["pooledCohortEquations10yAscvdRisk"]
    t = out["targets"]
    conf = out["confidence"]

    lines: List[str] = []
    lines.append(f"LEVELS™ {out['version']['levels']} — Quick Reference")

    if lvl.get("level") == 2 and lvl.get("sublevel"):
        lines.append(f"Level 2 ({lvl['sublevel']}): {lvl['label'].split('—',1)[1].strip()}")
    else:
        lines.append(f"Level {lvl['level']}: {lvl['label'].split('—',1)[1].strip()}")

    lines.append(f"Atherosclerotic disease burden: {out['diseaseBurden']}")
    miss = ", ".join(conf["top_missing"]) if conf["top_missing"] else "none"
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

    lines.append(f"Time horizon: {out['timeHorizon'].split(':',1)[1].strip() if out['timeHorizon'].startswith('Time horizon:') else out['timeHorizon']}")
    lines.append(f"ACC/AHA context: {out['accContext'].split(':',1)[1].strip() if out['accContext'].startswith('ACC/AHA context:') else out['accContext']}")

    if lvl.get("meaning"):
        lines.append(f"Meaning: {lvl['meaning']}")
    if lvl.get("defaultPosture"):
        lines.append(f"Default posture: {lvl['defaultPosture']}")

    if out["drivers"]:
        lines.append("Drivers: " + "; ".join(out["drivers"]))

    lines.append("Targets")
    if p.has("apob"):
        lines.append(f"• ApoB: {fmt_int(p.get('apob'))} mg/dL → target <{t['apob']} mg/dL")
    if p.has("ldl"):
        lines.append(f"• LDL-C: {fmt_int(p.get('ldl'))} mg/dL → target <{t['ldl']} mg/dL")

    above = False
    if p.has("apob") and fmt_int(p.get("apob")) > t["apob"]:
        above = True
    if (not p.has("apob")) and p.has("ldl") and fmt_int(p.get("ldl")) > t["ldl"]:
        above = True
    if above:
        lines.append("Benefit context: ~40 mg/dL ApoB/LDL reduction ≈ ~20–25% relative ASCVD event reduction over time (population data).")

    lines.append(out["escGoals"])

    if out["nextActions"]:
        lines.append("Next: " + " / ".join(out["nextActions"]))

    asp = out.get("aspirin", {})
    lines.append(f"Aspirin 81 mg: {asp.get('status','Not assessed')}")
    why = short_why(asp.get("rationale", []), max_items=2)
    if why:
        lines.append(f"Why: {why}")

    return "\n".join(lines)

