# levels_engine.py
# LEVELS v1.1 — Polished output on top of stable core parsing
# CAC > 0 => Level 3 disease boundary
# FHx line presence => True unless explicitly "no"
# Adds: badge, ACC/ESC qualitative, overlays, intermediate zone, polished note

import re
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

@dataclass
class Patient:
    data: Dict[str, Any]
    def get(self, k, d=None): return self.data.get(k, d)
    def has(self, k): return k in self.data

LINE = re.compile(r"^\s*([^:]+?)\s*:\s*(.*?)\s*$", re.IGNORECASE)

def _num_first(s: str) -> Optional[float]:
    m = re.search(r"-?\d+(?:\.\d+)?", s or "")
    if not m: return None
    try: return float(m.group(0))
    except: return None

def parse_levels_smartphrase(text: str) -> Patient:
    d = {}
    for line in (text or "").splitlines():
        m = LINE.match(line)
        if not m: 
            continue
        label = (m.group(1) or "").lower()
        value_raw = (m.group(2) or "").strip()
        value = value_raw.lower()

        # FHx: present unless explicitly "no"
        if "family history" in label:
            d["fhx"] = not value.startswith("n")
            continue

        if label.startswith("ascvd"):
            d["ascvd"] = value.startswith("y")
            continue

        if label.startswith("ldl"):
            v=_num_first(value_raw); 
            if v is not None: d["ldl"]=v
            continue

        if "apob" in label:
            v=_num_first(value_raw); 
            if v is not None: d["apob"]=v
            continue

        if "lp(a" in label:
            v=_num_first(value_raw); 
            if v is not None: d["lpa"]=v
            # unit hint
            if "nmol" in value: d["lpa_unit"]="nmol/L"
            elif "mg" in value: d["lpa_unit"]="mg/dL"
            continue

        if "hscrp" in label:
            v=_num_first(value_raw); 
            if v is not None: d["hscrp"]=v
            continue

        if label.startswith("cac"):
            v=_num_first(value_raw); 
            if v is not None: d["cac"]=int(v)
            continue

        # Optional extras
        if label.startswith("diabetes"):
            d["diabetes"] = value.startswith("y")
            continue
        if label.startswith("smoking"):
            d["smoking"] = value.startswith("y")
            continue
        if label == "age":
            v=_num_first(value_raw)
            if v is not None: d["age"]=int(v)
            continue

    return Patient(d)

# ----------------------------
# Helpers (safe, simple)
# ----------------------------

def lpa_elevated(p: Patient) -> bool:
    if not p.has("lpa"): return False
    v=float(p.get("lpa",0))
    unit=str(p.get("lpa_unit","")).lower()
    if "mg" in unit: return v>=50
    return v>=125

def inflammation_flags(p: Patient) -> List[str]:
    flags=[]
    if p.has("hscrp") and float(p.get("hscrp",0))>=2:
        flags.append("hsCRP>=2")
    return flags

def lifetime_signal(level:int)->str:
    return {0:"Low",1:"Mildly elevated",2:"Elevated",3:"High",4:"Very high"}[level]

def substrate_status(p: Patient)->str:
    if p.has("cac"):
        cac=int(p.get("cac",0))
        return f"Present (CAC {cac})" if cac>0 else "Not demonstrated (CAC 0)"
    return "Unknown (no CAC on file)"

def near_term_signal(p: Patient)->str:
    if p.has("cac"):
        cac=int(p.get("cac",0))
        if cac==0: return "Low"
        if cac>=100: return "High"
        return "Moderate"
    return "Indeterminate"

def acc_lines(p: Patient, level:int)->List[str]:
    lines=[]
    if p.get("ascvd") is True:
        lines.append("ACC/AHA: Secondary prevention — high-intensity risk reduction typical.")
        return lines

    if level<=1:
        lines.append("ACC/AHA: Primary prevention — optimize risk factors; meds often shared decision.")
    elif level==2:
        lines.append("ACC/AHA: Primary prevention — risk enhancers present; pharmacotherapy often reasonable; confirm substrate if needed.")
    elif level==3:
        lines.append("ACC/AHA: Primary prevention — confirmed subclinical disease; more intensive prevention typical.")
    else:
        lines.append("ACC/AHA: High-risk primary prevention / disease-equivalent; very intensive prevention typical.")

    if p.has("cac"):
        cac=int(p.get("cac",0))
        if cac==0: lines.append("  - CAC=0 supports de-escalation when uncertain.")
        elif cac<100: lines.append("  - CAC>0 confirms subclinical disease.")
        else: lines.append("  - CAC≥100 indicates high-burden subclinical disease.")

    enh=[]
    if p.get("fhx") is True: enh.append("Premature family history")
    if lpa_elevated(p): enh.append("Lp(a) elevated")
    if inflammation_flags(p): enh.append("Inflammatory state (hsCRP/inflammatory disease)")
    if p.get("smoking") is True: enh.append("Smoking")
    if p.get("diabetes") is True: enh.append("Diabetes")
    if enh:
        lines.append("  - Risk enhancers: " + ", ".join(enh))
    return lines

def esc_line(p: Patient, level:int)->str:
    if p.get("ascvd") is True:
        return "ESC/EAS: Very high risk — clinical ASCVD."
    if level>=4:
        return "ESC/EAS: Very high risk — advanced disease burden (e.g., CAC≥100)."
    if level==3:
        return "ESC/EAS: High risk — subclinical disease present (CAC>0)."
    if level==2:
        return "ESC/EAS: Moderate–high risk — high biologic risk without proven substrate (formal SCORE2 optional)."
    if level==1:
        return "ESC/EAS: Low–moderate risk — mild biologic risk without disease (formal SCORE2 optional)."
    return "ESC/EAS: Low risk — favorable profile (if otherwise healthy)."

# ----------------------------
# Levels engine (0–4) + overlays + intermediate zone
# ----------------------------

def evaluate_levels_banded(p: Patient) -> Dict[str, Any]:
    triggers=[]
    overlays={}
    level=0

    # Level 4: clinical ASCVD OR CAC>=100
    if p.get("ascvd") is True:
        level=4; triggers.append("ASCVD")
    if p.has("cac") and int(p.get("cac",0))>=100:
        level=max(level,4); triggers.append("CAC>=100")

    # Level 3: CAC>0 boundary
    if p.has("cac") and int(p.get("cac",0))>0:
        level=max(level,3); triggers.append("CAC>0")

    # Level 2: biology (if no disease)
    if level<3:
        if float(p.get("apob",0))>=100:
            level=2; triggers.append("ApoB>=100")
        if float(p.get("ldl",0))>=130:
            level=2; triggers.append("LDL>=130")
        if lpa_elevated(p):
            level=2; triggers.append("Lp(a)>=threshold")
        if p.get("fhx") is True:
            level=2; triggers.append("FHx_premature")

    # Level 1: any signal present
    if level==0 and p.data:
        level=1; triggers.append("Any_risk_signal_present")

    # Overlays
    infl=inflammation_flags(p)
    if infl:
        overlays["inflammatory_overlay"]=infl
        triggers.append("Inflammation_present")
    if lpa_elevated(p):
        overlays["genetic_overlay"]="Lp(a) elevated"
        triggers.append("Lp(a)_elevated")
    accelerated=(len(infl)>0 and level in (1,2))

    # Intermediate zone (simple)
    intermediate=False
    inter_reasons=[]
    next_steps=[]
    if level<=2 and (float(p.get("apob",0))>=100 or float(p.get("ldl",0))>=130 or lpa_elevated(p) or p.get("fhx") is True):
        if not p.has("cac"):
            intermediate=True
            inter_reasons.append("Elevated biologic risk without CAC substrate assessment")
            next_steps.append("Order CAC for substrate confirmation (if appropriate)")
        elif p.get("cac",0)==0 and (float(p.get("apob",0))>=120 or float(p.get("ldl",0))>=160 or (lpa_elevated(p) and p.get("fhx") is True)):
            intermediate=True
            inter_reasons.append("Discordant: CAC=0 with high biologic risk; confirm persistence and reassess")
            next_steps += [
                "Repeat fasting lipids + ApoB to confirm persistence",
                "Evaluate secondary contributors as clinically appropriate",
                "Consider repeat CAC in ~3–5 years (or sooner if risk changes)"
            ]

    labels={
        0:"Level 0 — No atherosclerotic risk detected",
        1:"Level 1 — Mild biologic risk (no disease)",
        2:"Level 2 — High biologic risk (disease not yet proven)",
        3:"Level 3 — Subclinical atherosclerotic disease",
        4:"Level 4 — Advanced / clinical atherosclerotic disease",
    }

    return {
        "level": level,
        "label": labels[level],
        "triggers": sorted(set(triggers)),
        "badge": f"ASCVD substrate: {substrate_status(p)} | Lifetime risk: {lifetime_signal(level)} | Near-term risk: {near_term_signal(p)}",
        "overlays": overlays,
        "accelerated_trajectory": accelerated,
        "intermediate_zone": {"flag": intermediate, "reasons": inter_reasons},
        "recommended_next_steps": next_steps,
        "acc_lines": acc_lines(p, level),
        "esc_line": esc_line(p, level),
    }

# ----------------------------
# Note renderer
# ----------------------------

def render_note(p: Patient, r: Dict[str, Any], mode="balanced") -> str:
    out=[]
    out.append("LEVELS™ v1.1 — Atherosclerotic Risk Band")
    out.append(r["badge"])
    out.append("")
    out.append(r["label"])
    out.append("")

    det=[]
    if p.has("ldl"): det.append(f"LDL-C: {p.get('ldl')}")
    if p.has("apob"): det.append(f"ApoB: {p.get('apob')}")
    if p.has("lpa"):
        u=p.get("lpa_unit","")
        det.append(f"Lp(a): {p.get('lpa')} {u}".strip())
    if p.get("fhx") is True: det.append("Premature FHx: Yes")
    if p.has("hscrp"): det.append(f"hsCRP: {p.get('hscrp')}")
    if p.has("cac"): det.append(f"CAC: {p.get('cac')}")
    if det:
        out.append("Key determinants:")
        for d in det: out.append("• " + d)
        out.append("")

    out.append("Guideline positioning (qualitative):")
    for line in r["acc_lines"]:
        out.append("• " + line if not line.startswith("  -") else line)
    out.append("• " + r["esc_line"])
    out.append("")

    if r["overlays"]:
        out.append("Overlays:")
        if r["overlays"].get("inflammatory_overlay"):
            out.append("• Inflammatory overlay: " + ", ".join(r["overlays"]["inflammatory_overlay"]))
        if r.get("accelerated_trajectory"):
            out.append("• Trajectory: Accelerated (inflammation may increase progression risk)")
        if r["overlays"].get("genetic_overlay"):
            out.append("• Genetic overlay: " + r["overlays"]["genetic_overlay"])
        out.append("")

    iz=r.get("intermediate_zone",{})
    if iz.get("flag"):
        out.append("Intermediate zone:")
        for rr in iz.get("reasons",[]): out.append("• " + rr)
        out.append("")
        if r.get("recommended_next_steps"):
            out.append("Recommended next steps:")
            for s in r["recommended_next_steps"]: out.append("• " + s)
            out.append("")

    out.append("Triggers:")
    out.append(", ".join(r["triggers"]))
    return "\n".join(out)
