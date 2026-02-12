from __future__ import annotations

import random
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from levels_engine import Patient, evaluate


def _rand_patient(rng: random.Random) -> dict:
    """Generate clinically bounded synthetic profiles (not edge-sentinel fuzz)."""

    def maybe(value, p: float = 0.7):
        return value if rng.random() < p else None

    return {
        "age": rng.randint(40, 79),
        "sex": rng.choice(["M", "F"]),
        "race": rng.choice(["other", "african_american"]),
        "ascvd": rng.random() < 0.10,
        "sbp": rng.randint(100, 185),
        "bp_treated": rng.random() < 0.50,
        "smoking": rng.random() < 0.25,
        "diabetes": rng.random() < 0.22,
        "tc": rng.randint(130, 310),
        "hdl": rng.randint(25, 90),
        "ldl": rng.randint(50, 220),
        "egfr": rng.randint(25, 115),
        "lipid_lowering": rng.random() < 0.45,
        "apob": maybe(rng.randint(40, 180), 0.70),
        "lpa": maybe(rng.randint(10, 300), 0.70),
        "lpa_unit": rng.choice(["nmol/L", "mg/dL"]),
        "a1c": maybe(round(rng.uniform(4.8, 8.8), 1), 0.70),
        "cac": maybe(rng.choice([0, rng.randint(1, 600)]), 0.50),
        "fhx": rng.random() < 0.20,
    }


def test_adversarial_200_profiles_no_contradictions_or_big_instability():
    """
    Adversarial generation pass:
    - 200 bounded random profiles
    - flag/report contradictions
    - flag/report instability for tiny perturbations

    Invariant checks:
    1) No dominant-action language at low posture when plaque is explicitly reassuring (CAC=0).
    2) Tiny perturbations (+1 SBP, +1 LDL, +1 ApoB, +0.1 A1c) should not cause >=2 level jumps.
    """
    rng = random.Random(20260212)

    contradictions: list[tuple] = []
    unstable: list[tuple] = []

    for idx in range(200):
        prof = _rand_patient(rng)
        out = evaluate(Patient(prof))

        lvl = out.get("levels") or {}
        level = int(lvl.get("managementLevel") or 0)
        dominant = bool(lvl.get("dominantAction") is True)

        ev = (lvl.get("evidence") or {}) if isinstance(lvl.get("evidence"), dict) else {}
        cac_status = str(ev.get("cac_status") or "").lower()
        cac_value = ev.get("cac_value")

        if dominant and level <= 2 and ("cac = 0" in cac_status or cac_value == 0):
            contradictions.append((idx, level, cac_status, cac_value))

        for field, delta in (("sbp", 1), ("ldl", 1), ("apob", 1), ("a1c", 0.1)):
            if prof.get(field) is None:
                continue
            perturbed = deepcopy(prof)
            if field == "a1c":
                perturbed[field] = round(float(perturbed[field]) + float(delta), 1)
            else:
                perturbed[field] = int(perturbed[field]) + int(delta)

            out2 = evaluate(Patient(perturbed))
            level2 = int(((out2.get("levels") or {}).get("managementLevel") or 0))

            if abs(level2 - level) >= 2:
                unstable.append((idx, field, level, level2, prof.get(field), perturbed[field]))

    assert not contradictions, f"Contradictions found: {contradictions[:10]}"
    assert not unstable, f"Large-instability cases found: {unstable[:10]}"
