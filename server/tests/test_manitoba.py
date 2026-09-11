"""MPNP (Manitoba) self-assessment grid, pinned to the official worksheet values.

Manitoba requires a mandatory Manitoba connection (Factor 5) we do not collect, so MPNP eligibility
is never asserted. We compute Factors 1-4 (language, age, work, education, max 75) exactly from the
official grid. Source: immigratemanitoba.com self-assessment worksheet.

Run:  cd server && PYTHONPATH=. python3 -m pytest -q tests/test_manitoba.py
"""
from crs import LanguageScores, Profile
from paths import eligible_pathways
from pnp import mpnp_points


def L(clb):
    return LanguageScores(clb, clb, clb, clb)


def test_factors_1_to_4_scored_from_the_official_grid():
    # language 20+5 + age(30) 10 + work(3yr) 12 + education(masters) 25 = 72 of 75.
    p = Profile(age=30, education="masters-or-professional", first_language=L(9),
                canadian_work_years=3, second_language=L(7))
    s = mpnp_points(p)
    assert s.factors_1_4 == 72
    assert s.clears_floor_before_connection is True


def test_weak_profile_subtotal():
    # language(CLB4) 12 + age(48) 4 + work(0) 0 + education(secondary) 0 = 16.
    p = Profile(age=48, education="secondary", first_language=L(4))
    s = mpnp_points(p)
    assert s.factors_1_4 == 16
    assert s.clears_floor_before_connection is False


def test_manitoba_eligibility_is_never_asserted_without_the_connection():
    p = Profile(age=30, education="masters-or-professional", first_language=L(9))
    mb = next(x for x in eligible_pathways(p).pathways if x.slug == "pnp-manitoba")
    assert mb.eligible is None       # a Manitoba connection is mandatory and not collected
    assert mb.score_kind == "MPNP points"
    assert "connection" in mb.additional_requirements.lower()
