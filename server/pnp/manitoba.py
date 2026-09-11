"""Manitoba Provincial Nominee Program (MPNP): the Skilled Worker self-assessment points grid.

A deterministic score from the OFFICIAL MPNP Self-Assessment Worksheet (immigratemanitoba.com,
the government points grid PDF read 2026-09-11). Same treatment as BC's SIRS and Saskatchewan's
SINP: transcribe the grid, compute what the profile determines, never invent the rest.

Two things make MPNP different from a plain score:
- **A Manitoba connection is mandatory.** Factor 5 (Adaptability) requires a close relative in
  Manitoba, past MB work or study, a friend/distant relative there, or an Invitation through a
  Strategic Recruitment Initiative. Without one you are NOT eligible regardless of your total. We
  do not collect connection information, so we NEVER assert MPNP eligibility (it stays None).
- The floor to apply is 60 of 100 points, INCLUDING the connection.

So we compute Factors 1-4 (language, age, work experience, education, max 75), which are all
determinate from the profile, and state plainly that the mandatory Manitoba connection (Factor 5)
is unassessed here. Work experience uses total years (the grid counts full-time work in the last
five years), which can slightly over-count someone whose experience is older, so we do not treat
the subtotal as a guarantee.

Source: Manitoba Provincial Nominee Program, "MPNP Self-Assessment Points" worksheet.
https://immigratemanitoba.com/wp-content/uploads/2025/06/manitoba-immigration-mpnp-points-worksheet-interactive-2.pdf
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from crs.models import Profile

MPNP_SOURCE_URL = ("https://immigratemanitoba.com/wp-content/uploads/2025/06/"
                   "manitoba-immigration-mpnp-points-worksheet-interactive-2.pdf")
MPNP_SOURCE_DATE = date(2026, 9, 11)
MPNP_MIN_POINTS = 60           # "you must score at least 60 points" (official)
MPNP_FACTORS_1_4_MAX = 75      # language 25 + age 10 + work 15 + education 25


def _language_points(profile: Profile) -> int:
    """Factor 1 (max 25): first language by CLB band + 5 for a second language at CLB 5+."""
    clb = profile.first_language.min_clb()
    first = 20 if clb >= 8 else {7: 18, 6: 16, 5: 14, 4: 12}.get(clb, 0)
    second = 5 if (profile.second_language and profile.second_language.min_clb() >= 5) else 0
    return first + second


def _age_points(profile: Profile, as_of: Optional[date]) -> int:
    """Factor 2 (max 10)."""
    a = profile.age_at(as_of)
    if 21 <= a <= 45:
        return 10
    return {18: 4, 19: 6, 20: 8, 46: 8, 47: 6, 48: 4, 49: 2}.get(a, 0)


def _work_points(profile: Profile) -> int:
    """Factor 3 (max 15). Total full-time years, capped at the grid's top band (4+)."""
    years = profile.canadian_work_years + profile.foreign_work_years
    if years >= 4:
        return 15
    return {0: 0, 1: 8, 2: 10, 3: 12}[years]


def _education_points(profile: Profile) -> int:
    """Factor 4 (max 25). A trade certificate is worth 14."""
    by_level = {
        "doctoral": 25,                    # Master's or Doctorate
        "masters-or-professional": 25,
        "two-or-more-certificates": 23,    # two post-secondary programs of >=2 years each
        "bachelors-or-three-year": 20,     # one post-secondary program of two years or longer
        "two-year-post-secondary": 20,
        "one-year-post-secondary": 14,     # one one-year post-secondary program
        "secondary": 0,
        "none-or-less-than-secondary": 0,
    }
    pts = by_level.get(profile.education, 0)
    if profile.has_certificate_of_qualification:
        pts = max(pts, 14)                 # trade certification
    return pts


@dataclass(frozen=True)
class MpnpStanding:
    """The candidate's MPNP Factors 1-4 subtotal and what it means, cited. `eligible` is always
    None: MPNP requires a Manitoba connection (Factor 5) that we do not collect, so we never assert
    eligibility. `clears_floor_before_connection` is True when Factors 1-4 already reach the 60
    floor, meaning a single connection point would satisfy both the floor and the mandatory
    connection."""
    factors_1_4: int
    clears_floor_before_connection: bool
    breakdown: list = field(default_factory=list)
    minimum: int = MPNP_MIN_POINTS
    factors_1_4_max: int = MPNP_FACTORS_1_4_MAX
    source_url: str = MPNP_SOURCE_URL
    source_date: date = MPNP_SOURCE_DATE


def mpnp_points(profile: Profile, as_of: Optional[date] = None) -> MpnpStanding:
    """Compute the candidate's MPNP Factors 1-4 subtotal from the official grid. Pure."""
    items = [
        ("language", _language_points(profile)),
        ("age", _age_points(profile, as_of)),
        ("work_experience", _work_points(profile)),
        ("education", _education_points(profile)),
    ]
    subtotal = sum(v for _, v in items)
    return MpnpStanding(factors_1_4=subtotal, clears_floor_before_connection=subtotal >= MPNP_MIN_POINTS,
                        breakdown=[{"factor": k, "points": v} for k, v in items])
