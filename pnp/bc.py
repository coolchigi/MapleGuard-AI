"""BC PNP SIRS scorer (first province).

SIRS is scored out of 200: human capital (work experience 40, education 40,
language 40 = 120) + economic (hourly wage 55, area of employment 25 = 80). A
provincial nomination adds 600 to CRS, which effectively guarantees a federal
ITA. Most BC Skills Immigration streams require a full-time indeterminate BC job
offer; certain Tech occupations are job-offer-exempt for registration.

STATUS: the factor structure and maxes are confirmed and stable (no major 2026
change). The exact point BANDS below are best-effort and marked verified=False
until line-checked against the official BC PNP Program Guide. `sirs_bc` is safe
to use for structure/eligibility/flags now; do not trust exact sub-scores until
the bands are verified (see TODO). Pure functions, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from crs.models import Profile
from crs.tables import Table

PROVINCIAL_NOMINATION_CRS_BONUS = 600
SIRS_MAX = 200

# --- Band tables (VERIFY against the BC PNP Program Guide) ---------------------
WORK_EXPERIENCE = Table("bc_work_experience", False, {0: 0, 1: 8, 2: 16, 3: 24, 4: 32, 5: 40})
EDUCATION = Table("bc_education", False, {
    "none-or-less-than-secondary": 0, "secondary": 5,
    "one-year-post-secondary": 15, "two-year-post-secondary": 20,
    "bachelors-or-three-year": 27, "two-or-more-certificates": 27,
    "masters-or-professional": 37, "doctoral": 40,
})
LANGUAGE = Table("bc_language", False, {4: 5, 5: 10, 6: 15, 7: 20, 8: 30, 9: 35, 10: 40})
# Hourly wage (CAD) -> points. Keys are the lower bound of each band.
WAGE = Table("bc_wage", False, {
    0: 0, 16: 4, 18: 8, 20: 12, 22: 16, 24: 20, 26: 24, 28: 28, 30: 32,
    32: 36, 34: 40, 36: 44, 40: 48, 45: 51, 50: 53, 70: 55,
})
# Area of employment: Metro Vancouver lowest, rural/north highest.
AREA = Table("bc_area", False, {"metro_vancouver": 5, "other_lower_mainland": 10,
                                "rest_of_bc": 15, "northern_bc": 25})

ALL_TABLES = [WORK_EXPERIENCE, EDUCATION, LANGUAGE, WAGE, AREA]
FACTOR_MAX = {"work_experience": 40, "education": 40, "language": 40, "wage": 55, "area": 25}


@dataclass(frozen=True)
class BCJobOffer:
    hourly_wage: float
    area: str = "metro_vancouver"          # key into AREA
    is_tech_exempt: bool = False           # a job-offer-exempt Tech occupation


@dataclass(frozen=True)
class SirsLine:
    factor: str
    points: int


@dataclass(frozen=True)
class SirsResult:
    score: int                             # out of 200
    breakdown: list[SirsLine]
    job_offer_required: bool
    eligible_to_register: bool
    crs_bonus_if_nominated: int = PROVINCIAL_NOMINATION_CRS_BONUS


def _min_clb(profile: Profile) -> int:
    fl = profile.first_language
    return min(fl.speaking, fl.listening, fl.reading, fl.writing)


def _clb_bucket(clb: int) -> int | None:
    if clb < 4:
        return None
    return 10 if clb >= 10 else clb


def _band(table: dict, value: float) -> int:
    """Highest band whose lower-bound key is <= value (0 if below the lowest)."""
    keys = sorted(k for k in table if k <= value)
    return table[keys[-1]] if keys else 0


def _capped(points: int, factor: str) -> int:
    return min(points, FACTOR_MAX[factor])


def sirs_bc(profile: Profile, offer: Optional[BCJobOffer] = None) -> SirsResult:
    """BC SIRS score (out of 200) for a profile, given an optional BC job offer."""
    years = min(max(profile.canadian_work_years + profile.foreign_work_years, 0), 5)
    clb = _clb_bucket(_min_clb(profile))

    work = _capped(_band(WORK_EXPERIENCE.values, years), "work_experience")
    edu = _capped(EDUCATION.values[profile.education], "education")
    lang = _capped(LANGUAGE.values.get(clb, 0) if clb else 0, "language")

    # Economic factors require a job offer.
    if offer is not None:
        wage = _capped(_band(WAGE.values, offer.hourly_wage), "wage")
        area = _capped(AREA.values.get(offer.area, 0), "area")
    else:
        wage = area = 0

    # Most streams need an offer; Tech has job-offer-exempt occupations.
    tech_exempt = bool(offer and offer.is_tech_exempt)
    job_offer_required = not tech_exempt
    eligible = offer is not None or tech_exempt

    lines = [
        SirsLine("work_experience", work),
        SirsLine("education", edu),
        SirsLine("language", lang),
        SirsLine("wage", wage),
        SirsLine("area", area),
    ]
    return SirsResult(
        score=min(SIRS_MAX, sum(l.points for l in lines)),
        breakdown=lines,
        job_offer_required=job_offer_required,
        eligible_to_register=eligible,
    )
