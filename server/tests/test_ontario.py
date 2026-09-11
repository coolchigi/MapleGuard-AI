"""OINP (Ontario) Workforce Priority Stream floors, pinned to the official 2026 redesign.

Ontario removed its 8 former streams on June 26, 2026 and now runs one job-offer-based stream. We
never assert OINP eligibility (it turns on an Ontario job offer we do not collect); we check the
published skill floors and say the job offer is the binding requirement. Source: ontario.ca.

Run:  cd server && PYTHONPATH=. python3 -m pytest -q tests/test_ontario.py
"""
from crs import LanguageScores, Profile
from paths import eligible_pathways
from pnp import oinp_standing


def L(clb):
    return LanguageScores(clb, clb, clb, clb)


def test_meets_teer_0_3_floor_but_still_needs_a_job_offer():
    p = Profile(age=30, education="masters-or-professional", first_language=L(9))
    s = oinp_standing(p)
    assert s.meets_teer_0_3_floor is True
    assert s.requires_ontario_job_offer is True
    assert "job offer" in s.reason.lower()


def test_low_skilled_profile_meets_only_the_teer_4_5_floor():
    # CLB 4 + secondary clears TEER 4-5 but not TEER 0-3 (which needs CLB 6 + post-secondary).
    p = Profile(age=30, education="secondary", first_language=L(4))
    s = oinp_standing(p)
    assert s.meets_teer_0_3_floor is False
    assert s.meets_teer_4_5_floor is True


def test_ontario_is_never_asserted_eligible_from_a_profile_alone():
    p = Profile(age=30, education="masters-or-professional", first_language=L(9))
    ontario = next(x for x in eligible_pathways(p).pathways if x.slug == "pnp-ontario")
    assert ontario.eligible is None  # eligibility needs the Ontario job offer we do not collect
    assert "ontario.ca" in ontario.source_url
