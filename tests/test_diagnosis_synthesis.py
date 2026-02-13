from levels_output_adapter import build_diagnosis_synthesis, generateRiskContinuumCvOutput


def test_build_diagnosis_synthesis_suspected_diabetes_no_exported_icd():
    payload = {"a1c": 6.7}
    out = build_diagnosis_synthesis(payload, {})

    suspected = [d for d in out["diagnoses"] if d["id"] == "dx_dm_suspected"]
    assert suspected, "expected suspected diabetes diagnosis"
    assert suspected[0]["status"] == "suspected"
    assert suspected[0]["icd10"] == []
    assert suspected[0]["icd10_candidates"]


def test_build_diagnosis_synthesis_composite_suppression_for_htn_ckd():
    payload = {"hypertension": True, "ckd": True, "egfr": 38}
    out = build_diagnosis_synthesis(payload, {})
    ids = {d["id"] for d in out["diagnoses"]}

    assert "dx_htn_ckd" in ids
    assert "dx_htn" not in ids


def test_generate_output_includes_diagnosis_synthesis():
    input_data = {
        "ldl": 165,
        "triglycerides": 210,
        "a1c": 5.9,
        "bmi": 31,
    }
    engine_out = {
        "system": "Risk Continuum",
        "levels": {
            "managementLevel": 2,
            "label": "Level 2 — Emerging risk signals",
            "recommendationStrength": "Routine",
            "evidence": {},
        },
        "riskSignal": {"score": 41, "band": "moderate"},
        "pooledCohortEquations10yAscvdRisk": {"risk_pct": 5.0, "category": "borderline"},
        "targets": {},
        "prevent10": {},
    }

    out = generateRiskContinuumCvOutput(input_data, engine_out)
    assert "diagnosisSynthesis" in out
    assert isinstance(out["diagnosisSynthesis"].get("diagnoses"), list)


def test_build_diagnosis_synthesis_lpa_unit_threshold_respects_nmol():
    payload = {"lpa": 80, "lpa_unit": "nmol/L"}
    out = build_diagnosis_synthesis(payload, {})
    ids = {d["id"] for d in out["diagnoses"]}

    assert "dx_lpa_elevated" not in ids


def test_build_diagnosis_synthesis_lpa_unit_threshold_respects_mgdl():
    payload = {"lpa": 80, "lpa_unit": "mg/dL"}
    out = build_diagnosis_synthesis(payload, {})
    ids = {d["id"] for d in out["diagnoses"]}

    assert "dx_lpa_elevated" in ids
