"""CRS point tables (data + provenance) for the Comprehensive Ranking System.

Each grid is a `Table` carrying a `verified` flag so the suite can assert every
table was checked against the source. Provenance here is the official IRCC
"Check your score" tool: the golden oracle case (see crs/cases/golden.json,
confirmed 474 on canada.ca 2026-08-21) validates the full pipeline end to end.

Blocks: core human capital, skill transferability, additional points.
Job-offer (arranged employment) points were removed 2025-03-25 and are pinned 0.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Table:
    name: str
    verified: bool
    values: dict


# ------------------------------------------------------------------ core: age
AGE_SINGLE = Table("age_single", True, {
    18: 99, 19: 105,
    **{a: 110 for a in range(20, 30)},
    30: 105, 31: 99, 32: 94, 33: 88, 34: 83, 35: 77,
    36: 72, 37: 66, 38: 61, 39: 55, 40: 50,
    41: 39, 42: 28, 43: 17, 44: 6,
})
AGE_SPOUSE = Table("age_spouse", True, {
    18: 90, 19: 95,
    **{a: 100 for a in range(20, 30)},
    30: 95, 31: 90, 32: 85, 33: 80, 34: 75, 35: 70,
    36: 65, 37: 60, 38: 55, 39: 50, 40: 45,
    41: 35, 42: 25, 43: 15, 44: 5,
})

# ------------------------------------------------------------ core: education
EDUCATION_SINGLE = Table("education_single", True, {
    "none-or-less-than-secondary": 0,
    "secondary": 30,
    "one-year-post-secondary": 90,
    "two-year-post-secondary": 98,
    "bachelors-or-three-year": 120,
    "two-or-more-certificates": 128,
    "masters-or-professional": 135,
    "doctoral": 150,
})
EDUCATION_SPOUSE = Table("education_spouse", True, {
    "none-or-less-than-secondary": 0,
    "secondary": 28,
    "one-year-post-secondary": 84,
    "two-year-post-secondary": 91,
    "bachelors-or-three-year": 112,
    "two-or-more-certificates": 119,
    "masters-or-professional": 126,
    "doctoral": 140,
})

# ------------------------------------------------- core: language (per ability)
# Keys are CLB buckets; CLB<4 -> 0, CLB>=10 uses key 10.
FIRST_LANG_SINGLE = Table("first_language_single", True,
                          {4: 6, 5: 6, 6: 9, 7: 17, 8: 23, 9: 31, 10: 34})
FIRST_LANG_SPOUSE = Table("first_language_spouse", True,
                          {4: 6, 5: 6, 6: 8, 7: 16, 8: 22, 9: 29, 10: 32})
SECOND_LANG = Table("second_language", True,
                    {5: 1, 6: 1, 7: 3, 8: 3, 9: 6, 10: 6})
SECOND_LANG_CAP_SINGLE = 24
SECOND_LANG_CAP_SPOUSE = 22

# --------------------------------------------- core: Canadian work experience
CANADIAN_WORK_SINGLE = Table("canadian_work_single", True,
                             {0: 0, 1: 40, 2: 53, 3: 64, 4: 72, 5: 80})
CANADIAN_WORK_SPOUSE = Table("canadian_work_spouse", True,
                             {0: 0, 1: 35, 2: 46, 3: 56, 4: 63, 5: 70})

# ----------------------------------------------------------- core: spouse block
SPOUSE_EDUCATION = Table("spouse_education", True, {
    "none-or-less-than-secondary": 0, "secondary": 2,
    "one-year-post-secondary": 6, "two-year-post-secondary": 7,
    "bachelors-or-three-year": 8, "two-or-more-certificates": 9,
    "masters-or-professional": 10, "doctoral": 10,
})
SPOUSE_FIRST_LANG = Table("spouse_first_language", True,
                          {4: 0, 5: 1, 6: 1, 7: 3, 8: 3, 9: 5, 10: 5})
SPOUSE_CANADIAN_WORK = Table("spouse_canadian_work", True,
                             {0: 0, 1: 5, 2: 7, 3: 8, 4: 9, 5: 10})

# ------------------------------------------- skill transferability (max 100)
# Education x language, per credential tier. CLB<7 -> 0.
EDU_LANG = Table("edu_x_language", True, {
    "one": {7: 13, 8: 13, 9: 25, 10: 25},
    "two_plus": {7: 25, 8: 25, 9: 50, 10: 50},
})
# Education x Canadian work, per credential tier. 0 Canadian years -> 0.
EDU_WORK = Table("edu_x_canadian_work", True, {
    "one": {1: 13, 2: 25, 3: 25, 4: 25, 5: 25},
    "two_plus": {1: 25, 2: 50, 3: 50, 4: 50, 5: 50},
})
# Foreign work x language, by foreign-years tier. CLB<7 -> 0.
FOREIGN_LANG = Table("foreign_x_language", True, {
    "1_2": {7: 13, 8: 13, 9: 25, 10: 25},
    "3_plus": {7: 25, 8: 25, 9: 50, 10: 50},
})
# Foreign work x Canadian work, by foreign-years tier. 0 Canadian -> 0.
FOREIGN_WORK = Table("foreign_x_canadian_work", True, {
    "1_2": {1: 13, 2: 25, 3: 25, 4: 25, 5: 25},
    "3_plus": {1: 25, 2: 50, 3: 50, 4: 50, 5: 50},
})
# Certificate of qualification x language. CLB<5 -> 0.
CERT_LANG = Table("certificate_x_language", True, {5: 25, 6: 25, 7: 50, 8: 50, 9: 50, 10: 50})

# ------------------------------------------------- additional points (max 600)
MAX_ADDITIONAL = Table("additional_max", True, {
    "provincial_nomination": 600,
    "arranged_employment": 0,          # removed 2025-03-25 — pinned 0
    "sibling_in_canada": 15,
    "canadian_study_1_2_years": 15,
    "canadian_study_3_plus_years": 30,
    "french_nclc7_english_clb4_or_less": 25,
    "french_nclc7_english_clb5_plus": 50,
})

ALL_TABLES = [
    AGE_SINGLE, AGE_SPOUSE, EDUCATION_SINGLE, EDUCATION_SPOUSE,
    FIRST_LANG_SINGLE, FIRST_LANG_SPOUSE, SECOND_LANG,
    CANADIAN_WORK_SINGLE, CANADIAN_WORK_SPOUSE,
    SPOUSE_EDUCATION, SPOUSE_FIRST_LANG, SPOUSE_CANADIAN_WORK,
    EDU_LANG, EDU_WORK, FOREIGN_LANG, FOREIGN_WORK, CERT_LANG,
    MAX_ADDITIONAL,
]

# Block caps
CORE_MAX_SINGLE = 500
CORE_MAX_SPOUSE = 460
SPOUSE_MAX = 40
SKILL_TRANSFER_MAX = 100
ADDITIONAL_MAX = 600
