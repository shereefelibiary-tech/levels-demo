# levels_engine.py
# LEVELS v1.4.1 — Quick mode fixes + explicit ESC numeric goals

import math
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

VERSION = {
    "levels": "v1.4.1",
    "risk_signal": "RSS v1.0",
    "pce": "Pooled Cohort Equations (ACC/AHA 2013; Race other->non-Black)",
    "aspirin": "Aspirin v1.0 (CAC≥100 OR 10y risk≥10%, age 40–69, low bleed risk)"
}

@dataclass
class Patient:
    data: Dict[str, Any]
    def get(self, k, d=None): return self.data.get(k, d)
    def has(self, k): return k in self.data and self.data[k] is not None

# --- helpers ---
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

# --- RSS ---
def _clamp(x: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, x))

def _rss_band(score: int) -> str:
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
        cac = int(p.get("cac", 0))
        if cac == 0: burden = 0
        elif 1 <= cac <= 9: burden = 20
        elif 10 <= cac <= 99: burden = 30
        elif 100 <= cac <= 399: burden = 45
        else: burden = 55

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

    infl = 0
    if p.has("hscrp"):
        h = float(p.get("hscrp", 0))
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

    total = _clamp(burden + athero + genetics + infl + metab)
    return {
        "score": total,
        "band": _rss_band(total),
        "note": "Not an event probability.",
    }

# --- Pooled Cohort Equations (kept from v1.4) ---
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

# --- Aspirin uses existing function in v1.4; omitted here for brevity in this snippet ---
# If you want, we can keep aspirin module in full; but since you already have it, we can keep the prior version.
# For now, keep a simple line:
def aspirin_status_simple(p: Patient, risk10: Dict[str, Any]) -> str:
    if p.get("ascvd") is True: return "Secondary prevention: typically indicated if no contraindication"
    if p.has("cac") and int(p.get("cac",0)) >= 100: return "Consider (shared decision) if bleeding risk low"
    if risk10.get("risk_pct") is not None and risk10["risk_pct"] >= 10: return "Consider (shared decision) if bleeding risk low"
    if p.has("cac") and int(p.get("cac",0)) == 0: return "Avoid (primary prevention; CAC=0)"
    return "Avoid / individualize"

# --- Levels band + targets ---
def levels_band(p: Patient) -> Dict[str, Any]:
    triggers=[]; level=0
    if p.get("ascvd") is True: level=4; triggers.append("ASCVD")
    if p.has("cac") and int(p.get("cac",0))>=100: level=max(level,4); triggers.append("CAC>=100")
    if p.has("cac") and int(p.get("cac",0))>0: level=max(level,3); triggers.append("CAC>0")
    if level<3:
        if p.has("apob") and float(p.get("apob",0))>=100: level=2; triggers.append("ApoB>=100")
        if p.has("ldl") and float(p.get("ldl",0))>=130: level=2; triggers.append("LDL>=130")
        if lpa_elevated(p): level=2; triggers.append("Lp(a) elevated")
        if p.get("fhx") is True: level=2; triggers.append("FHx_premature")
        if a1c_status(p)=="prediabetes": triggers.append("Prediabetes_A1c")
        if inflammation_flags(p) or has_chronic_inflammatory_disease(p): triggers.append("Inflammation_present")
    if level==0 and p.data: level=1; triggers.append("Any_risk_signal_present")
    labels={0:"Level 0 — No atherosclerotic risk detected",1:"Level 1 — Mild biologic risk (no disease)",2:"Level 2 — High biologic risk (disease not yet proven)",3:"Level 3 — Subclinical atherosclerotic disease",4:"Level 4 — Advanced / clinical atherosclerotic disease"}
    return {"level":level,"label":labels[level],"triggers":sorted(set(triggers))}

def levels_targets(level:int)->Dict[str,int]:
    if level<=1: return {"apob":80,"ldl":100}
    if level==2: return {"apob":80,"ldl":100}
    if level==3: return {"apob":70,"ldl":70}
    return {"apob":60,"ldl":70}

def esc_numeric_goals(level:int)->str:
    # High-yield numeric goals (ESC-style)
    if level>=4:
        return "ESC/EAS goals: LDL-C <55 mg/dL; ApoB <65 mg/dL (very high risk)."
    if level==3:
        return "ESC/EAS goals: LDL-C <70 mg/dL; ApoB <80 mg/dL (high risk)."
    return "ESC/EAS goals: risk-category dependent; use biology + burden to individualize."

def atherosclerotic_disease_burden(p: Patient)->str:
    if p.get("ascvd") is True: return "Present (clinical ASCVD)"
    if p.has("cac"):
        cac=int(p.get("cac",0))
        if cac==0: return "Not detected (CAC=0)"
        return f"Present (CAC {cac})"
    return "Unknown (CAC not available)"

def top3_drivers(p: Patient)->List[str]:
    d=[]
    if p.get("ascvd") is True: d.append("Clinical ASCVD")
    elif p.has("cac") and int(p.get("cac",0))>0: d.append(f"CAC {int(p.get('cac'))}")
    if p.has("apob") and float(p.get("apob",0))>=100: d.append(f"ApoB {int(round(float(p.get('apob'))))}")
    elif p.has("ldl") and float(p.get("ldl",0))>=130: d.append(f"LDL-C {int(round(float(p.get('ldl'))))}")
    if lpa_elevated(p): d.append("Lp(a) elevated")
    if p.get("fhx") is True: d.append("Premature family history")
    if a1c_status(p)=="prediabetes": d.append("Prediabetes A1c")
    if inflammation_flags(p) or has_chronic_inflammatory_disease(p): d.append("Inflammatory signal")
    return d[:3]

def next_actions(p: Patient, level:int, targets:Dict[str,int])->List[str]:
    acts=[]
    if p.has("apob"):
        ap=int(round(float(p.get("apob"))))
        gap=ap-targets["apob"]
        if gap>0: acts.append(f"Reduce ApoB toward <{targets['apob']} (Δ ~{gap}).")
    elif p.has("ldl"):
        ld=int(round(float(p.get("ldl"))))
        gap=ld-targets["ldl"]
        if gap>0: acts.append(f"Reduce LDL-C toward <{targets['ldl']} (Δ ~{gap}).")
    if p.has("cac") and int(p.get("cac"))==0 and level==2:
        acts.append("Given CAC=0, staged escalation reasonable; consider repeat CAC in 3–5y if risk persists.")
    elif not p.has("cac") and level>=2:
        acts.append("Consider CAC to clarify disease burden and refine intensity.")
    return acts[:2]

def completeness(p: Patient)->Dict[str,Any]:
    key=["apob","lpa","cac","hscrp","a1c","tc","hdl","sbp","bp_treated","smoking","diabetes","sex","race","age"]
    present=[k for k in key if p.has(k)]
    missing=[k for k in key if not p.has(k)]
    pct=int(round(100*(len(present)/len(key))))
    conf="High" if pct>=85 else ("Moderate" if pct>=60 else "Low")
    return {"pct":pct,"confidence":conf,"top_missing":missing[:2], "missing":missing}

def evaluate(p: Patient)->Dict[str,Any]:
    lvl=levels_band(p)
    rs=risk_signal_score(p)
    risk10=pooled_cohort_equations_10y_ascvd_risk(p)
    t=levels_targets(lvl["level"])
    conf=completeness(p)
    burden=atherosclerotic_disease_burden(p)
    return {
        "version": VERSION,
        "levels": lvl,
        "risk_signal": rs,
        "risk10": risk10,
        "targets": t,
        "confidence": conf,
        "burden": burden,
        "drivers": top3_drivers(p),
        "actions": next_actions(p, lvl["level"], t),
        "esc_goals": esc_numeric_goals(lvl["level"]),
        "aspirin": aspirin_status_simple(p, risk10),
    }

def render_note_quick(p: Patient, out: Dict[str,Any])->str:
    lvl=out["levels"]; rs=out["risk_signal"]; risk10=out["risk10"]; t=out["targets"]; conf=out["confidence"]
    lines=[]
    # include numeric Level
    lines.append(f"LEVELS™ {out['version']['levels']} — Quick Reference")
    lines.append(f"Level {lvl['level']}: {lvl['label'].split('—',1)[1].strip()}")
    lines.append(f"Atherosclerotic disease burden: {out['burden']}")
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
    if out["drivers"]:
        lines.append("Drivers: " + "; ".join(out["drivers"]))
    # targets line includes level target + ESC numeric goal line
    delta_ap = max(0, int(round(float(p.get("apob",0)))) - t["apob"]) if p.has("apob") else None
    delta_ld = max(0, int(round(float(p.get("ldl",0)))) - t["ldl"]) if p.has("ldl") else None
    deltas=[]
    if delta_ap is not None: deltas.append(f"ΔApoB {delta_ap}")
    if delta_ld is not None: deltas.append(f"ΔLDL {delta_ld}")
    lines.append(f"Targets (Levels): ApoB<{t['apob']} | LDL<{t['ldl']}  ({' | '.join(deltas)})")
    lines.append(out["esc_goals"])
    if out["actions"]:
        lines.append("Next: " + " / ".join(out["actions"]))
    lines.append(f"Aspirin 81 mg: {out['aspirin']}")
    return "\n".join(lines)

def render_note_full(p: Patient, out: Dict[str,Any])->str:
    # for now, full = quick + triggers
    q = render_note_quick(p, out)
    return q + "\n\nTriggers: " + ", ".join(out["levels"]["triggers"])

