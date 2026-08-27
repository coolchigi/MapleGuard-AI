"""Express Entry 2026 category-based selection rules, and a deterministic eligibility check.

This is the piece that turns occupation-category eligibility from "needs NOC check" into a
real, cited verdict. Given a candidate's NOC code (or French test result), it answers: are
you eligible for category X? It never touches cutoff numbers (those live in ingest.rounds)
and never asserts overall PR eligibility (that is IRCC's call). It decides one narrow,
official thing: does your occupation appear on this category's published NOC list, or do you
meet the French-language rule.

Source (verified 2026-08-26 against the live page, whose own "Page details" date is
2026-06-22): the official "Express Entry: Category-based selection" page.
Each category's NOC list is transcribed from that page's tables; the French category is a
language rule (NCLC 7 in all four abilities), not a NOC list.

Honesty boundary: each occupation category also carries official conditions this module does
NOT enforce (e.g. at least 12 months of qualifying work experience within the past 3 years,
Canadian experience for the "with Canadian work experience" categories, an arranged-offer
for skilled military). Those are recorded in ``additional_requirements`` and surfaced in the
reason, so a positive NOC-list match is reported as "your occupation is in-category" rather
than "you are eligible" -- the full determination stays with IRCC.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, FrozenSet, Optional

CATEGORY_SOURCE_URL = ("https://www.canada.ca/en/immigration-refugees-citizenship/services/"
                       "immigrate-canada/express-entry/rounds-invitations/"
                       "category-based-selection.html")
CATEGORY_SOURCE_DATE = date(2026, 6, 22)   # the page's own "Page details" date
CATEGORY_FETCHED = date(2026, 8, 26)       # when we read and transcribed it
FRENCH_MIN_NCLC = 7

# --- Verified data (transcribed from the official page; see module docstring) --------
# NOC 2021 five-digit codes per 2026 category. French carries no list (it is a language
# rule). Agriculture and agri-food is intentionally absent: it is not a 2026 category.
NOC_CODES_BY_CATEGORY: Dict[str, FrozenSet[str]] = {
    "healthcare": frozenset({"31100", "31101", "31102", "31103", "31110", "31111", "31112", "31120", "31121", "31200", "31201", "31202", "31203", "31209", "31300", "31301", "31302", "31303", "32101", "32102", "32103", "32104", "32109", "32111", "32120", "32121", "32122", "32123", "32124", "32129", "32201", "33101", "33102", "33103", "41300", "41301", "42201"}),
    "stem": frozenset({"20011", "21220", "21300", "21301", "21310", "21321", "21331", "22300", "22301", "22310", "63100"}),
    "trades": frozenset({"22303", "63201", "70010", "70011", "72100", "72102", "72106", "72200", "72201", "72300", "72302", "72310", "72311", "72320", "72400", "72401", "72402", "72422", "72501", "72999", "73100", "73110", "73112", "73113", "82021"}),
    "education": frozenset({"41220", "41221", "42202", "42203", "43100"}),
    "transport": frozenset({"22313", "72404", "72410", "72600"}),
    "physicians": frozenset({"31100", "31101", "31102"}),
    "senior-managers": frozenset({"00012", "00013", "00014", "00015"}),
    "researchers": frozenset({"41200", "41201"}),
    "skilled-military": frozenset({"40042", "42102", "43204"}),
}

# Official titles for cited, human-readable reasons.
CATEGORY_TITLES: Dict[str, str] = {
    "french": "French-language proficiency",
    "healthcare": "Healthcare and social services occupations",
    "stem": "Science, Technology, Engineering and Math (STEM) occupations",
    "trades": "Trade occupations",
    "education": "Education occupations",
    "transport": "Transport occupations",
    "physicians": "Physicians with Canadian work experience",
    "senior-managers": "Senior managers with Canadian work experience",
    "researchers": "Researchers with Canadian work experience",
    "skilled-military": "Skilled military recruits",
}

# Official conditions beyond the NOC list / language rule that this module does NOT verify.
_EXPERIENCE_NOTE = ("also requires >=12 months of full-time (or equal part-time) work "
                    "experience in a single listed occupation within the past 3 years")
_CANADIAN_EXPERIENCE_NOTE = ("also requires >=12 months of Canadian work experience in a "
                             "listed occupation within the past 3 years")
ADDITIONAL_REQUIREMENTS: Dict[str, str] = {
    "french": "French test results (TEF/TCF) valid at time of invitation",
    "healthcare": _EXPERIENCE_NOTE,
    "stem": _EXPERIENCE_NOTE,
    "trades": _EXPERIENCE_NOTE,
    "education": _EXPERIENCE_NOTE,
    "transport": _EXPERIENCE_NOTE,
    "physicians": _CANADIAN_EXPERIENCE_NOTE,
    "senior-managers": _CANADIAN_EXPERIENCE_NOTE,
    "researchers": _CANADIAN_EXPERIENCE_NOTE,
    "skilled-military": ("also requires being a serving foreign military member (>=10 years) "
                         "with an arranged-employment offer from the Canadian Armed Forces"),
}

CANONICAL_SLUGS = tuple(CATEGORY_TITLES.keys())


@dataclass(frozen=True)
class CategoryRule:
    """One 2026 category and the deterministic rule that governs it."""
    slug: str
    title: str
    rule_kind: str                     # "language" | "noc_list"
    noc_codes: FrozenSet[str]          # empty for the language rule
    language_min_nclc: Optional[int]   # 7 for French; None otherwise
    additional_requirements: str       # official conditions NOT checked here
    source_url: str = CATEGORY_SOURCE_URL
    source_date: date = CATEGORY_SOURCE_DATE
    fetched: date = CATEGORY_FETCHED
    verified: bool = True              # transcribed and completeness-checked against source


def _build_rules() -> Dict[str, CategoryRule]:
    rules: Dict[str, CategoryRule] = {}
    for slug, title in CATEGORY_TITLES.items():
        is_french = slug == "french"
        rules[slug] = CategoryRule(
            slug=slug, title=title,
            rule_kind="language" if is_french else "noc_list",
            noc_codes=NOC_CODES_BY_CATEGORY.get(slug, frozenset()),
            language_min_nclc=FRENCH_MIN_NCLC if is_french else None,
            additional_requirements=ADDITIONAL_REQUIREMENTS[slug],
        )
    return rules


CATEGORY_RULES: Dict[str, CategoryRule] = _build_rules()


@dataclass(frozen=True)
class CategoryEligibility:
    """A deterministic, cited verdict for one category.

    ``eligible`` is None only when the needed input is missing (no NOC code for an occupation
    category, or no French result for the French category) -- honest "cannot decide", never a
    guess. A True verdict means the narrow official test is met (occupation is in-category, or
    NCLC 7 reached); it is not a claim of overall PR eligibility.
    """
    slug: str
    eligible: Optional[bool]
    reason: str
    source_url: str
    source_date: date
    additional_requirements: str = ""


# --- Slug resolution: one canonical vocabulary both ingest and paths map through ------
def resolve_category(text: Optional[str]) -> Optional[str]:
    """Map any official draw name, ingest slug, or category title to a canonical slug.

    This is the shared vocabulary that lets ingest's display slugs (e.g. "stem-occupations",
    "healthcare-and-social-services-occupations") line up with the rule keys here. Returns
    None for anything that is not one of the ten 2026 categories (e.g. provincial-nominee or
    program-specific draws), which is honest: those are not category-based-selection rules.
    """
    if not text:
        return None
    n = " ".join(str(text).replace("-", " ").split()).lower()
    if "french" in n:
        return "french"
    if "healthcare" in n or "health and social" in n or "health care" in n:
        return "healthcare"
    if "stem" in n or "science technology engineering" in n:
        return "stem"
    if "trade" in n:
        return "trades"
    if "education" in n:
        return "education"
    if "transport" in n:
        return "transport"
    if "physician" in n:
        return "physicians"
    if "senior manager" in n:
        return "senior-managers"
    if "research" in n:
        return "researchers"
    if "military" in n:
        return "skilled-military"
    return None


# --- The deterministic eligibility check --------------------------------------------
def category_eligibility(slug: str, *, noc_code: Optional[str] = None,
                         french_nclc: Optional[int] = None) -> CategoryEligibility:
    """Decide eligibility for one category from official inputs only.

    - occupation categories: ``noc_code`` in the category's published NOC list.
    - French category: ``french_nclc`` (min across the four abilities) >= 7.
    Missing input -> eligible=None ("cannot decide"), never guessed.
    """
    rule = CATEGORY_RULES.get(slug)
    if rule is None:
        return CategoryEligibility(slug, None, f"{slug!r} is not a 2026 category",
                                   CATEGORY_SOURCE_URL, CATEGORY_SOURCE_DATE)

    if rule.rule_kind == "language":
        if french_nclc is None:
            return CategoryEligibility(
                rule.slug, None, "provide French test results to check the French category",
                rule.source_url, rule.source_date, rule.additional_requirements)
        ok = french_nclc >= FRENCH_MIN_NCLC
        reason = (f"French NCLC {french_nclc} across abilities "
                  f"{'meets' if ok else 'is below'} the NCLC {FRENCH_MIN_NCLC} requirement")
        return CategoryEligibility(rule.slug, ok, reason, rule.source_url, rule.source_date,
                                   rule.additional_requirements)

    # occupation categories
    if not noc_code:
        return CategoryEligibility(
            rule.slug, None, "provide the candidate's NOC code to check this category",
            rule.source_url, rule.source_date, rule.additional_requirements)
    code = str(noc_code).strip()
    in_list = code in rule.noc_codes
    if in_list:
        reason = (f"NOC {code} ({CATEGORY_NOC_TITLES.get(code, 'listed occupation')}) is in "
                  f"the {rule.title} category")
    else:
        reason = f"NOC {code} is not in the {rule.title} category's published list"
    return CategoryEligibility(rule.slug, in_list, reason, rule.source_url, rule.source_date,
                               rule.additional_requirements)


def categories_for_noc(noc_code: str) -> list[str]:
    """Every occupation category whose published NOC list contains ``noc_code``."""
    code = str(noc_code).strip()
    return [slug for slug, rule in CATEGORY_RULES.items() if code in rule.noc_codes]


# Titles per NOC code, for cited reasons.
CATEGORY_NOC_TITLES: Dict[str, str] = {
    "00012": "Senior managers - financial, communications and other business services",
    "00013": "Senior managers - health, education, social and community services and membership organizations",
    "00014": "Senior managers - trade, broadcasting and other services",
    "00015": "Senior managers - construction, transportation, production and utilities",
    "20011": "Architecture and science managers",
    "21220": "Cybersecurity specialists",
    "21300": "Civil Engineers",
    "21301": "Mechanical Engineers",
    "21310": "Electrical and electronics engineers",
    "21321": "Industrial and manufacturing engineers",
    "21331": "Geological Engineers",
    "22300": "Civil engineering technologists and technicians",
    "22301": "Mechanical Engineering Technologists and Technicians",
    "22303": "Construction estimators",
    "22310": "Electrical and electronics engineering technologists and technicians",
    "22313": "Aircraft instrument, electrical and avionics mechanics, technicians and inspectors",
    "31100": "Specialists in clinical and laboratory medicine",
    "31101": "Specialists in surgery",
    "31102": "General practitioners and family physicians",
    "31103": "Veterinarians",
    "31110": "Dentists",
    "31111": "Optometrists",
    "31112": "Audiologists and speech-language pathologists",
    "31120": "Pharmacists",
    "31121": "Dietitians and nutritionists",
    "31200": "Psychologists",
    "31201": "Chiropractors",
    "31202": "Physiotherapists",
    "31203": "Occupational therapists",
    "31209": "Other professional occupations in health diagnosing and treating",
    "31300": "Nursing coordinators and supervisors",
    "31301": "Registered nurses and registered psychiatric nurses",
    "31302": "Nurse practitioners",
    "31303": "Physician assistants, midwives and allied health professionals",
    "32101": "Licensed practical nurses",
    "32102": "Paramedical occupations",
    "32103": "Respiratory therapists, clinical perfusionists and cardiopulmonary technologists",
    "32104": "Animal health technologists and veterinary technicians",
    "32109": "Other technical occupations in therapy and assessment",
    "32111": "Dental hygienists and dental therapists",
    "32120": "Medical laboratory technologists",
    "32121": "Medical radiation technologists",
    "32122": "Medical sonographers",
    "32123": "Cardiology technologists and electrophysiological diagnostic technologists",
    "32124": "Pharmacy technicians",
    "32129": "Other medical technologists and technicians",
    "32201": "Massage therapists",
    "33101": "Medical laboratory assistants and related technical occupations",
    "33102": "Nurse aides, orderlies and patient service associates",
    "33103": "Pharmacy technical assistants and pharmacy assistants",
    "40042": "Commissioned officers of the Canadian Armed Forces",
    "41200": "University professors and lecturers",
    "41201": "Post-secondary teaching and research assistants",
    "41220": "Secondary school teachers",
    "41221": "Elementary school and kindergarten teachers",
    "41300": "Social workers",
    "41301": "Therapists in counselling and related specialized therapies",
    "42102": "Specialized members of the Canadian Armed Forces",
    "42201": "Social and community service workers",
    "42202": "Early childhood educators and assistants",
    "42203": "Instructors of persons with disabilities",
    "43100": "Elementary and secondary school teacher assistants",
    "43204": "Operations Members of the Canadian Armed Forces",
    "63100": "Insurance agents and brokers",
    "63201": "Butchers - retail and wholesale",
    "70010": "Construction managers",
    "70011": "Home building and renovation managers",
    "72100": "Machinists and machining and tooling inspectors",
    "72102": "Sheet metal workers",
    "72106": "Welders and related machine operators",
    "72200": "Electricians (except industrial and power system)",
    "72201": "Industrial electricians",
    "72300": "Plumbers",
    "72302": "Gas fitters",
    "72310": "Carpenters",
    "72311": "Cabinetmakers",
    "72320": "Bricklayers",
    "72400": "Construction millwrights and industrial mechanics",
    "72401": "Heavy-duty equipment mechanics",
    "72402": "Heating, refrigeration and air conditioning mechanics",
    "72404": "Aircraft mechanics and aircraft inspectors",
    "72410": "Automotive service technicians, truck and bus mechanics, and mechanical repairers",
    "72422": "Electrical mechanics",
    "72501": "Water well drillers",
    "72600": "Air pilots, flight engineers and flying instructors",
    "72999": "Other technical trades and related occupations",
    "73100": "Concrete finishers",
    "73110": "Roofers and shinglers",
    "73112": "Painters and decorators (except interior decorators)",
    "73113": "Floor covering installers",
    "82021": "Contractors and supervisors, oil and gas drilling and services",
}
