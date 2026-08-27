"""Tests for the time machine: deadlines() and trajectory()."""
from datetime import date

import pytest

from crs import LanguageScores, Profile, crs, deadlines, trajectory


def L(clb):
    return LanguageScores(clb, clb, clb, clb)


def _p(**kw):
    base = dict(
        education="bachelors-or-three-year",
        first_language=L(9),
        date_of_birth=date(1994, 11, 3),
        canadian_work_years=1,
    )
    base.update(kw)
    return Profile(**base)


def test_age_cliff_detected_with_delta():
    d = deadlines(_p(), as_of=date(2024, 1, 1))
    first = d.age_cliffs[0]
    assert first.date == date(2024, 11, 3)   # turns 30
    assert first.kind == "age"
    assert first.delta == -5                  # 110 -> 105


def test_age_cliffs_span_until_45_and_all_nonzero():
    d = deadlines(_p(), as_of=date(2024, 1, 1))
    assert all(c.delta != 0 for c in d.age_cliffs)
    assert d.age_cliffs[-1].date.year - 1994 == 45  # last cliff is turning 45


def test_test_expiry_cliff_zeros_language():
    p = _p(first_language_test_date=date(2024, 3, 1))
    d = deadlines(p, as_of=date(2024, 1, 1))
    assert d.test_expiry == date(2026, 3, 1)
    # dropping first-language points (incl. their skill-transfer) is a large negative
    assert d.test_expiry_cliff.delta < 0
    assert d.test_expiry_cliff.kind == "test_expiry"


def test_trajectory_points_and_cliffs():
    p = _p(first_language_test_date=date(2024, 3, 1))
    t = trajectory(p, date(2024, 1, 1), date(2026, 12, 31))
    # endpoints present, monotonic dates
    dates = [pt.date for pt in t.points]
    assert dates[0] == date(2024, 1, 1) and dates[-1] == date(2026, 12, 31)
    assert dates == sorted(dates)
    # cliffs include the two birthdays (2024, 2025, 2026-11-03) and the 2026-03-01 expiry
    kinds = [c.kind for c in t.cliffs]
    assert "age" in kinds and "test_expiry" in kinds
    # trajectory total at a date matches a direct crs() call before expiry
    assert t.points[0].total == crs(p, date(2024, 1, 1)).total


def test_timeline_requires_dob():
    with pytest.raises(ValueError):
        deadlines(Profile(age=30, education="secondary", first_language=L(7)))
