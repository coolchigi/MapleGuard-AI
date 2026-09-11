"""Ontario Immigrant Nominee Program (OINP): the Ontario Workforce Priority Stream eligibility gate.

Ontario rebuilt the OINP on June 26, 2026: all eight former streams (Human Capital Priorities, the
Employer Job Offer streams, Masters/PhD Graduate, French-Speaking Skilled Worker, Skilled Trades,
Entrepreneur) were removed and replaced by ONE stream, the Ontario Workforce Priority Stream. That
change is why the old "OINP draws from the Express Entry pool by CRS" story is out of date.

The defining fact of the new stream, and the honest thing to tell a candidate: **every pathway
requires a full-time, permanent job offer in Ontario** (the one exception is self-employed
physicians registered with the College of Physicians and Surgeons of Ontario). MapleGuard does not
collect a candidate's job-offer status, so we never assert OINP eligibility. What we CAN check from
the profile is whether they clear the stream's published skill floors, and then we state plainly
that an Ontario job offer is the binding requirement.

Published minimums (ontario.ca, read 2026-09-11):
- TEER 0-3 pathway: CLB 6 (CLB 5 for certain occupations) + a post-secondary degree or diploma.
- TEER 4-5 pathway: CLB 4 + a secondary-school diploma or equivalent.
Both also require the Ontario job offer and qualifying work experience.

Source: Government of Ontario, "2026 Ontario Immigrant Nominee Program Updates" (Ontario Workforce
Priority stream overview). https://www.ontario.ca/page/2026-ontario-immigrant-nominee-program-updates
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from crs.models import Profile

OINP_SOURCE_URL = "https://www.ontario.ca/page/2026-ontario-immigrant-nominee-program-updates"
OINP_SOURCE_DATE = date(2026, 9, 11)

_POST_SECONDARY = {
    "one-year-post-secondary", "two-year-post-secondary", "bachelors-or-three-year",
    "two-or-more-certificates", "masters-or-professional", "doctoral",
}


@dataclass(frozen=True)
class OinpStanding:
    """Whether the candidate clears the Ontario Workforce Priority Stream skill floors, and the
    binding requirement they cannot clear from a profile alone (the Ontario job offer). `eligible`
    is None on purpose: eligibility turns on a job offer we do not collect, so we never assert it."""
    meets_teer_0_3_floor: bool     # CLB 6 + post-secondary
    meets_teer_4_5_floor: bool     # CLB 4 + secondary or above
    reason: str
    requires_ontario_job_offer: bool = True
    source_url: str = OINP_SOURCE_URL
    source_date: date = OINP_SOURCE_DATE


def oinp_standing(profile: Profile, as_of: Optional[date] = None) -> OinpStanding:
    """The candidate's standing against the Ontario Workforce Priority Stream floors. Pure."""
    clb = profile.first_language.min_clb()
    has_post_secondary = profile.education in _POST_SECONDARY
    has_secondary = profile.education != "none-or-less-than-secondary"

    teer_0_3 = clb >= 6 and has_post_secondary
    teer_4_5 = clb >= 4 and has_secondary

    if teer_0_3:
        floor = "meet the TEER 0-3 skill floor (CLB 6 and post-secondary)"
    elif teer_4_5:
        floor = "meet the TEER 4-5 skill floor (CLB 4 and secondary), not the TEER 0-3 floor"
    else:
        floor = "do not meet the stream's language and education minimums"

    reason = (f"OINP is now the single Ontario Workforce Priority Stream (redesigned June 2026). "
              f"You {floor}, but every pathway requires a full-time, permanent Ontario job offer "
              f"(only self-employed physicians registered in Ontario are exempt), which is the "
              f"binding requirement and is not something we can verify from your profile")
    return OinpStanding(meets_teer_0_3_floor=teer_0_3, meets_teer_4_5_floor=teer_4_5, reason=reason)
