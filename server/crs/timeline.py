"""The time machine: your CRS over time, and the dated cliffs and windows.

CRS is a deterministic function of dates. `deadlines()` returns the events that
move your score (age-bracket drops, language-test expiry). `trajectory()` plots
the score across a date range with those cliffs labelled. Both require a
`date_of_birth` (a timeline needs a birthdate). Pure functions, no I/O.

Not yet modelled (needs a work-start date, see TODO): the upward cliffs where
Canadian-work anniversaries add points.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from .engine import crs
from .models import LanguageScores, Profile

LANGUAGE_TEST_VALIDITY_YEARS = 2
AGE_FLOOR = 45  # age at which age points reach 0


@dataclass(frozen=True)
class Cliff:
    date: date
    kind: str      # "age" | "test_expiry"
    label: str
    delta: int     # change in total CRS at this event (negative = a drop)


@dataclass(frozen=True)
class Deadlines:
    age_cliffs: list[Cliff]
    test_expiry: date | None
    test_expiry_cliff: Cliff | None


@dataclass(frozen=True)
class TrajectoryPoint:
    date: date
    total: int


@dataclass(frozen=True)
class Trajectory:
    points: list[TrajectoryPoint]
    cliffs: list[Cliff]


# ------------------------------------------------------------------- internals
def _require_dob(profile: Profile) -> date:
    if profile.date_of_birth is None:
        raise ValueError("timeline needs a date_of_birth")
    return profile.date_of_birth


def _expiry(profile: Profile) -> date | None:
    d = profile.first_language_test_date
    return d.replace(year=d.year + LANGUAGE_TEST_VALIDITY_YEARS) if d else None


def _expired(profile: Profile) -> Profile:
    """Profile with first-language results lapsed (points, incl. transfer, drop to 0)."""
    return replace(profile, first_language=LanguageScores(0, 0, 0, 0))


def _total_on(profile: Profile, d: date, expiry: date | None) -> int:
    p = _expired(profile) if (expiry and d >= expiry) else profile
    return crs(p, d).total


def _birthday(dob: date, year: int) -> date:
    try:
        return dob.replace(year=year)
    except ValueError:  # Feb 29 in a non-leap year
        return date(year, 3, 1)


def _birthdays_in(dob: date, start: date, end: date):
    for year in range(start.year, end.year + 1):
        b = _birthday(dob, year)
        if start < b <= end:
            yield b


def _cliff_at(profile: Profile, d: date, kind: str, label: str, expiry: date | None) -> Cliff:
    delta = _total_on(profile, d, expiry) - _total_on(profile, d - timedelta(days=1), expiry)
    return Cliff(date=d, kind=kind, label=label, delta=delta)


# ---------------------------------------------------------------------- public
def deadlines(profile: Profile, as_of: date | None = None) -> Deadlines:
    dob = _require_dob(profile)
    today = as_of or date.today()
    expiry = _expiry(profile)

    age_cliffs: list[Cliff] = []
    horizon = _birthday(dob, dob.year + AGE_FLOOR)  # birthday when age hits the floor
    for b in _birthdays_in(dob, today, horizon):
        c = _cliff_at(profile, b, "age", f"age {b.year - dob.year}", expiry)
        if c.delta != 0:
            age_cliffs.append(c)

    expiry_cliff = None
    if expiry and expiry >= today:
        expiry_cliff = _cliff_at(
            profile, expiry, "test_expiry",
            "language test expires (profile rejected in-pool)", expiry,
        )
    return Deadlines(age_cliffs=age_cliffs, test_expiry=expiry, test_expiry_cliff=expiry_cliff)


def trajectory(profile: Profile, start: date, end: date) -> Trajectory:
    _require_dob(profile)
    if end < start:
        raise ValueError("end before start")
    expiry = _expiry(profile)

    events: list[tuple[date, str, str]] = [
        (b, "age", f"age {b.year - profile.date_of_birth.year}")
        for b in _birthdays_in(profile.date_of_birth, start, end)
    ]
    if expiry and start < expiry <= end:
        events.append((expiry, "test_expiry", "language test expires (profile rejected in-pool)"))
    events.sort(key=lambda e: e[0])

    points = [TrajectoryPoint(start, _total_on(profile, start, expiry))]
    cliffs: list[Cliff] = []
    for d, kind, label in events:
        points.append(TrajectoryPoint(d, _total_on(profile, d, expiry)))
        cliffs.append(_cliff_at(profile, d, kind, label, expiry))
    if not events or events[-1][0] != end:
        points.append(TrajectoryPoint(end, _total_on(profile, end, expiry)))
    return Trajectory(points=points, cliffs=cliffs)
