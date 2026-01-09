# levels_engine.py
# LEVELS v2.5 — Compact professional output + robust normalization + explicit Calcium Score handling
#
# Includes:
# - Levels 0–5 with Level 2A/2B/2C sublevels
# - Risk Signal Score (RSS)
# - Pooled Cohort Equations (10-year ASCVD risk)
# - Aspirin module with clean labels + rationale
# - ESC numeric goals + ACC context + time horizon (kept in JSON; shown in Full output)
#
# New in v2.5:
# - normalize_sex(), normalize_race() to accept F/M + other/white/black
# - PCE returns "not valid for age" note; compact output surfaces this
# - Calcium Score: 0 is valid and explicitly displayed
# - Compact text is a fixed, concise template (~10 lines)
# - Full text is optional drill-down

import math
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

VERSION = {
    "levels": "v2.5",
    "riskSignal": "RSS v1.0",
    "riskCalc": "Pooled Cohort Equations (ACC/AHA 2013; Race other→non-Black)",
    "aspirin": "Aspirin v1.1 (clean labels + rationale)",
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
# Normalization helpers
# ----------------------------
def normalize_sex(val: Any) -> str:
    s = str(val or "").strip().lower()
    if s in ("m", "male"):
        return "male"
    if s in ("f", "female"):
        return "female"
    # default to female if unknown (conservative for coefficient mapping consistency)
    return "female"

def normalize_race(val: Any) -> str:
    s = str(val or "").strip().lower()
    # Accept variants; "other" treated as non-Black coefficients
    if s in ("black", "african american", "african-american"):
        return "black"
    return "white"

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

def lpa_elevated(p: Patient) -> bool:
    if not p.has("lpa"):
        return False
    v = safe_float(p.get("lpa", 0), default=0.0)
    unit = str(p.get("lpa_unit", "")).lower()
    if "mg" in unit:
        return v >= 50
    return v >= 125

def premature_fhx(p: Patient) -> bool:
    # Backward compatible
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
    if rel and rel not in ("father", "mother", "brother", "sister", "son", "daughter", "parent", "sibling", "child"):
        return False

    if is_male and age_evt < 55: return True
    if (not is_male) and age_evt < 65: return True
    return False

def metabolic_syndrome(p: Patient) -> bool:
    if p.get("metabolic_syndrome") is True:
        return True
    tg = safe_float(p.get("tg"))
    hdl = safe_float(p.get("hdl"))
    treated_htn = bool(p.get("bp_treated")) is True
    a1 = a1c_status(p)

    criteria = 0
    if tg is not None and tg >= 150: criteria += 1
    if hdl is not None:
        male = normalize_sex(p.get("sex")) == "male"
        if (male and hdl < 40) or ((not male) and hdl < 50):
            criteria += 1
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
    if metabolic_syndrome(p): enh.append("metabolic_syndrome")
    tg = safe_float(p.get("tg"))
    if tg is not None and tg >= 175: enh.append("TG≥175")
    return enh


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

def risk_signal_score(p: Patient) -> Dict[str, Any]:
    burden = 0
    if p.get("ascvd") is True:
        burden = 55
    elif p.has("cac"):
        cac = safe_int(p.get("cac", 0), default=0)
        # IMPORTANT: CAC=0 is valid
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

    total = clamp(int(burden + athero + genetics + infl + metab))
    return {"score": total, "band": rss_band(total), "note": "Not an event probability (biologic + plaque signal)."}


# ----------------------------
# Pooled Cohort Equations (10-year ASCVD risk)
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
        return {"risk_pct": None, "missing": missing, "notes": None}

    age = int(p.get("age"))
    if age < 40 or age > 79:
        return {"risk_pct": None, "missing": [], "notes": f"PCE not valid for age {age} (valid 40–79)."}

    sex_key = normalize_sex(p.get("sex"))
    race_key = normalize_race(p.get("race"))

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

    return {"risk_pct": risk_pct, "category": cat, "missing": [], "notes": "Population estimate (does not include Calcium Score/ApoB/Lp(a))."}


# ----------------------------
# Aspirin module
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

    if ascvd:
        if bleed_flags:
            return {"status": "Consider aspirin (shared decision)",
                    "rationale": ["Clinical ASCVD present"] + ["Bleeding risk flags: " + "; ".join(bleed_flags)]}
        return {"status": "Recommend aspirin",
                "rationale": ["Clinical ASCVD present (no bleeding risk flags identified)"]}

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
        if cac_ok: reasons.append("Calcium Score ≥100")
        if risk_ok: reasons.append(f"PCE 10-year risk ≥10% ({risk_pct}%)")
        return {"status": "Consider aspirin (shared decision)",
                "rationale": reasons + ["Bleeding risk low by available flags"]}

    return {"status": "Would not recommend aspirin",
            "rationale": ["Primary prevention benefit likely small at current risk level"]}


# ----------------------------
# Levels logic (unchanged behavior, compact explanations)
# ----------------------------
def _domains_abnormal(p: Patient) -> int:
    domains = 0
    apob = safe_float(p.get("apob"))
    ldl = safe_float(p.get("ldl"))
    if apob is not None and apob >= 90:
        domains += 1
    elif apob is None and ldl is not None and ldl >= 130:
        domains += 1

    sbp = safe_float(p.get("sbp"))
    if sbp is not None and sbp >= 130:
        domains += 1
    if p.get("bp_treated") is True:
        domains += 1

    if p.get("diabetes") is True:
        domains += 1
    else:
        a1 = a1c_status(p)
        a1c = safe_float(p.get("a1c"))
        if a1 == "prediabetes" and a1c is not None and a1c >= 6.0:
            domains += 1

    return min(domains, 3)

def _mild_abnormalities_count(p: Patient) -> int:
    count = 0
    apob = safe_float(p.get("apob"))
    ldl = safe_float(p.get("ldl"))
    sbp = safe_float(p.get("sbp"))
    a1c = safe_float(p.get("a1c"))
    tg = safe_float(p.get("tg"))

    if apob is not None and 80 <= apob <= 89: count += 1
    if apob is None and ldl is not None and 100 <= ldl <= 129: count += 1
    if sbp is not None and 130 <= sbp <= 139: count += 1
    if p.get("bp_treated") is True: count += 1
    if a1c is not None and 5.7 <= a1c <= 5.9: count += 1
    if tg is not None and 150 <= tg <= 199: count += 1
    return count

def levels_band(p: Patient, risk10: Dict[str, Any]) -> Dict[str, Any]:
    cac = safe_int(p.get("cac")) if p.has("cac") else None
    apob = safe_float(p.get("apob")) if p.has("apob") else None
    ldl = safe_float(p.get("ldl")) if p.has("ldl") else None
    a1c = safe_float(p.get("a1c")) if p.has("a1c") else None
    pce = risk10.get("risk_pct")
    enh = enhancer_list(p)

    # Level 5 (optional flags)
    if p.get("ascvd") is True and any(p.get(k) is True for k in ["recurrent_ascvd", "polyvascular", "event_on_therapy"]):
        return {"level": 5, "sublevel": None, "label": "Level 5 — Extreme / progressive ASCVD risk",
                "meaning": "Extreme/progressive ASCVD risk.", "why": ["Progressive ASCVD features"], "defaultPosture": "Maximal risk reduction strategy."}

    # Level 4
    if p.get("ascvd") is True:
        return {"level": 4, "sublevel": None, "label": "Level 4 — Clinical ASCVD / risk-equivalent disease",
                "meaning": "Clinical ASCVD or risk-equivalent.", "why": ["Clinical ASCVD"], "defaultPosture": "High-intensity lipid lowering typical."}

    if ldl is not None and ldl >= 190:
        return {"level": 4, "sublevel": None, "label": "Level 4 — Severe hypercholesterolemia (risk-equivalent)",
                "meaning": "Very high LDL-C (risk-equivalent).", "why": ["LDL-C ≥190 mg/dL"], "defaultPosture": "Treat aggressively; consider FH."}

    # Level 3
    if cac is not None and cac >= 100:
        return {"level": 3, "sublevel": None, "label": "Level 3 — Subclinical atherosclerotic disease (imaging+)",
                "meaning": "Subclinical atherosclerosis established.", "why": [f"Calcium Score {cac}"], "defaultPosture": "Secondary-prevention mindset."}

    if cac is not None and 1 <= cac <= 99:
        return {"level": 2, "sublevel": "2C", "label": "Level 2C — Silent disease probability",
                "meaning": "Higher probability of silent disease.", "why": [f"Calcium Score {cac}"], "defaultPosture": "Treat like early disease; statin default."}

    domains = _domains_abnormal(p)
    if pce is not None and pce >= 7.5 and domains >= 2:
        return {"level": 2, "sublevel": "2C", "label": "Level 2C — Silent disease probability",
                "meaning": "Higher probability of silent disease.", "why": [f"PCE {pce}% + multi-domain"], "defaultPosture": "Treat like early disease; statin default."}

    # 2B enhancers
    discordance = (apob is not None and apob >= 90 and ldl is not None and ldl < 100)
    reasons = []
    if lpa_elevated(p): reasons.append("Lp(a) elevated")
    if premature_fhx(p): reasons.append("Premature family history")
    if has_chronic_inflammatory_disease(p): reasons.append("Inflammatory disease")
    if p.get("ckd") is True: reasons.append("CKD")
    if discordance: reasons.append("ApoB discordance")

    if reasons:
        return {"level": 2, "sublevel": "2B", "label": "Level 2B — Enhancer-driven acceleration",
                "meaning": "Enhancer-driven lifetime risk.", "why": reasons[:3], "defaultPosture": "Statin favored; refine with Calcium Score if unknown."}

    # 2A biologic risk
    why = []
    if apob is not None and 90 <= apob <= 99: why.append("ApoB 90–99")
    if ldl is not None and 130 <= ldl <= 159: why.append("LDL-C 130–159")
    if a1c is not None and 6.0 <= a1c < 6.5: why.append("A1c 6.0–6.4")
    if metabolic_syndrome(p): why.append("Metabolic syndrome")
    if pce is not None and 5.0 <= pce < 20.0: why.append(f"PCE {pce}%")

    if why:
        return {"level": 2, "sublevel": "2A", "label": "Level 2A — Biologic risk, low structural risk",
                "meaning": "Biologic risk present; structure not established.", "why": why[:3], "defaultPosture": "Lifestyle + shared med decision."}

    # Level 1 tightened
    mild = _mild_abnormalities_count(p)
    if mild >= 2 or (mild >= 1 and len(enh) >= 1):
        return {"level": 1, "sublevel": None, "label": "Level 1 — Early drift (low structural risk)",
                "meaning": "Early drift without proof of plaque.", "why": ["Clustered mild signals"], "defaultPosture": "Lifestyle-first; confirm/track trend."}

    # Level 0
    diabetes = (p.get("diabetes") is True) or (a1c_status(p) == "diabetes_range")
    if (not diabetes) and (p.get("smoking") is not True) and (len(enh) == 0):
        ok_lipids = False
        if apob is not None and apob < 80: ok_lipids = True
        if apob is None and ldl is not None and ldl < 100: ok_lipids = True
        if ok_lipids:
            return {"level": 0, "sublevel": None, "label": "Level 0 — Optimal / no major atherosclerotic signal",
                    "meaning": "No major risk signal detected.", "why": ["Optimal profile"], "defaultPosture": "Maintain habits; periodic re-check."}

    return {"level": 1, "sublevel": None, "label": "Level 1 — Early drift (low structural risk)",
            "meaning": "Non-optimal or incomplete data.", "why": ["Incomplete/uncertain"], "defaultPosture": "Lifestyle-first; fill gaps."}


# ----------------------------
# Targets + context
# ----------------------------
def levels_targets(level: int, sublevel: Optional[str]) -> Dict[str, int]:
    if level <= 1:
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
    if level >= 4:
        return "ESC/EAS goals: LDL-C <55 mg/dL; ApoB <65 mg/dL."
    if level == 3:
        return "ESC/EAS goals: LDL-C <70 mg/dL; ApoB <80 mg/dL."
    if level == 2 and sublevel in ("2B","2C"):
        return "ESC/EAS goals (often): consider LDL-C <70 mg/dL; ApoB <80 mg/dL."
    if level == 2:
        return "ESC/EAS goals (often): LDL-C <100 mg/dL; ApoB <100 mg/dL."
    return "ESC/EAS goals: individualized by risk tier."

def acc_context(p: Patient, lvl: Dict[str, Any], risk10: Dict[str, Any]) -> str:
    if p.get("ascvd") is True:
        return "ACC/AHA: Secondary prevention; high-intensity lipid lowering typical; add-ons if LDL-C ≥70 on statin."
    enh = []
    if premature_fhx(p): enh.append("FHx")
    if lpa_elevated(p): enh.append("Lp(a)")
    if has_chronic_inflammatory_disease(p): enh.append("inflammation")
    if p.get("diabetes") is True: enh.append("diabetes")
    enh_txt = ", ".join(enh) if enh else "none identified"

    cac = safe_int(p.get("cac")) if p.has("cac") else None
    if cac == 0:
        return f"ACC/AHA: enhancers({enh_txt}); Calcium Score=0 supports staged escalation."
    if cac is not None and cac > 0:
        return f"ACC/AHA: enhancers({enh_txt}); Calcium Score>0 supports more intensive prevention."
    rp = risk10.get("risk_pct")
    if rp is not None:
        return f"ACC/AHA: enhancers({enh_txt}); PCE {rp}%—Calcium Score can refine intensity."
    notes = risk10.get("notes")
    if notes:
        return f"ACC/AHA: enhancers({enh_txt}); {notes}"
    return f"ACC/AHA: enhancers({enh_txt}); Calcium Score can refine intensity."

def time_horizon(p: Patient, lvl: Dict[str, Any]) -> str:
    if p.get("ascvd") is True:
        return "Near-term + lifetime risk elevated (clinical ASCVD)."
    if p.has("cac"):
        cac = safe_int(p.get("cac",0), default=0)
        if cac == 0:
            return "Near-term risk low (Calcium Score=0); lifetime risk depends on biology/enhancers."
        if cac >= 100:
            return "Near-term + lifetime risk elevated (Calcium Score≥100)."
        return "Near-term risk moderate; lifetime risk elevated (Calcium Score>0)."
    return "Time horizon: Calcium Score unavailable; interpret biology + risk estimate together."

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
        d.append(f"Level {lvl['sublevel']}")
    if p.has("cac"):
        d.append(f"Calcium Score {safe_int(p.get('cac',0), default=0)}")
    apob = safe_float(p.get("apob"))
    ldl = safe_float(p.get("ldl"))
    if apob is not None and apob >= 90: d.append(f"ApoB {fmt_int(apob)}")
    elif ldl is not None and ldl >= 130: d.append(f"LDL-C {fmt_int(ldl)}")
    if lpa_elevated(p): d.append("Lp(a)+")
    if premature_fhx(p): d.append("FHx+")
    return d[:3]

def next_actions(p: Patient, lvl: Dict[str, Any], targets: Dict[str, int]) -> List[str]:
    acts: List[str] = []
    if p.has("apob") and fmt_int(p.get("apob")) > targets["apob"]:
        acts.append(f"Lower ApoB to <{targets['apob']} mg/dL.")
    elif p.has("ldl") and fmt_int(p.get("ldl")) > targets["ldl"]:
        acts.append(f"Lower LDL-C to <{targets['ldl']} mg/dL (or check ApoB).")
    if (not p.has("cac")) and int(lvl.get("level", 0) or 0) >= 2:
        acts.append("Consider Calcium Score to refine intensity.")
    return acts[:2]


# ----------------------------
# Renderers (compact + full)
# ----------------------------
def render_compact_text(p: Patient, out: Dict[str, Any]) -> str:
    """
    Locked compact template (~10 lines) for real clinical use.
    """
    lvl = out["levels"]
    risk10 = out["pooledCohortEquations10yAscvdRisk"]
    rs = out["riskSignal"]
    t = out["targets"]
    asp = out.get("aspirin", {})
    conf = out.get("confidence", {})

    # Level display
    lvl_disp = f"{lvl.get('level','—')}"
    if int(lvl.get("level", 0) or 0) == 2 and lvl.get("sublevel"):
        lvl_disp += f" ({lvl.get('sublevel')})"

    # Calcium Score display (0 is valid)
    if p.get("ascvd") is True:
        cs = "N/A (clinical ASCVD)"
    elif p.has("cac"):
        cs = str(safe_int(p.get("cac"), default=0))
    else:
        cs = "Not available"

    # PCE display
    if risk10.get("risk_pct") is not None:
        pce = f"{risk10['risk_pct']}% ({risk10.get('category','')})"
    else:
        # show missing vs age-invalid
        if risk10.get("notes"):
            pce = risk10["notes"]
        elif risk10.get("missing"):
            pce = "Not calculated (missing inputs)"
        else:
            pce = "Not calculated"

    drivers = out.get("drivers") or []
    plan = out.get("nextActions") or []

    asp_status = asp.get("status", "Not assessed")
    asp_why = short_why(asp.get("rationale", []), max_items=2)

    miss = ", ".join(conf.get("top_missing", []) or [])

    lines = [
        f"LEVELS™ {out['version']['levels']}",
        f"Assessment: Level {lvl_disp} — {lvl.get('label','')}",
        f"Calcium Score: {cs}",
        f"10-year ASCVD (PCE): {pce}",
        f"Risk Signal Score: {rs.get('score','—')}/100 ({rs.get('band','')})",
        f"Drivers: {'; '.join(drivers) if drivers else '—'}",
        f"Targets: ApoB <{t['apob']} mg/dL; LDL-C <{t['ldl']} mg/dL",
        f"Plan: {' / '.join(plan) if plan else '—'}",
        f"Aspirin: {asp_status}" + (f" — Why: {asp_why}" if asp_why else ""),
        f"Data quality: {conf.get('confidence','—')} ({conf.get('pct','—')}%)" + (f" — Missing: {miss}" if miss else ""),
    ]
    return "\n".join(lines)

def render_full_text(p: Patient, out: Dict[str, Any]) -> str:
    """
    Optional drill-down (still clean) with interpretive context.
    """
    lvl = out["levels"]
    lines = [render_compact_text(p, out), ""]
    lines.append(f"Time horizon: {out.get('timeHorizon','')}")
    lines.append(f"ACC/AHA context: {out.get('accContext','')}")
    lines.append(out.get("escGoals",""))
    if lvl.get("meaning"):
        lines.append(f"Meaning: {lvl['meaning']}")
    if lvl.get("defaultPosture"):
        lines.append(f"Default posture: {lvl['defaultPosture']}")
    return "\n".join(lines)

# Backward compatibility for older UI calls
def render_quick_text(p: Patient, out: Dict[str, Any]) -> str:
    return render_compact_text(p, out)


# ----------------------------
# Public API
# ----------------------------
def evaluate(p: Patient) -> Dict[str, Any]:
    # Normalize sex/race once for safety, without changing user input fields
    d = dict(p.data)
    if "sex" in d:
        d["sex"] = normalize_sex(d["sex"])
    if "race" in d:
        d["race"] = normalize_race(d["race"])
    p = Patient(d)

    risk10 = pooled_cohort_equations_10y_ascvd_risk(p)
    lvl = levels_band(p, risk10)
    rs  = risk_signal_score(p)
    t = levels_targets(lvl["level"], lvl.get("sublevel"))
    conf = completeness(p)
    asp = aspirin_advice(p, risk10)

    return {
        "version": VERSION,
        "levels": lvl,
        "riskSignal": rs,
        "pooledCohortEquations10yAscvdRisk": risk10,
        "targets": t,
        "confidence": conf,
        "drivers": top_drivers(p, lvl),
        "nextActions": next_actions(p, lvl, t),
        "escGoals": esc_numeric_goals(lvl["level"], lvl.get("sublevel")),
        "accContext": acc_context(p, lvl, risk10),
        "timeHorizon": time_horizon(p, lvl),
        "aspirin": asp,
    }

