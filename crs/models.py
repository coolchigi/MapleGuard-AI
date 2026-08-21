"""Profile model for the CRS engine.

A Profile is a pure data record. The engine is a pure function of it. No I/O here.
Language scores are Canadian Language Benchmark (CLB) levels per ability, 0-10+.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

MaritalStatus = Literal["single", "married", "common-law", "divorced", "widowed", "separated"]
EducationLevel = Literal[
    "none-or-less-than-secondary",
    "secondary",                       # high school
    "one-year-post-secondary",
    "two-year-post-secondary",
    "bachelors-or-three-year",         # 3+ year post-secondary
    "two-or-more-certificates",        # one being 3+ years
    "masters-or-professional",
    "doctoral",
]


@dataclass
class LanguageScores:
    """CLB level per ability. For a second language, same shape (NCLC maps to CLB)."""
    speaking: int = 0
    listening: int = 0
    reading: int = 0
    writing: int = 0

    def min_clb(self) -> int:
        return min(self.speaking, self.listening, self.reading, self.writing)


@dataclass
class Profile:
    education: EducationLevel
    first_language: LanguageScores
    # Supply exactly one of `age` (static) or `date_of_birth` (date-parameterized).
    age: Optional[int] = None
    date_of_birth: Optional[date] = None
    marital_status: MaritalStatus = "single"

    # Spouse is only scored when they accompany you AND are not a Canadian citizen/PR.
    spouse_accompanying: bool = False
    spouse_is_pr_or_citizen: bool = False
    spouse_education: Optional[EducationLevel] = None
    spouse_first_language: Optional[LanguageScores] = None
    spouse_canadian_work_years: int = 0

    second_language: Optional[LanguageScores] = None  # e.g. French as second language
    first_language_test_date: Optional[date] = None    # results valid 2 years (for expiry)
    canadian_work_years: int = 0
    foreign_work_years: int = 0

    has_certificate_of_qualification: bool = False    # trades
    has_provincial_nomination: bool = False
    has_sibling_in_canada: bool = False
    canadian_post_secondary_years: int = 0            # 0 = none, 1-2 = short, 3+ = long

    # French additional-points eligibility is derived, but we let the caller state
    # whether the second language is French (NCLC) for the +25/+50 additional bonus.
    second_language_is_french: bool = False

    def __post_init__(self):
        if self.age is None and self.date_of_birth is None:
            raise ValueError("Profile needs either `age` or `date_of_birth`")

    def age_at(self, as_of: Optional[date] = None) -> int:
        """Effective age. Prefers date_of_birth (as of `as_of`, default today) over static `age`."""
        if self.date_of_birth is not None:
            d = as_of or date.today()
            dob = self.date_of_birth
            return d.year - dob.year - ((d.month, d.day) < (dob.month, dob.day))
        return self.age

    def scored_with_spouse(self) -> bool:
        """You are scored as having a spouse only if they come with you and are not a PR/citizen."""
        if self.marital_status not in ("married", "common-law"):
            return False
        return self.spouse_accompanying and not self.spouse_is_pr_or_citizen
