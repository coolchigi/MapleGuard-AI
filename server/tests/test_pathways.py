"""Tests for the eligibility / pathways service (paths/pathways.py).

Pure and offline. The service composes the CRS engine, the cited 2026 category rules, and the move
catalog into one "what do I qualify for" map. The cases below pin the behaviour that makes it
genuinely useful: it surfaces a pathway a candidate would not know to look for (French), it is honest
when it cannot decide (no NOC code), and a positive verdict is the narrow official test, never a PR
guarantee.

Run:  cd server && PYTHONPATH=. python3 -m pytest -q tests/test_pathways.py
"""
from datetime import date

from crs import LanguageScores, Profile
from paths import Draw, eligible_pathways

AS_OF = date(2026, 9, 7)


def _civil_engineer_with_french() -> Profile:
    # NOC 21300 (Civil Engineers) is on the 2026 STEM list; French NCLC 8 clears the French rule.
    return Profile(education="masters-or-professional", first_language=LanguageScores(9, 9, 9, 9),
                   date_of_birth=date(1994, 7, 1), canadian_work_years=2, noc_code="21300",
                   second_language=LanguageScores(8, 8, 8, 8), second_language_is_french=True)


def test_map_covers_general_ten_categories_and_bc_pnp():
    m = eligible_pathways(_civil_engineer_with_french(), as_of=AS_OF)
    slugs = [p.slug for p in m.pathways]
    assert slugs[0] == "general"
    assert {"french", "stem", "healthcare", "trades", "physicians"} <= set(slugs)
    assert "bc-pnp" in slugs


def test_surfaces_french_the_candidate_would_not_know_to_look_for():
    # The motivating case: a strong profile is in-category for French. The verdict is cited.
    m = eligible_pathways(_civil_engineer_with_french(), as_of=AS_OF)
    french = next(p for p in m.pathways if p.slug == "french")
    assert french.eligible is True
    assert "NCLC" in french.eligibility_reason
    assert "canada.ca" in french.source_url
    assert "french" in m.qualifying() and "stem" in m.qualifying()


def test_no_french_result_is_a_determinate_not_eligible():
    p = Profile(education="bachelors-or-three-year", first_language=LanguageScores(9, 9, 9, 9),
                date_of_birth=date(1996, 7, 1), canadian_work_years=1, noc_code="21300")
    m = eligible_pathways(p, as_of=AS_OF)
    french = next(pw for pw in m.pathways if pw.slug == "french")
    assert french.eligible is False  # no French second language -> below NCLC 7, not "unknown"
    assert "french" not in m.qualifying()


def test_missing_noc_code_is_cannot_decide_not_a_guess():
    p = Profile(education="bachelors-or-three-year", first_language=LanguageScores(8, 8, 8, 8),
                date_of_birth=date(1996, 7, 1), canadian_work_years=1)  # no noc_code
    m = eligible_pathways(p, as_of=AS_OF)
    stem = next(pw for pw in m.pathways if pw.slug == "stem")
    assert stem.eligible is None  # cannot decide an occupation category without a NOC code
    assert stem.slug not in m.qualifying()


def test_occupation_not_in_list_is_not_eligible():
    # NOC 21231 (software engineers) is NOT on the 2026 STEM list.
    p = Profile(education="bachelors-or-three-year", first_language=LanguageScores(9, 9, 9, 9),
                date_of_birth=date(1996, 7, 1), canadian_work_years=1, noc_code="21231")
    m = eligible_pathways(p, as_of=AS_OF)
    stem = next(pw for pw in m.pathways if pw.slug == "stem")
    assert stem.eligible is False
    assert "not in" in stem.eligibility_reason


def test_additional_requirements_travel_with_the_verdict():
    # A positive NOC-list match is "in-category", not "eligible for PR": the official conditions
    # this layer does not verify must travel with it.
    m = eligible_pathways(_civil_engineer_with_french(), as_of=AS_OF)
    stem = next(p for p in m.pathways if p.slug == "stem")
    assert stem.eligible is True and stem.additional_requirements


def test_standing_against_a_draw_shows_gap_and_moves_when_below_cutoff():
    # A profile eligible for a category but below its cutoff gets a gap and cited closing moves.
    p = Profile(education="bachelors-or-three-year", first_language=LanguageScores(7, 7, 7, 7),
                date_of_birth=date(1990, 7, 1), canadian_work_years=1, noc_code="21300")
    draws = [Draw(kind="category", name="STEM occupations", cutoff=520, date=date(2026, 8, 1),
                  source="https://www.canada.ca/stem", category="stem")]
    m = eligible_pathways(p, draws=draws, as_of=AS_OF)
    stem = next(pw for pw in m.pathways if pw.slug == "stem")
    assert stem.eligible is True
    assert stem.latest_cutoff == 520
    if not stem.clears:
        assert stem.gap > 0
        assert all(mv["closes_gap"] for mv in stem.closing_moves)


def test_clears_when_score_meets_cutoff_and_no_moves_suggested():
    p = _civil_engineer_with_french()  # CRS ~518
    draws = [Draw(kind="category", name="French", cutoff=379, date=date(2026, 9, 2),
                  source="https://www.canada.ca/fr", category="french")]
    m = eligible_pathways(p, draws=draws, as_of=AS_OF)
    french = next(pw for pw in m.pathways if pw.slug == "french")
    assert french.clears is True and french.gap == 0 and french.closing_moves == ()


def test_to_dict_is_json_safe_and_lists_qualifying():
    m = eligible_pathways(_civil_engineer_with_french(), as_of=AS_OF)
    d = m.to_dict()
    assert isinstance(d["crs_total"], int)
    assert "french" in d["qualifying"]
    assert all({"slug", "eligible", "source_url"} <= set(p) for p in d["pathways"])
