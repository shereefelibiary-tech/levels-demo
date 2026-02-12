import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from levels_engine import Patient, evaluate
from levels_output_adapter import evaluate_unified


BASE = {
    "age": 60,
    "sex": "M",
    "race": "other",
    "ascvd": False,
    "sbp": 130,
    "bp_treated": False,
    "smoking": False,
    "diabetes": False,
    "tc": 180,
    "hdl": 50,
    "ldl": 100,
    "egfr": 80,
    "lipid_lowering": False,
}


def _required_schema_assertions(out: dict) -> None:
    top_keys = {
        "levels",
        "riskSignal",
        "pooledCohortEquations10yAscvdRisk",
        "prevent10",
        "targets",
        "aspirin",
        "insights",
        "nextActions",
        "drivers",
    }
    assert top_keys.issubset(set(out.keys()))

    levels = out["levels"]
    assert 1 <= int(levels["managementLevel"]) <= 5
    assert levels["managementLevel"] == levels["postureLevel"]
    assert isinstance(levels["evidence"], dict)

    evidence = levels["evidence"]
    for k in ("clinical_ascvd", "on_lipid_therapy", "cac_status", "burden_band"):
        assert k in evidence

    assert isinstance(out["nextActions"], list)
    assert isinstance(out["drivers"], list)


def test_schema_no_drift_property_style_randomized_legacy_and_v4():
    rng = random.Random(7)
    for _ in range(60):
        d = dict(BASE)
        d.update(
            {
                "age": rng.randint(35, 79),
                "sbp": rng.randint(100, 180),
                "bp_treated": rng.choice([True, False]),
                "smoking": rng.choice([True, False]),
                "diabetes": rng.choice([True, False]),
                "tc": rng.randint(120, 300),
                "hdl": rng.randint(25, 90),
                "ldl": rng.randint(50, 220),
                "egfr": rng.randint(25, 110),
                "ascvd": rng.choice([True, False]),
                "lipid_lowering": rng.choice([True, False]),
            }
        )
        if rng.random() < 0.7:
            d["apob"] = rng.choice([0, rng.randint(40, 180)])
        if rng.random() < 0.7:
            d["lpa"] = rng.choice([0, rng.randint(5, 300)])
            d["lpa_unit"] = rng.choice(["nmol/L", "mg/dL"])
        if rng.random() < 0.5:
            d["cac"] = rng.choice([0, rng.randint(1, 400)])

        p = Patient(d)
        _required_schema_assertions(evaluate(p))
        _required_schema_assertions(evaluate_unified(p, engine_version="v4"))


def test_stable_level_sublevel_canonical_cases():
    cases = [
        ({**BASE, "cac": 50}, (4, None)),
        ({**BASE, "ascvd": True}, (5, None)),
        ({**BASE, "a1c": 6.0}, (2, "2B")),
        ({**BASE, "apob": 120}, (3, "3A")),
        ({**BASE, "apob": 120, "lpa": 150, "lpa_unit": "nmol/L"}, (3, "3B")),
    ]

    for data, expected in cases:
        out = evaluate(Patient(data))
        got = (out["levels"]["managementLevel"], out["levels"].get("sublevel"))
        assert got == expected


def test_cac_gating_rules():
    unknown = evaluate(Patient(dict(BASE)))
    known_zero = evaluate(Patient({**BASE, "cac": 0}))
    known_positive = evaluate(Patient({**BASE, "cac": 20}))
    high_risk = evaluate(
        Patient({**BASE, "sbp": 170, "tc": 260, "hdl": 30, "smoking": True})
    )

    u = (unknown.get("insights") or {}).get("cac_decision_support") or {}
    z = (known_zero.get("insights") or {}).get("cac_decision_support") or {}
    p = (known_positive.get("insights") or {}).get("cac_decision_support") or {}
    h = (high_risk.get("insights") or {}).get("cac_decision_support") or {}

    assert u.get("status") == "optional"
    assert z.get("status") == "suppressed" and z.get("tag") == "CAC_SUPPRESSED_PLAQUE_KNOWN"
    assert p.get("status") == "suppressed" and p.get("tag") == "CAC_SUPPRESSED_PLAQUE_KNOWN"
    assert h.get("status") == "suppressed" and h.get("tag") == "CAC_SUPPRESSED_HIGH_RISK"


def test_apob_lpa_missing_vs_zero_rules():
    # ApoB: 0 should behave like missing (same management level/sublevel)
    apob_missing = evaluate(Patient(dict(BASE)))
    apob_zero = evaluate(Patient({**BASE, "apob": 0}))
    assert apob_missing["levels"]["managementLevel"] == apob_zero["levels"]["managementLevel"]
    assert apob_missing["levels"].get("sublevel") == apob_zero["levels"].get("sublevel")

    # Lp(a): 0 should be treated as unmeasured in where-patient-falls HTML and show missing effect.
    lpa_zero = evaluate(Patient({**BASE, "lpa": 0, "lpa_unit": "nmol/L"}))
    html = ((lpa_zero.get("insights") or {}).get("where_patient_falls_html") or "")
    assert "Lp(a)" in html
    assert "Unmeasured" in html
    assert "Missing (obtain Lp(a))" in html


def test_aspirin_text_rules():
    ascvd = evaluate(Patient({**BASE, "ascvd": True}))
    old_age = evaluate(Patient({**BASE, "age": 75}))
    consider = evaluate(Patient({**BASE, "cac": 150}))

    a1 = ((ascvd.get("insights") or {}).get("aspirin_copy") or {}).get("headline", "")
    a2 = ((old_age.get("insights") or {}).get("aspirin_copy") or {}).get("headline", "")
    a3 = ((consider.get("insights") or {}).get("aspirin_copy") or {}).get("headline", "")

    assert a1 == "Aspirin: Indicated (secondary prevention)."
    assert a2 == "Aspirin: Avoid."
    assert a3 == "Aspirin: Reasonable (shared decision)."
