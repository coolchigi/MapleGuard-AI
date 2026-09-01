"""Pydantic request bodies for the API.

Kept intentionally light: the profile/draw/offer payloads are passed through as dicts to
`serde`, which is the single authoritative validation path (it raises on a malformed profile
rather than defaulting). These models give FastAPI a clean OpenAPI schema and validate the
request envelope (required fields, scalar types); the deep validation still happens in `serde`,
so there is one source of truth, not two. Field docs mirror `agent/schemas.py`.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class AuditRequest(BaseModel):
    letter_text: str = Field(..., description="The employer reference letter's full text.")
    noc_code: str = Field(..., description="The claimed NOC 2021 code, e.g. '21234'.")


class DraftRequest(BaseModel):
    letter_text: str
    noc_code: str
    supporting_facts: Optional[list[str]] = Field(
        default=None, description="Facts the caller attests the drafter may rely on.")


class PositionRequest(BaseModel):
    profile: dict[str, Any] = Field(..., description="Candidate profile (validated by serde).")
    as_of: Optional[str] = Field(default=None, description="ISO 'YYYY-MM-DD' to score as of.")


class TrajectoryRequest(BaseModel):
    profile: dict[str, Any]
    start: str = Field(..., description="ISO start date 'YYYY-MM-DD'.")
    end: str = Field(..., description="ISO end date 'YYYY-MM-DD'.")


class DeadlinesRequest(BaseModel):
    profile: dict[str, Any]
    as_of: Optional[str] = None


class DashboardRequest(BaseModel):
    """The whole dashboard in one call: position categories + the time-machine trajectory."""
    profile: dict[str, Any] = Field(..., description="Candidate profile; needs date_of_birth.")
    as_of: Optional[str] = Field(default=None, description="ISO 'YYYY-MM-DD'; defaults to today.")
    horizon_years: int = Field(default=3, ge=1, le=30,
                              description="How far forward the trajectory runs from as_of.")
    last_draw_score: Optional[int] = Field(
        default=None, ge=0, le=1200,
        description="CRS cutoff of the most recent general round, for the 'points below' line. "
                    "Omit to use the server's stated constant; fetch live values from /draws.")
    last_draw_date: Optional[str] = Field(default=None, description="ISO date of that round.")


class SirsRequest(BaseModel):
    profile: dict[str, Any]
    offer: Optional[dict[str, Any]] = Field(
        default=None, description="BC job offer {hourly_wage, area, is_tech_exempt}.")


class ReachableRequest(BaseModel):
    profile: dict[str, Any]
    draws: list[dict[str, Any]] = Field(..., description="Live cited draws (from /draws).")
    as_of: Optional[str] = None
    bc_offer: Optional[dict[str, Any]] = None


class DrawsResponse(BaseModel):
    """Documentation-only shape for /draws (the endpoint returns the tool dict directly)."""
    draws: list[dict[str, Any]]
    needs_manual_check: list[dict[str, Any]]


class BriefRequest(BaseModel):
    """Assemble the consultant brief for one candidate: CRS position, cited NOC letter gaps + the
    drafted correction, and the ranked next moves with dates. Every number/citation comes from the
    deterministic core; only the cover prose is model-written (and screened for eligibility verdicts)."""
    profile: dict[str, Any] = Field(..., description="Candidate profile (validated by serde).")
    noc_code: Optional[str] = Field(default=None, description="Claimed NOC 2021 code (for the letter audit).")
    letter_text: Optional[str] = Field(default=None, description="Reference letter text to audit + correct.")
    draws: Optional[list[dict[str, Any]]] = Field(
        default=None, description="Live cited draws (from /draws) to rank the next moves against.")
    supporting_facts: Optional[list[str]] = Field(
        default=None, description="Facts the caller attests the corrector may rely on.")
    as_of: Optional[str] = Field(default=None, description="ISO 'YYYY-MM-DD' to compute as of.")


class ReferenceLetter(BaseModel):
    """An employer reference letter stored with a profile, so a NOC-type policy change can trigger
    a re-audit. PII note: the letter contains personal data and is stored unscrubbed until Bedrock
    Guardrails PII redaction is provisioned (flagged, not faked)."""
    noc_code: str = Field(..., description="The claimed NOC 2021 code, e.g. '21234'.")
    letter_text: str = Field(..., description="The reference letter's full text.")


class ProfileSaveRequest(BaseModel):
    """Save a candidate profile into the monitored set — the intake path that puts a profile in
    front of the autonomous monitor. `profile` is the same shape `/position` takes (validated by
    serde). `id` is a stable per-user id (generated if omitted); re-saving the same id updates it.
    `reference_letter` (optional) is stored so a NOC reclassification can re-audit it."""
    profile: dict[str, Any] = Field(..., description="Candidate profile (validated by serde).")
    id: Optional[str] = Field(default=None, description="Stable profile id; generated if omitted.")
    bc_offer: Optional[dict[str, Any]] = Field(
        default=None, description="Optional BC job offer {hourly_wage, area, is_tech_exempt}.")
    reference_letter: Optional[ReferenceLetter] = Field(
        default=None, description="Optional employer reference letter to store for re-audit.")
