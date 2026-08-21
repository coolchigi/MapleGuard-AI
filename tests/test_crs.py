"""Validation suite for the CRS engine.

Run:  cd agents-for-humans/mapleguard && python -m pytest -q
The engine has no third-party dependencies; only the tests require pytest.

Layers:
  - invariant tests: bounds and caps that must always hold
  - regression tests: rules that must not silently change (e.g. removed job-offer points)
  - provenance test: every point table must be marked verified against the source
  - arithmetic anchors: fixed profiles with values computed by hand from the grid
  - oracle cases: profiles checked against the official IRCC calculator (data-driven)
"""
import json
import pathlib

import pytest

from crs import crs, Profile, LanguageScores
from crs import tables as T

CASES = pathlib.Path(__file__).parent.parent / "crs" / "cases" / "golden.json"


def L(clb):  # helper: uniform CLB across all four abilities
    return LanguageScores(clb, clb, clb, clb)


# --- Tier 5: property / invariant tests (catch whole bug classes) --------------------
SAMPLE = Profile(age=29, education="masters-or-professional", first_language=L(9),
                 canadian_work_years=3, foreign_work_years=3)


def test_score_in_range():
    assert 0 <= crs(SAMPLE).total <= 1200


def test_component_caps():
    s = crs(SAMPLE)
    assert s.core <= 500
    assert s.spouse <= 40
    assert s.skill_transfer <= 100
    assert s.additional <= 600


def test_monotonicity_pnp_never_hurts():
    base = crs(SAMPLE).total
    with_pnp = crs(Profile(**{**SAMPLE.__dict__, "has_provincial_nomination": True})).total
    assert with_pnp >= base
    assert with_pnp - base == 600  # PNP is exactly +600


def test_monotonicity_more_language_never_hurts():
    lo = crs(Profile(age=29, education="bachelors-or-three-year", first_language=L(7))).total
    hi = crs(Profile(age=29, education="bachelors-or-three-year", first_language=L(9))).total
    assert hi >= lo


def test_spouse_shifts_core_ceiling():
    # With a scored spouse, core ceiling is 460, not 500.
    p = Profile(age=25, education="doctoral", first_language=L(10), canadian_work_years=5,
                marital_status="married", spouse_accompanying=True)
    assert crs(p).core <= 460


# --- Tier 4: temporal / regression guard (the stale-value killer) --------------------
def test_arranged_employment_is_zero():
    """Job-offer points were removed 2025-03-25. This must never silently come back."""
    assert T.MAX_ADDITIONAL.values["arranged_employment"] == 0
    p = Profile(age=29, education="masters-or-professional", first_language=L(9))
    # There is no field to grant arranged-employment points; additional stays bounded.
    assert crs(p).additional <= 600


def test_table_provenance():
    """Every point table must be marked verified against the official source."""
    unverified = [t.name for t in T.ALL_TABLES if not t.verified]
    assert not unverified, f"Tables not yet verified against the source: {unverified}"


# Fixed profiles with point totals computed by hand from the published grid. These
# exercise the full pipeline, including the graduated skill-transferability rules.
def test_anchor_minimal():
    # age 20 (110), less than secondary (0), no language, no work.
    assert crs(Profile(age=20, education="none-or-less-than-secondary", first_language=L(0))).total == 110


def test_anchor_secondary_maxed_language_no_transfer():
    # age 20 (110) + secondary (30) + CLB 10 all abilities (136) + 5 years Canadian work (80).
    # Secondary education is below the skill-transfer education tier, so that group is 0
    # even at CLB 10: language alone does not unlock education skill-transfer points.
    p = Profile(age=20, education="secondary", first_language=L(10), canadian_work_years=5)
    s = crs(p)
    assert s.core == 356 and s.skill_transfer == 0 and s.total == 356


def test_anchor_lone_bachelor_clb9_transfer_is_25():
    # A single bachelor's degree is one credential, so it sits in the 13/25 skill-transfer
    # tier rather than the 25/50 tier used for two-or-more credentials.
    # age 20 (110) + bachelor (120) + CLB 9 all abilities (124) = 354 core; education
    # skill-transfer 25 (CLB 9, no Canadian work).
    p = Profile(age=20, education="bachelors-or-three-year", first_language=L(9))
    s = crs(p)
    assert s.core == 354
    assert s.skill_transfer == 25
    assert s.total == 379


# --- Tier 3: oracle / end-to-end golden cases (your 474, the ImmiPilot 444) ----------
def _load_cases():
    if not CASES.exists():
        return []
    return json.loads(CASES.read_text()).get("cases", [])


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c.get("name", "case"))
def test_golden_oracle(case):
    """Each case: a profile + the number IRCC's official tool gives. Engine must match."""
    if case.get("expected_total") is None:
        pytest.skip(f"{case['name']}: fill expected_total from the official IRCC tool")
    p = _profile_from_case(case["profile"])
    assert crs(p).total == case["expected_total"], case.get("note", "")


def _profile_from_case(d: dict) -> Profile:
    for lang_key in ("first_language", "second_language", "spouse_first_language"):
        if isinstance(d.get(lang_key), list):
            d[lang_key] = LanguageScores(*d[lang_key])
    return Profile(**d)
