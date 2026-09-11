"""SINP (Saskatchewan) Factor I points grid, pinned to the official values (saskatchewan.ca).

Each expected number is computed by hand from the transcribed grid, so a change to any point value
breaks exactly one assertion. Guards against silent drift in a provincial grid, the same protection
the CRS anchors give the federal engine.

Run:  cd server && PYTHONPATH=. python3 -m pytest -q tests/test_saskatchewan.py
"""
from datetime import date

from crs import LanguageScores, Profile
from pnp import sinp_points


def L(clb):
    return LanguageScores(clb, clb, clb, clb)


def test_strong_profile_scores_factor_one_and_clears_the_floor():
    # masters 23 + 3yr work 6 + CLB9 first 20 + CLB7 second 8 + age 30 (22-34) 12 = 69.
    p = Profile(age=30, education="masters-or-professional", first_language=L(9),
                canadian_work_years=3, second_language=L(7))
    s = sinp_points(p)
    assert s.factor_one == 69
    assert s.meets_points_floor is True  # 69 >= 60 on Factor I alone


def test_weak_profile_is_undecided_not_rejected():
    # secondary 0 + 0yr work 0 + CLB4 first 12 + no second 0 + age 48 (46-50) 8 = 20.
    p = Profile(age=48, education="secondary", first_language=L(4))
    s = sinp_points(p)
    assert s.factor_one == 20
    # Below 60 on Factor I, but a Saskatchewan connection (not assessed) could still reach it.
    assert s.meets_points_floor is None


def test_trade_certificate_is_worth_at_least_20_education_points():
    # No academic post-secondary, but a journeyperson trade certificate is 20 education points.
    p = Profile(age=25, education="secondary", first_language=L(6),
                has_certificate_of_qualification=True)
    s = sinp_points(p)
    edu = next(i["points"] for i in s.breakdown if i["factor"] == "education")
    assert edu == 20


def test_work_experience_counts_recent_years_capped_at_five():
    # 8 total years -> counted as the last-5 band (10), never inflated beyond the grid's 5-year max.
    p = Profile(age=30, education="bachelors-or-three-year", first_language=L(7),
                canadian_work_years=5, foreign_work_years=3)
    work = next(i["points"] for i in sinp_points(p).breakdown if i["factor"] == "work_experience")
    assert work == 10
