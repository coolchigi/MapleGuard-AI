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


# --- Factor coverage: one anchor per factor an immigrant actually asks about ----------
# Each number below is computed by hand from the published grid in crs/tables.py and then
# confirmed against the engine, so a change to any single table breaks exactly one test and
# names the factor. These are the factors the official IRCC tool exposes but that the earlier
# suite did not exercise: French, spouse, the skill-transfer foreign-work and certificate
# groups, the additional-points sources and their 600 cap, and the age/CLB boundaries.

def test_french_bonus_nclc7_with_english_clb9_adds_50():
    # The "I didn't know French was an option" case. English first language CLB 9, French second
    # language NCLC 7. French NCLC 7 + English CLB 5+ is the top additional bonus: +50.
    # core 310 = age29 110 + bachelor 120 + Eng CLB9 (31x4=124)... wait English is CLB7 here:
    # first_language CLB7 (17x4=68) + French second (3x4=12, under the 24 cap) = 110+120+68+12.
    p = Profile(age=29, education="bachelors-or-three-year", first_language=L(7),
                second_language=L(7), second_language_is_french=True)
    s = crs(p)
    assert s.additional == 50
    assert any(i.factor == "french_bonus" and i.points == 50 for i in s.breakdown)
    assert s.total == 373


def test_french_bonus_nclc7_with_english_clb4_adds_only_25():
    # Same French NCLC 7, but weak English (CLB 4 < 5) drops the bonus to the lower tier: +25.
    p = Profile(age=29, education="bachelors-or-three-year", first_language=L(4),
                second_language=L(7), second_language_is_french=True)
    s = crs(p)
    assert s.additional == 25
    assert s.total == 291


def test_french_bonus_needs_nclc7_across_all_abilities():
    # NCLC 6 in even one ability fails the NCLC 7 gate, so no French bonus at all.
    weak_french = LanguageScores(speaking=7, listening=7, reading=6, writing=7)
    p = Profile(age=29, education="bachelors-or-three-year", first_language=L(9),
                second_language=weak_french, second_language_is_french=True)
    assert all(i.factor != "french_bonus" for i in crs(p).breakdown)


def test_scored_spouse_uses_spouse_tables_and_spouse_block():
    # Married, spouse accompanying and not a PR, so the spouse is scored: the core switches to the
    # spouse tables (lower age/education/language values, ceiling 460) and the spouse block adds
    # spouse education 8 + spouse language (3x4=12) + spouse Canadian work 5 = 25.
    p = Profile(age=29, education="bachelors-or-three-year", first_language=L(9),
                marital_status="married", spouse_accompanying=True,
                spouse_education="bachelors-or-three-year", spouse_first_language=L(7),
                spouse_canadian_work_years=1)
    s = crs(p)
    assert s.core == 328          # 100 age + 112 edu + 116 lang (spouse tables)
    assert s.spouse == 25
    assert s.total == 378


def test_spouse_not_scored_when_a_pr_or_citizen():
    # A spouse who is already a PR/citizen is not scored: single tables, no spouse block.
    single = crs(Profile(age=29, education="bachelors-or-three-year", first_language=L(9)))
    with_pr_spouse = crs(Profile(age=29, education="bachelors-or-three-year", first_language=L(9),
                                 marital_status="married", spouse_accompanying=True,
                                 spouse_is_pr_or_citizen=True, spouse_first_language=L(9)))
    assert with_pr_spouse.total == single.total
    assert with_pr_spouse.spouse == 0


def test_skill_transfer_all_three_groups_cap_at_100():
    # Masters + CLB 9 + 2 Canadian years + 3 foreign years + trade certificate maxes every
    # skill-transfer group (education 50, foreign work 50, certificate 50 = 150) but the block
    # is capped at 100.
    p = Profile(age=29, education="masters-or-professional", first_language=L(9),
                canadian_work_years=2, foreign_work_years=3, has_certificate_of_qualification=True)
    assert crs(p).skill_transfer == 100


def test_sibling_in_canada_adds_15():
    p = Profile(age=29, education="bachelors-or-three-year", first_language=L(9),
                has_sibling_in_canada=True)
    s = crs(p)
    assert s.additional == 15
    assert any(i.factor == "sibling_in_canada" and i.points == 15 for i in s.breakdown)


def test_canadian_study_1_2_years_is_15_and_3_plus_is_30():
    short = crs(Profile(age=29, education="bachelors-or-three-year", first_language=L(9),
                        canadian_post_secondary_years=2))
    long = crs(Profile(age=29, education="bachelors-or-three-year", first_language=L(9),
                       canadian_post_secondary_years=3))
    assert short.additional == 15
    assert long.additional == 30


def test_additional_points_cap_at_600():
    # PNP 600 + sibling 15 + Canadian study 30 + French 50 = 695, capped at 600.
    p = Profile(age=29, education="bachelors-or-three-year", first_language=L(9),
                has_provincial_nomination=True, has_sibling_in_canada=True,
                canadian_post_secondary_years=4, second_language=L(7),
                second_language_is_french=True)
    assert crs(p).additional == 600


def test_age_outside_the_table_scores_zero():
    # The age grid runs 18 to 44. Age 45+ and 17- score 0 age points (not an error).
    at_45 = crs(Profile(age=45, education="bachelors-or-three-year", first_language=L(9)))
    assert at_45.breakdown[0].factor == "age" and at_45.breakdown[0].points == 0
    at_18 = crs(Profile(age=18, education="bachelors-or-three-year", first_language=L(9)))
    assert at_18.breakdown[0].points == 99


def test_language_below_clb4_scores_zero():
    # CLB below 4 earns no first-language points; CLB 4 is the first scoring band (6 x 4 = 24).
    below = crs(Profile(age=29, education="bachelors-or-three-year", first_language=L(3)))
    at_4 = crs(Profile(age=29, education="bachelors-or-three-year", first_language=L(4)))
    lang_pts = lambda s: next(i.points for i in s.breakdown if i.factor == "first_language")
    assert lang_pts(below) == 0
    assert lang_pts(at_4) == 24


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


# --- Date-parameterization (time-machine foundation) ---------------------------
from datetime import date as _date


def test_dob_derives_age_and_age_cliff():
    p = Profile(education="bachelors-or-three-year", first_language=L(9),
                date_of_birth=_date(1994, 11, 3))
    assert crs(p, _date(2024, 11, 2)).breakdown[0].points == 110  # age 29
    assert crs(p, _date(2024, 11, 3)).breakdown[0].points == 105  # turns 30


def test_static_age_still_works():
    assert crs(Profile(age=29, education="bachelors-or-three-year",
                       first_language=L(9))).breakdown[0].points == 110


def test_requires_age_or_dob():
    import pytest as _pt
    with _pt.raises(ValueError):
        Profile(education="secondary", first_language=L(0))
