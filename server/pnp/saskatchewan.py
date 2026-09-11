"""Saskatchewan Immigrant Nominee Program (SINP): the International Skilled Worker points grid.

A deterministic score from the OFFICIAL SINP point assessment grid (saskatchewan.ca, read
2026-09-11), the same "compute it, cite it, never guess" treatment BC's SIRS gets. Every point
value below is transcribed from that grid.

What we compute and what we honestly do NOT:
- We compute FACTOR I (labour-market success, max 80): education, skilled work experience,
  first/second official language, and age. These are all determinate from the candidate profile.
- We do NOT compute FACTOR II (connection to Saskatchewan + adaptability): a close family relative
  in Saskatchewan, past SK work or study, or a Saskatchewan job offer. MapleGuard does not collect
  those, so we never invent them, we report Factor I and say the connection points are unassessed.
- Work experience: the official grid splits into "last 5 years" and "6 to 10 years prior". The
  profile carries total years, not a recency split, so we count only the last-5-years band (the
  candidate's total, capped at 5). This UNDER-counts someone with 6+ years, which is the safe
  direction (never inflate a score).

The floor: you need at least 60 of the grid's points to be allowed to submit an EOI. Meeting it is
NOT an invitation: SINP invites by Expression-of-Interest draws that select on in-demand occupation
and provincial labour need, and can change at any time (there were no scheduled draws when this was
written). So a candidate who clears 60 has met the points floor to enter the pool, nothing more.

Source: Saskatchewan Immigrant Nominee Program, "Assess Your Eligibility" (SINP point assessment
grid). https://www.saskatchewan.ca/residents/moving-to-saskatchewan/live-in-saskatchewan/by-immigrating/saskatchewan-immigrant-nominee-program/assess-your-eligibility
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from crs.models import Profile

SINP_SOURCE_URL = ("https://www.saskatchewan.ca/residents/moving-to-saskatchewan/"
                   "live-in-saskatchewan/by-immigrating/saskatchewan-immigrant-nominee-program/"
                   "assess-your-eligibility")
SINP_SOURCE_DATE = date(2026, 9, 11)
SINP_MIN_POINTS = 60          # "You need at least 60 points to apply." (official)
SINP_FACTOR_I_MAX = 80        # "MAXIMUM POINTS FOR FACTOR I  80" (official)


def _education_points(profile: Profile) -> int:
    """SINP education/training points. A trade certificate (journeyperson-equivalent) is worth 20,
    so a candidate holding one gets at least that."""
    by_level = {
        "doctoral": 23,                    # Master's or Doctorate
        "masters-or-professional": 23,
        "bachelors-or-three-year": 20,     # Bachelor's OR a 3+ year degree
        "two-or-more-certificates": 20,    # one being a 3+ year credential
        "two-year-post-secondary": 15,     # 2 (but <3) year diploma
        "one-year-post-secondary": 12,     # certificate / >=2 semesters but <2-year
        "secondary": 0,                    # SINP requires post-secondary
        "none-or-less-than-secondary": 0,
    }
    pts = by_level.get(profile.education, 0)
    if profile.has_certificate_of_qualification:
        pts = max(pts, 20)                 # trade certification equivalent to journeyperson
    return pts


def _work_points(profile: Profile) -> int:
    """Skilled work experience, last-5-years band only (see module note). Total years capped at 5."""
    years = min(profile.canadian_work_years + profile.foreign_work_years, 5)
    return {0: 0, 1: 2, 2: 4, 3: 6, 4: 8, 5: 10}[years]


def _first_language_points(profile: Profile) -> int:
    clb = profile.first_language.min_clb()
    if clb >= 8:
        return 20
    return {7: 18, 6: 16, 5: 14, 4: 12}.get(clb, 0)


def _second_language_points(profile: Profile) -> int:
    if not profile.second_language:
        return 0
    clb = profile.second_language.min_clb()
    if clb >= 8:
        return 10
    return {7: 8, 6: 6, 5: 4, 4: 2}.get(clb, 0)


def _age_points(profile: Profile, as_of: Optional[date]) -> int:
    a = profile.age_at(as_of)
    if a < 18 or a > 50:
        return 0
    if a <= 21:
        return 8
    if a <= 34:
        return 12
    if a <= 45:
        return 10
    return 8  # 46-50


@dataclass(frozen=True)
class SinpStanding:
    """The candidate's SINP Factor I score and what it means, cited. `meets_points_floor` is True
    only when Factor I alone already clears the 60-point floor; None when it does not, because the
    unassessed Saskatchewan-connection points (Factor II) could still lift them to 60. Never a
    claim of an invitation, which SINP gates on in-demand occupation and its draws."""
    factor_one: int
    meets_points_floor: Optional[bool]
    breakdown: list = field(default_factory=list)
    minimum: int = SINP_MIN_POINTS
    factor_one_max: int = SINP_FACTOR_I_MAX
    source_url: str = SINP_SOURCE_URL
    source_date: date = SINP_SOURCE_DATE


def sinp_points(profile: Profile, as_of: Optional[date] = None) -> SinpStanding:
    """Compute the candidate's SINP Factor I score from the official grid. Pure and deterministic."""
    items = [
        ("education", _education_points(profile)),
        ("work_experience", _work_points(profile)),
        ("first_language", _first_language_points(profile)),
        ("second_language", _second_language_points(profile)),
        ("age", _age_points(profile, as_of)),
    ]
    factor_one = sum(v for _, v in items)
    # Factor I alone can meet the 60 floor -> True. If not, the unassessed connection points might
    # still lift them there, so it is an honest "cannot decide" (None), never a False we cannot back.
    meets = True if factor_one >= SINP_MIN_POINTS else None
    return SinpStanding(factor_one=factor_one, meets_points_floor=meets,
                        breakdown=[{"factor": k, "points": v} for k, v in items])
