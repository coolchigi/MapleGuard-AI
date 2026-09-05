"""Typed tool-input schemas, so the Strands ToolSpec the model sees is richly typed.

These are `TypedDict`s, chosen deliberately over Pydantic models: Strands generates the
same rich nested JSON schema from them (verified against SDK 1.53.0), while at runtime the
argument still arrives as a plain `dict`. That means `serde.profile_from_dict` and friends
keep working untouched, and there is one validation path (serde), not two. Literal-typed
fields (education, marital status, draw kind, BC area) become enums in the schema, so the
model is told the exact allowed values rather than guessing a free string.

Type-level `Required`/optional here shapes the schema only. The authoritative runtime
validation stays in `serde`, which raises on a malformed profile rather than defaulting.
"""
from __future__ import annotations

from typing import Optional

# TypedDict (and Required) come from typing_extensions, not typing: pydantic requires
# typing_extensions.TypedDict on Python < 3.12 (the AgentCore runtime is python3.11), and it works
# identically on newer Pythons, so this import is correct on every version.
from typing_extensions import Required, TypedDict

from crs.models import EducationLevel, MaritalStatus


class LanguageScoresInput(TypedDict):
    """Canadian Language Benchmark (CLB) level per ability, 0-10+."""
    speaking: int
    listening: int
    reading: int
    writing: int


class ProfileInput(TypedDict, total=False):
    """A candidate profile. `education` and `first_language` are required; supply exactly
    one of `age` or `date_of_birth` (a trajectory/deadlines needs `date_of_birth`)."""
    education: Required[EducationLevel]
    first_language: Required[LanguageScoresInput]
    age: int
    date_of_birth: str                       # ISO 'YYYY-MM-DD'
    marital_status: MaritalStatus
    spouse_accompanying: bool
    spouse_is_pr_or_citizen: bool
    spouse_education: EducationLevel
    spouse_first_language: LanguageScoresInput
    spouse_canadian_work_years: int
    second_language: LanguageScoresInput
    second_language_is_french: bool
    first_language_test_date: str            # ISO 'YYYY-MM-DD'; results valid 2 years
    canadian_work_years: int
    foreign_work_years: int
    has_certificate_of_qualification: bool
    has_provincial_nomination: bool
    has_sibling_in_canada: bool
    canadian_post_secondary_years: int       # 0 none, 1-2 short, 3+ long


BCArea = str  # one of: metro_vancouver | other_lower_mainland | rest_of_bc | northern_bc


class BCJobOfferInput(TypedDict, total=False):
    """A BC job offer, used to score the SIRS economic factors and the registration flag."""
    hourly_wage: Required[float]
    area: BCArea
    is_tech_exempt: bool                     # a job-offer-exempt Tech occupation


class DrawInput(TypedDict, total=False):
    """One live draw to measure a profile against. `source` is a required citation (the
    trust posture forbids an uncited cutoff). `cutoff` is CRS for general/category draws and
    SIRS for pnp_bc."""
    kind: Required[str]                      # 'general' | 'category' | 'pnp_bc'
    name: Required[str]
    cutoff: Required[int]
    date: Required[str]                      # ISO 'YYYY-MM-DD'
    source: Required[str]                    # citation URL / doc id
    category: str                            # for kind=='category': 'french' | occupation slug
    eligible_override: bool                  # caller-asserted eligibility (occupation categories)
    round_number: str                        # official round id (from ingest_draws)
    invitations: int                         # invitations issued this round (from ingest_draws)
    provenance: dict                         # full ingest citation; echoed onto the result
