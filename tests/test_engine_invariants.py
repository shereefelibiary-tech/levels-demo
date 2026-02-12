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


def test_aspirin_primary_prevention_guardrails_and_rationale():
    # A) Primary prevention, age 60, CAC 222, no bleeding risks
    primary_consider = evaluate(Patient({**BASE, "age": 60, "cac": 222, "ascvd": False}))
    a_line = ((primary_consider.get("insights") or {}).get("aspirin_copy") or {}).get("headline", "")
    a_data = primary_consider.get("aspirin") or {}

    assert a_line == "Aspirin: Consider low-dose aspirin (shared decision-making; bleeding risk must be low)."
    assert "FOR:" in " ".join(a_data.get("rationale") or [])
    assert "AGAINST:" in " ".join(a_data.get("rationale") or [])

    # B) Primary prevention, age 60, CAC 0, no bleeding risks
    primary_cac0 = evaluate(Patient({**BASE, "age": 60, "cac": 0, "ascvd": False}))
    b_line = ((primary_cac0.get("insights") or {}).get("aspirin_copy") or {}).get("headline", "")
    assert b_line == "Aspirin: Not indicated."

    # C) Primary prevention, age 72, CAC 300, no bleeding risks
    primary_old = evaluate(Patient({**BASE, "age": 72, "cac": 300, "ascvd": False}))
    c_line = ((primary_old.get("insights") or {}).get("aspirin_copy") or {}).get("headline", "")
    assert c_line == "Aspirin: Not indicated."

    # D) Primary prevention, age 55, CAC 150, anticoagulant
    primary_anticoag = evaluate(Patient({**BASE, "age": 55, "cac": 150, "ascvd": False, "bleed_anticoag": True}))
    d_line = ((primary_anticoag.get("insights") or {}).get("aspirin_copy") or {}).get("headline", "")
    assert d_line == "Aspirin: Not indicated."


def test_aspirin_secondary_prevention_behavior_unchanged():
    # E) Secondary prevention pathway remains indicated wording
    ascvd = evaluate(Patient({**BASE, "ascvd": True, "age": 60}))
    a1 = ((ascvd.get("insights") or {}).get("aspirin_copy") or {}).get("headline", "")
    assert a1 == "Aspirin: Indicated (secondary prevention)."
