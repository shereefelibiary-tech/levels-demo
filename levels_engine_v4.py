# levels_engine_v4.py
from typing import Any, Dict

def evaluate_v4(patient) -> Dict[str, Any]:
    # Minimal stub: returns just enough for app.py + adapter to render.
    # Replace these constants with real derivations incrementally.
    return {
        "level_num": 3,
        "sublevel": "3B",
        "plaque_status": "Unknown — no structural imaging",
        "plaque_burden": "Not quantified",

        "riskSignal": {"score": 7, "band": "Low"},
        "pooledCohortEquations10yAscvdRisk": {"risk_pct": 42.9, "category": "High (≥20%)"},
        "prevent10": {"total_cvd_10y_pct": 16.83, "ascvd_10y_pct": 8.44, "notes": ""},

        "targets": {"ldl": 100, "apob": 80},

        "aspirin_status": "Not indicated",
        "aspirin_copy": {"headline": "Aspirin: Not indicated"},
        "cac_copy": {"headline": "Coronary calcium: Reasonable", "detail": "", "referral": ""},

        "ckm_text": "CKM: Stage 2 (diabetes, obesity, dyslipidemia)",
        "ckd_text": "CKD3a (eGFR 52, UACR 68)",

        # Optional
        "drivers": ["Diabetes"],
        "nextActions": [],
        "anchors": {"nearTerm": {"summary": "—"}, "lifetime": {"summary": "—"}},
        "trace": [],
    }

