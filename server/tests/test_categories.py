"""Tests for the 2026 category-based selection rules and eligibility check.

Data-integrity tests compare the encoded ruleset against a saved snapshot of the official
page (ingest/fixtures/category_rules_2026.json) -- no network. Eligibility and slug-resolution
tests are pure. The reach wiring is exercised end to end with a real Draw + Profile.

Run:  cd agents-for-humans/mapleguard && PYTHONPATH=. python3 -m pytest -q
"""
import json
from datetime import date
from pathlib import Path

from ingest import (CATEGORY_RULES, CANONICAL_SLUGS, category_eligibility,
                    categories_for_noc, resolve_category, classify)
from ingest.categories import CATEGORY_NOC_TITLES
from crs import Profile, EducationLevel, LanguageScores
from paths import Draw, reachable_paths

FIXTURE = Path(__file__).resolve().parent.parent / "ingest" / "fixtures" / "category_rules_2026.json"
DAY = date(2026, 8, 26)


# --- Data integrity: encoded rules match the saved snapshot of source ----------------
def test_ten_categories_seeded():
    assert len(CATEGORY_RULES) == 10
    assert set(CANONICAL_SLUGS) == set(CATEGORY_RULES)


def test_noc_lists_match_official_snapshot():
    snapshot = json.loads(FIXTURE.read_text())
    # snapshot keys are official titles -> canonical slug via resolve_category
    by_slug = {}
    for title, codes in snapshot.items():
        slug = resolve_category(title)
        assert slug is not None, f"unresolved category title: {title}"
        by_slug[slug] = set(codes)
    for slug, rule in CATEGORY_RULES.items():
        if rule.rule_kind == "language":
            assert not rule.noc_codes
            continue
        assert set(rule.noc_codes) == by_slug[slug], f"{slug} drifted from source snapshot"


def test_every_code_has_a_title_and_is_verified():
    for rule in CATEGORY_RULES.values():
        assert rule.verified is True
        assert "canada.ca" in rule.source_url and rule.source_date == date(2026, 6, 22)
        for code in rule.noc_codes:
            assert code in CATEGORY_NOC_TITLES


def test_agriculture_is_not_a_2026_category():
    # It was a 2023-2024 category; verifying against source kept it out.
    assert resolve_category("Agriculture and agri-food occupations") is None


# --- Slug resolution lines up with the ingest draw slugs -----------------------------
def test_resolve_maps_ingest_draw_slugs_to_canonical_keys():
    # Drive real draw names through ingest.classify, then confirm resolve_category lands on
    # a rule key -- proving the two vocabularies line up.
    cases = {
        "Healthcare and Social Services Occupations, 2026-Version 3": "healthcare",
        "STEM occupations (Version 1)": "stem",
        "Trades Occupations, 2026-Version 3": "trades",
        "Education occupations (Version 1)": "education",
        "Transport occupations (Version 1)": "transport",
        "French-Language proficiency 2026-Version 2": "french",
        "Physicians with Canadian Work Experience, 2026-Version 1": "physicians",
        "Senior managers with Canadian Work Experience, 2026-Version 1": "senior-managers",
        "Skilled Military Recruits, 2026-Version 1": "skilled-military",
    }
    for draw_name, expected in cases.items():
        _kind, ingest_slug, _note = classify(draw_name)
        assert resolve_category(ingest_slug) == expected, f"{draw_name} via slug {ingest_slug}"
        assert resolve_category(draw_name) == expected   # raw name resolves too


def test_non_category_draws_resolve_to_none():
    # Provincial-nominee and program-specific draws are not category-based-selection rules.
    assert resolve_category("provincial-nominee") is None
    assert resolve_category("General") is None
    assert resolve_category("canadian-experience-class") is None


# --- Eligibility: occupation categories ---------------------------------------------
def test_noc_in_list_is_eligible_with_cited_reason():
    r = category_eligibility("stem", noc_code="21220")   # Cybersecurity specialists
    assert r.eligible is True
    assert "21220" in r.reason and "STEM" in r.reason
    assert "canada.ca" in r.source_url
    assert r.additional_requirements                     # the unmodeled experience condition


def test_noc_not_in_list_is_ineligible():
    r = category_eligibility("stem", noc_code="63201")   # Butchers -> trades, not STEM
    assert r.eligible is False and "not in" in r.reason


def test_missing_noc_code_is_unknown_not_guessed():
    r = category_eligibility("healthcare", noc_code=None)
    assert r.eligible is None
    assert "provide the candidate's NOC code" in r.reason


def test_categories_for_noc_finds_overlaps():
    # 31100 is on both healthcare and physicians lists.
    assert set(categories_for_noc("31100")) == {"healthcare", "physicians"}
    assert categories_for_noc("00000") == []


# --- Eligibility: French language rule ----------------------------------------------
def test_french_rule_uses_nclc7():
    assert category_eligibility("french", french_nclc=7).eligible is True
    assert category_eligibility("french", french_nclc=6).eligible is False
    assert category_eligibility("french", french_nclc=None).eligible is None


# --- End to end through reachable_paths ---------------------------------------------
def _profile(noc_code=None, french=None):
    return Profile(
        education="bachelors-or-three-year",
        first_language=LanguageScores(9, 9, 9, 9),
        age=30, canadian_work_years=2,
        second_language=LanguageScores(*([french] * 4)) if french else None,
        second_language_is_french=french is not None,
        noc_code=noc_code,
    )


def _cat_draw(category, cutoff=400):
    return Draw(kind="category", name=category, cutoff=cutoff, date=DAY,
                source="https://canada.ca/rounds", category=category)


def test_reachable_paths_decides_occupation_category_from_noc():
    # A STEM-listed NOC clears a STEM draw below the candidate's CRS: reachable, not needs-check.
    eligible = _profile(noc_code="21220")
    res = reachable_paths(eligible, [_cat_draw("stem")], as_of=DAY)
    assert not res.needs_eligibility_check
    assert res.reachable and res.reachable[0].eligible is True

    # A non-STEM NOC is now a decided "not eligible" -> blocked, not needs-check.
    ineligible = _profile(noc_code="63201")
    res2 = reachable_paths(ineligible, [_cat_draw("stem")], as_of=DAY)
    assert not res2.needs_eligibility_check
    assert res2.blocked and res2.blocked[0].eligible is False


def test_reachable_paths_without_noc_stays_needs_check():
    no_noc = _profile(noc_code=None)
    res = reachable_paths(no_noc, [_cat_draw("healthcare")], as_of=DAY)
    assert res.needs_eligibility_check                   # honest: occupation unknown
    assert res.needs_eligibility_check[0].eligible is None
