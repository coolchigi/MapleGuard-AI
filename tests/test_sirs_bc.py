"""Tests for the BC PNP SIRS scorer.

Structure, caps, eligibility, and monotonicity are asserted now. Exact band
totals are NOT asserted while the bands are unverified (see xfail below).
"""
import pytest

from crs import LanguageScores, Profile
from pnp import BCJobOffer, PROVINCIAL_NOMINATION_CRS_BONUS, sirs_bc
from pnp import bc as B


def L(clb):
    return LanguageScores(clb, clb, clb, clb)


def _p(**kw):
    base = dict(age=30, education="bachelors-or-three-year",
                first_language=L(8), canadian_work_years=3, foreign_work_years=0)
    base.update(kw)
    return Profile(**base)


def test_score_in_range():
    r = sirs_bc(_p(), BCJobOffer(hourly_wage=35, area="rest_of_bc"))
    assert 0 <= r.score <= B.SIRS_MAX


def test_each_factor_within_cap():
    r = sirs_bc(_p(), BCJobOffer(hourly_wage=200, area="northern_bc"))
    caps = B.FACTOR_MAX
    for line in r.breakdown:
        assert line.points <= caps[line.factor]


def test_no_offer_zeros_economic_and_flags_required():
    r = sirs_bc(_p(), offer=None)
    econ = {l.factor: l.points for l in r.breakdown}
    assert econ["wage"] == 0 and econ["area"] == 0
    assert r.job_offer_required is True
    assert r.eligible_to_register is False


def test_tech_exempt_is_eligible_without_offer_semantics():
    r = sirs_bc(_p(), BCJobOffer(hourly_wage=45, is_tech_exempt=True))
    assert r.job_offer_required is False
    assert r.eligible_to_register is True


def test_higher_wage_never_scores_less():
    lo = sirs_bc(_p(), BCJobOffer(hourly_wage=20)).score
    hi = sirs_bc(_p(), BCJobOffer(hourly_wage=50)).score
    assert hi >= lo


def test_nomination_bonus_is_600():
    assert PROVINCIAL_NOMINATION_CRS_BONUS == 600
    assert sirs_bc(_p(), BCJobOffer(hourly_wage=30)).crs_bonus_if_nominated == 600


@pytest.mark.xfail(reason="SIRS bands not yet line-verified against the BC PNP Program Guide")
def test_sirs_bands_verified():
    assert all(t.verified for t in B.ALL_TABLES)
