# Turning a score into a timeline: CRS as a function of dates

A CRS score is usually treated as a snapshot. You compute it today and file the number away. But two of its inputs are functions of the calendar: your age, and whether your language results are still valid. That means your score on any future date is computable today, from the same profile, with no new information.

Once the engine takes a date, the timeline is not a new subsystem. It is the engine called repeatedly at future dates, with the profile adjusted for what will have expired by then. This post walks through `crs/timeline.py`.

## The engine already takes a date

The foundation is that age is derived from a date of birth, not stored as a fixed integer:

```python
def age_at(self, as_of: Optional[date] = None) -> int:
    """Effective age. Prefers date_of_birth (as of `as_of`, default today) over static `age`."""
    if self.date_of_birth is not None:
        d = as_of or date.today()
        dob = self.date_of_birth
        return d.year - dob.year - ((d.month, d.day) < (dob.month, dob.day))
    return self.age
```

So `crs(profile, as_of)` is a pure function of the profile and the date. Everything in the timeline is built on calling it at different values of `as_of`.

## The two things that move on the calendar

**Age brackets.** Age points are flat through the twenties, then step down each year from 30, reaching zero at 45. A birthday that crosses a bracket boundary lowers the score with nothing else changing.

**Test expiry.** Language results are valid for two years. On lapse, the candidate's language points fall away, and so does the skill-transfer that those language levels unlocked. The timeline models this by recomputing the score on a profile whose first-language results have been zeroed:

```python
LANGUAGE_TEST_VALIDITY_YEARS = 2
AGE_FLOOR = 45  # age at which age points reach 0


def _expiry(profile: Profile) -> date | None:
    d = profile.first_language_test_date
    return d.replace(year=d.year + LANGUAGE_TEST_VALIDITY_YEARS) if d else None


def _expired(profile: Profile) -> Profile:
    """Profile with first-language results lapsed (points, incl. transfer, drop to 0)."""
    return replace(profile, first_language=LanguageScores(0, 0, 0, 0))


def _total_on(profile: Profile, d: date, expiry: date | None) -> int:
    p = _expired(profile) if (expiry and d >= expiry) else profile
    return crs(p, d).total
```

`_total_on` is the whole trick. Ask for the score on a date, and it decides whether the test has expired by then, swaps in the lapsed profile if so, and calls the ordinary engine. Because zeroing first-language scores also removes their skill-transfer contribution, the drop at expiry is larger than the language points alone. It is the language block plus the transfer points those levels were unlocking.

## A cliff is a one-day difference

An event's size is defined as the score on the event day minus the score the day before. That is one subtraction of two pure recomputations:

```python
def _cliff_at(profile: Profile, d: date, kind: str, label: str, expiry: date | None) -> Cliff:
    delta = _total_on(profile, d, expiry) - _total_on(profile, d - timedelta(days=1), expiry)
    return Cliff(date=d, kind=kind, label=label, delta=delta)
```

There is no separate formula for "how much does expiry cost." The cost is whatever the engine says the difference is, which means the cliff size stays correct automatically if the underlying grids ever change.

## `deadlines()`: the dated events that move the score

`deadlines()` walks the birthdays out to the age floor, computes the delta at each, and keeps only the ones that actually move the number. It then computes the test-expiry cliff if an expiry date exists and is still in the future.

```python
def deadlines(profile: Profile, as_of: date | None = None) -> Deadlines:
    dob = _require_dob(profile)
    today = as_of or date.today()
    expiry = _expiry(profile)

    age_cliffs: list[Cliff] = []
    horizon = _birthday(dob, dob.year + AGE_FLOOR)
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
```

## `trajectory()`: the same recomputation, plotted

`trajectory()` collects the events in a date range, sorts them, and records the score at the start, at each event, and at the end. Same `_total_on`, more points.

```python
def trajectory(profile: Profile, start: date, end: date) -> Trajectory:
    _require_dob(profile)
    ...
    points = [TrajectoryPoint(start, _total_on(profile, start, expiry))]
    cliffs: list[Cliff] = []
    for d, kind, label in events:
        points.append(TrajectoryPoint(d, _total_on(profile, d, expiry)))
        cliffs.append(_cliff_at(profile, d, kind, label, expiry))
    if not events or events[-1][0] != end:
        points.append(TrajectoryPoint(end, _total_on(profile, end, expiry)))
    return Trajectory(points=points, cliffs=cliffs)
```

## A real cliff sequence

Here is the actual output for an illustrative profile (not anyone's real data): a bachelor's degree, CLB 9 across all four abilities, three years of foreign work, one year of Canadian work, born 1994-11-03, with a language test taken 2024-03-01, evaluated as of 2024-01-01.

```python
p = Profile(education="bachelors-or-three-year", first_language=L(9),
            date_of_birth=date(1994, 11, 3), canadian_work_years=1,
            foreign_work_years=3, first_language_test_date=date(2024, 3, 1))
```

Today's score is 482. The dated events that follow:

```
age        2024-11-03   -5     turns 30, first bracket step
age        2025-11-03   -6
test       2026-03-01  -174    language points + their skill-transfer drop to 0
age        2026-11-03   -5
...
age        2035-11-03  -11     later brackets drop harder
```

The test-expiry event is the one that hurts, at −174 for this profile, because it removes the language block and the skill-transfer those levels unlocked at the same time. The exact figure depends on the profile, so it is computed, never assumed. And it sits on a date that is fully knowable in advance, which is the entire point. Two years and a day after a test, a candidate who did nothing wrong can lose enough points to be pulled from the pool. The timeline surfaces that date ahead of time so there is a window to retake before the cliff, not after.

Everything here is a repeated call to one pure function. The novelty is not a clever forecasting method. It is the recognition that the score already is a function of dates, so the future is not a prediction, it is a recomputation.

The model reaches this the same way it reaches the score itself: through Strands tools, `crs_trajectory` and `crs_deadlines`, that call `trajectory()` and `deadlines()` and hand back the points and the dated cliffs. The model can explain the cliff and suggest acting before it, but the dates and the deltas are computed underneath it, not narrated by it.
