"""CRS engine — the full deterministic Comprehensive Ranking System calculator.

`crs(profile) -> Score` with a subtotal per block (core, spouse, skill_transfer,
additional) and a line-item breakdown. Pure function, no I/O, no model. The LLM
never computes a number; this does. Validated against IRCC's official tool via
the golden oracle (crs/cases/golden.json).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import tables as T
from .models import LanguageScores, Profile


@dataclass(frozen=True)
class LineItem:
    factor: str
    points: int


@dataclass(frozen=True)
class Score:
    core: int
    spouse: int
    skill_transfer: int
    additional: int
    breakdown: list[LineItem]

    @property
    def total(self) -> int:
        return self.core + self.spouse + self.skill_transfer + self.additional


# --------------------------------------------------------------------- helpers
def _clb_bucket(clb: int) -> int | None:
    if clb is None or clb < 4:
        return None
    return 10 if clb >= 10 else clb


def _lang_points(scores: LanguageScores, table: dict) -> int:
    total = 0
    for clb in (scores.speaking, scores.listening, scores.reading, scores.writing):
        b = _clb_bucket(clb)
        if b is not None and b in table:
            total += table[b]
    return total


def _clamp_years(y: int) -> int:
    return min(max(y, 0), 5)


def _edu_transfer_tier(education: str) -> str | None:
    """post-secondary credential tier for skill transfer: None / 'one' / 'two_plus'."""
    if education in ("none-or-less-than-secondary", "secondary"):
        return None
    if education == "two-or-more-certificates":
        return "two_plus"
    return "one"


def _foreign_tier(years: int) -> str | None:
    if years <= 0:
        return None
    return "1_2" if years <= 2 else "3_plus"


def _max_clb(scores: LanguageScores) -> int:
    return min(scores.speaking, scores.listening, scores.reading, scores.writing)


# ------------------------------------------------------------------- the blocks
def _core(profile: Profile, spouse: bool, age: int) -> list[LineItem]:
    age_t = T.AGE_SPOUSE if spouse else T.AGE_SINGLE
    edu_t = T.EDUCATION_SPOUSE if spouse else T.EDUCATION_SINGLE
    first_t = T.FIRST_LANG_SPOUSE if spouse else T.FIRST_LANG_SINGLE
    work_t = T.CANADIAN_WORK_SPOUSE if spouse else T.CANADIAN_WORK_SINGLE
    second_cap = T.SECOND_LANG_CAP_SPOUSE if spouse else T.SECOND_LANG_CAP_SINGLE

    items = [
        LineItem("age", age_t.values.get(age, 0)),
        LineItem("education", edu_t.values[profile.education]),
        LineItem("first_language", _lang_points(profile.first_language, first_t.values)),
        LineItem(
            "second_language",
            min(_lang_points(profile.second_language, T.SECOND_LANG.values), second_cap)
            if profile.second_language else 0,
        ),
        LineItem("canadian_work", work_t.values[_clamp_years(profile.canadian_work_years)]),
    ]
    return items


def _spouse(profile: Profile) -> list[LineItem]:
    if not profile.scored_with_spouse():
        return []
    edu = profile.spouse_education or "none-or-less-than-secondary"
    lang = profile.spouse_first_language
    return [
        LineItem("spouse_education", T.SPOUSE_EDUCATION.values[edu]),
        LineItem(
            "spouse_language",
            _lang_points(lang, T.SPOUSE_FIRST_LANG.values) if lang else 0,
        ),
        LineItem(
            "spouse_canadian_work",
            T.SPOUSE_CANADIAN_WORK.values[_clamp_years(profile.spouse_canadian_work_years)],
        ),
    ]


def _skill_transfer(profile: Profile) -> list[LineItem]:
    clb = _max_clb(profile.first_language)
    b = _clb_bucket(clb)
    edu_tier = _edu_transfer_tier(profile.education)
    cdn = _clamp_years(profile.canadian_work_years)
    foreign_tier = _foreign_tier(profile.foreign_work_years)

    # Education group (max 50): edu x language + edu x Canadian work.
    edu_lang = T.EDU_LANG.values[edu_tier].get(b, 0) if (edu_tier and b) else 0
    edu_work = T.EDU_WORK.values[edu_tier].get(cdn, 0) if edu_tier else 0
    edu_group = min(50, edu_lang + edu_work)

    # Foreign-work group (max 50): foreign x language + foreign x Canadian work.
    for_lang = T.FOREIGN_LANG.values[foreign_tier].get(b, 0) if (foreign_tier and b) else 0
    for_work = T.FOREIGN_WORK.values[foreign_tier].get(cdn, 0) if foreign_tier else 0
    foreign_group = min(50, for_lang + for_work)

    # Certificate of qualification group (max 50): cert x language.
    cert_group = 0
    if profile.has_certificate_of_qualification and b is not None:
        cert_group = min(50, T.CERT_LANG.values.get(b, 0))

    return [
        LineItem("transfer_education", edu_group),
        LineItem("transfer_foreign_work", foreign_group),
        LineItem("transfer_certificate", cert_group),
    ]


def _additional(profile: Profile) -> list[LineItem]:
    v = T.MAX_ADDITIONAL.values
    items: list[LineItem] = []
    if profile.has_provincial_nomination:
        items.append(LineItem("provincial_nomination", v["provincial_nomination"]))
    if profile.has_sibling_in_canada:
        items.append(LineItem("sibling_in_canada", v["sibling_in_canada"]))

    y = profile.canadian_post_secondary_years
    if y >= 3:
        items.append(LineItem("canadian_study", v["canadian_study_3_plus_years"]))
    elif y >= 1:
        items.append(LineItem("canadian_study", v["canadian_study_1_2_years"]))

    if profile.second_language_is_french and profile.second_language:
        french_ok = _max_clb(profile.second_language) >= 7  # NCLC 7 across abilities
        english = _max_clb(profile.first_language)
        if french_ok:
            if english >= 5:
                items.append(LineItem("french_bonus", v["french_nclc7_english_clb5_plus"]))
            else:
                items.append(LineItem("french_bonus", v["french_nclc7_english_clb4_or_less"]))
    # arranged_employment is pinned 0 and has no granting field — never added.
    return items


def crs(profile: Profile, as_of: date | None = None) -> Score:
    spouse_scored = profile.scored_with_spouse()
    age = profile.age_at(as_of)

    core_items = _core(profile, spouse_scored, age)
    spouse_items = _spouse(profile)
    transfer_items = _skill_transfer(profile)
    additional_items = _additional(profile)

    core_cap = T.CORE_MAX_SPOUSE if spouse_scored else T.CORE_MAX_SINGLE
    core = min(core_cap, sum(i.points for i in core_items))
    spouse = min(T.SPOUSE_MAX, sum(i.points for i in spouse_items))
    skill_transfer = min(T.SKILL_TRANSFER_MAX, sum(i.points for i in transfer_items))
    additional = min(T.ADDITIONAL_MAX, sum(i.points for i in additional_items))

    return Score(
        core=core,
        spouse=spouse,
        skill_transfer=skill_transfer,
        additional=additional,
        breakdown=core_items + spouse_items + transfer_items + additional_items,
    )
