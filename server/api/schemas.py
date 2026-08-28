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
