"""Tests for the reachable-path engine.

Covers classification (reachable / within-reach / blocked / needs-check), the
shortest-move catalog, eligibility derivation, and the BC PNP branch. The exact
CRS numbers come from the validated engine; here we assert the interpretation.
"""
from datetime import date

from crs import LanguageScores, Profile
from pnp import BCJobOffer
from paths import Draw, reachable_paths


def L(clb):
    return LanguageScores(clb, clb, clb, clb)


def _p(**kw):
    base = dict(age=29, education="bachelors-or-three-year", first_language=L(8),
                canadian_work_years=1, foreign_work_years=0)
    base.update(kw)
    return Profile(**base)


DAY = date(2026, 8, 22)


def _draw(**kw):
    base = dict(kind="general", name="EE general", cutoff=500, date=DAY,
                source="https://canada.ca/rounds")
    base.update(kw)
    return Draw(**base)


# --- classification -----------------------------------------------------------
def test_clears_when_score_meets_cutoff():
    # a very strong profile clears a low cutoff
    strong = _p(first_language=L(10), education="masters-or-professional",
                canadian_work_years=3, has_provincial_nomination=True)
    r = reachable_paths(strong, [_draw(cutoff=450)], as_of=DAY)
    assert len(r.reachable) == 1 and not r.within_reach and not r.blocked


def test_within_reach_lists_a_closing_move_cheapest_first():
    p = _p()  # mid profile, general cutoff just above it
    score = reachable_paths(p, [_draw(cutoff=9999)], as_of=DAY)  # force gap to read score
    your = score.blocked[0].your_score if score.blocked else None
    assert your is not None
    r = reachable_paths(p, [_draw(cutoff=your + 30)], as_of=DAY)
    assert len(r.within_reach) == 1
    moves = r.within_reach[0].closing_moves
    assert moves and all(m.closes_gap for m in moves)
    # nomination (+600) is always a closer, so a within-reach draw is never empty
    assert any("nomination" in m.move for m in moves)
    # cheapest-first ordering: effort tier is non-decreasing
    order = {"small": 0, "medium": 1, "large": 2}
    tiers = [order[m.effort] for m in moves]
    assert tiers == sorted(tiers)


def test_nomination_always_closes_a_federal_gap():
    p = _p()
    # an absurd cutoff no single lever but +600 could close from a mid score
    your = reachable_paths(p, [_draw(cutoff=9999)], as_of=DAY).blocked[0].your_score
    r = reachable_paths(p, [_draw(cutoff=your + 550)], as_of=DAY)
    assert r.within_reach and any("nomination" in m.move
                                  for m in r.within_reach[0].closing_moves)


def test_blocked_when_no_single_move_closes():
    p = _p()
    r = reachable_paths(p, [_draw(cutoff=1300)], as_of=DAY)  # above the 1200 ceiling
    assert len(r.blocked) == 1 and not r.within_reach


# --- eligibility --------------------------------------------------------------
def test_french_category_eligibility_is_derived():
    ineligible = _p()
    elig = _p(second_language=L(7), second_language_is_french=True)
    d = _draw(kind="category", category="french", name="French-language", cutoff=400)
    assert reachable_paths(ineligible, [d], as_of=DAY).blocked  # not eligible -> blocked
    r = reachable_paths(elig, [d], as_of=DAY)
    assert r.reachable  # eligible and clears the low cutoff


def test_occupation_category_needs_noc_check_unless_overridden():
    d = Draw(kind="category", name="Healthcare", cutoff=400, date=DAY,
             source="src", category="healthcare")
    r = reachable_paths(_p(), [d], as_of=DAY)
    assert len(r.needs_eligibility_check) == 1
    assert r.needs_eligibility_check[0].eligible is None
    # caller can assert eligibility (e.g. after a NOC-list match): it then leaves
    # the needs-check bucket and is scored like any other draw
    d2 = Draw(kind="category", name="Healthcare", cutoff=400, date=DAY,
              source="src", category="healthcare", eligible_override=True)
    r2 = reachable_paths(_p(), [d2], as_of=DAY)
    assert not r2.needs_eligibility_check
    assert (r2.reachable or r2.within_reach)
    scored = (r2.reachable or r2.within_reach)[0]
    assert scored.eligible is True


# --- BC PNP branch ------------------------------------------------------------
def test_pnp_without_offer_is_blocked_and_flags_offer_required():
    d = Draw(kind="pnp_bc", name="BC PNP Skilled Worker", cutoff=100, date=DAY, source="src")
    r = reachable_paths(_p(), [d], as_of=DAY, bc_offer=None)
    assert r.blocked and r.blocked[0].job_offer_required is True
    assert r.blocked[0].crs_bonus_if_nominated == 600


def test_pnp_with_strong_offer_can_clear():
    d = Draw(kind="pnp_bc", name="BC PNP Skilled Worker", cutoff=80, date=DAY, source="src")
    offer = BCJobOffer(hourly_wage=55, area="northern_bc")
    r = reachable_paths(_p(canadian_work_years=3), [d], as_of=DAY, bc_offer=offer)
    assert r.reachable and r.reachable[0].score_kind == "SIRS"
