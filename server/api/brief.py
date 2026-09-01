"""The consultant brief: one structured document a candidate can hand to their immigration
consultant, assembled from the deterministic core.

Determinism below the model, unchanged: every NUMBER and every CITATION comes from the core tools
(compute_crs, crs_deadlines, reachable_paths, audit_reference_letter, draft_corrected_letter) — the
same tools the agent and the API already use. The model's only job is the cover PROSE, and that
prose is screened by the never-assert-eligibility gate before it is included. The brief never
asserts eligibility and never submits.

The brief is assembled by `assemble_brief`; the API exposes it at POST /brief.
"""
from __future__ import annotations

from typing import Any, Optional

from agent.gates import never_assert_eligibility
from agent.tools import (audit_reference_letter, compute_crs, crs_deadlines,
                         draft_corrected_letter, reachable_paths)

DISCLAIMER = (
    "MapleGuard computes every number from the published government grids and cites every source. "
    "It does not assert eligibility and does not submit any application. An officer decides "
    "eligibility; you and your consultant decide what to file."
)

# Deterministic profile fields echoed verbatim into the summary (no computation, no inference).
_SUMMARY_FIELDS = (
    "education", "first_language", "second_language", "second_language_is_french",
    "date_of_birth", "age", "marital_status", "canadian_work_years", "foreign_work_years",
    "has_provincial_nomination", "has_certificate_of_qualification",
)


def _profile_summary(profile: dict, crs: dict) -> dict:
    """A plain echo of the candidate's stated facts plus the core's CRS total. No number here is
    computed by this function; the total is taken straight from `compute_crs`."""
    summary = {k: profile[k] for k in _SUMMARY_FIELDS if k in profile}
    summary["crs_total"] = crs.get("total")
    return summary


def _next_moves(reachability: Optional[dict]) -> list[dict]:
    """Ranked next moves WITH dates, taken straight from reachable_paths: each reachable / within-
    reach draw carries its date, cutoff, your gap, and the engine's ranked closing moves."""
    if not reachability:
        return []
    moves: list[dict] = []
    for bucket in ("reachable", "within_reach"):
        for p in reachability.get(bucket, []):
            draw = p.get("draw", {})
            moves.append({
                "draw": draw.get("name"), "date": draw.get("date"), "kind": draw.get("kind"),
                "cutoff": p.get("cutoff"), "your_score": p.get("your_score"),
                "clears": p.get("clears"), "gap": p.get("gap"),
                "closing_moves": p.get("closing_moves", []),
                "source": draw.get("source"), "bucket": bucket,
            })
    return moves


def assemble_brief(profile: dict, *, noc_code: Optional[str] = None,
                   letter_text: Optional[str] = None, draws: Optional[list] = None,
                   supporting_facts: Optional[list] = None, as_of: Optional[str] = None,
                   narrator: Any = None) -> dict:
    """Assemble the consultant brief. Every number/citation is a core-tool result copied unchanged;
    only `prose` is model-written, and it is screened for an eligibility verdict before inclusion.

    Args mirror BriefRequest. `narrator`, when given, is a callable(prompt)->object-with-.message
    (a Strands agent) that writes the cover prose from the assembled deterministic payload.
    """
    crs = compute_crs(profile, as_of=as_of)  # NUMBER from the core
    deadlines = crs_deadlines(profile, as_of=as_of) if profile.get("date_of_birth") else None
    reachability = (reachable_paths(profile, draws, as_of=as_of) if draws else None)

    letter_audit = None
    correction_draft = None
    if noc_code and letter_text:
        letter_audit = audit_reference_letter(letter_text, noc_code)          # cited gaps from core
        correction_draft = draft_corrected_letter(letter_text, noc_code, supporting_facts or None)

    brief = {
        "as_of": as_of,
        "profile_summary": _profile_summary(profile, crs),
        "crs": crs,
        "deadlines": deadlines,
        "next_moves": _next_moves(reachability),
        "letter_audit": letter_audit,
        "correction_draft": correction_draft,
        "prose": "",
        "disclaimer": DISCLAIMER,
    }

    if narrator is not None:
        brief["prose"] = _synthesize_prose(narrator, brief)
    return brief


def _synthesize_prose(narrator: Any, brief: dict) -> str:
    """Have the model write the cover prose from the assembled deterministic payload, then SCREEN it
    with the never-assert-eligibility gate. A prose that states an eligibility verdict is dropped
    (empty), never emitted — the structured, cited payload stands on its own. Numbers are the
    payload's; the model only phrases."""
    import json

    prompt = (
        "Write a short cover note (3-5 sentences) for an immigration consultant, summarizing this "
        "MapleGuard brief. Use ONLY the facts, numbers, and citations in the payload. Do not compute "
        "or change any number. Do not state or imply the person is eligible, qualifies, or is "
        "guaranteed anything — report the cited facts and let the consultant decide.\n\n"
        + json.dumps(brief, default=str)
    )
    try:
        message = narrator(prompt).message
        text = message if isinstance(message, str) else str(message)
    except Exception:  # pragma: no cover - prose is additive; a failure leaves the payload intact
        return ""
    return text if never_assert_eligibility(text).allowed else ""
