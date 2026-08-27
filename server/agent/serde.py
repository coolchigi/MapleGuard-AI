"""Plain-dict (de)serialization between the model's JSON and the deterministic core.

The model speaks JSON. The engine speaks typed dataclasses (`Profile`, `Draw`,
`BCJobOffer`) and returns typed results (`Score`, `Trajectory`, ...). This module is
the only translation layer: it builds typed inputs from the loose dicts a model emits,
and serializes typed results back to JSON-safe dicts that carry every field and every
citation the core produced. No I/O, no model, no strands dependency. Pure functions.

Serialization is faithful: the dict for a result mirrors the dataclass one-to-one, so
nothing (least of all a citation) is dropped in transport. Where the core already ships a
`.as_dict()` / `.to_dict()`, we defer to it rather than re-describe the shape here.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from crs import LanguageScores, Profile, Score
from crs.timeline import Cliff, Deadlines, Trajectory
from paths import Draw, MoveResult, PathResult, Reachability
from pnp import BCJobOffer, SirsResult


# ------------------------------------------------------------------- input side
def _parse_date(value: Any) -> Optional[date]:
    """ISO 'YYYY-MM-DD' -> date. None passes through. Never guesses a partial date."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def language_from_dict(value: Any) -> Optional[LanguageScores]:
    """{'speaking':.., 'listening':.., 'reading':.., 'writing':..} -> LanguageScores."""
    if value is None:
        return None
    if isinstance(value, LanguageScores):
        return value
    return LanguageScores(
        speaking=int(value.get("speaking", 0)),
        listening=int(value.get("listening", 0)),
        reading=int(value.get("reading", 0)),
        writing=int(value.get("writing", 0)),
    )


# Keys the model may supply, mapped straight onto Profile fields.
_PROFILE_PASSTHROUGH_INTS = (
    "canadian_work_years", "foreign_work_years", "spouse_canadian_work_years",
    "canadian_post_secondary_years",
)
_PROFILE_PASSTHROUGH_BOOLS = (
    "spouse_accompanying", "spouse_is_pr_or_citizen", "has_certificate_of_qualification",
    "has_provincial_nomination", "has_sibling_in_canada", "second_language_is_french",
)


def profile_from_dict(data: dict) -> Profile:
    """Build a typed `Profile` from the model's JSON. Raises on a malformed profile
    rather than substituting a default, so a bad input never scores as a real one."""
    kwargs: dict[str, Any] = {
        "education": data["education"],
        "first_language": language_from_dict(data["first_language"]),
    }
    if "age" in data and data["age"] is not None:
        kwargs["age"] = int(data["age"])
    if data.get("date_of_birth"):
        kwargs["date_of_birth"] = _parse_date(data["date_of_birth"])
    if "marital_status" in data:
        kwargs["marital_status"] = data["marital_status"]

    if data.get("second_language") is not None:
        kwargs["second_language"] = language_from_dict(data["second_language"])
    if data.get("spouse_education") is not None:
        kwargs["spouse_education"] = data["spouse_education"]
    if data.get("spouse_first_language") is not None:
        kwargs["spouse_first_language"] = language_from_dict(data["spouse_first_language"])
    if data.get("first_language_test_date"):
        kwargs["first_language_test_date"] = _parse_date(data["first_language_test_date"])

    for key in _PROFILE_PASSTHROUGH_INTS:
        if key in data and data[key] is not None:
            kwargs[key] = int(data[key])
    for key in _PROFILE_PASSTHROUGH_BOOLS:
        if key in data and data[key] is not None:
            kwargs[key] = bool(data[key])

    return Profile(**kwargs)


def bc_offer_from_dict(value: Any) -> Optional[BCJobOffer]:
    if value is None:
        return None
    if isinstance(value, BCJobOffer):
        return value
    return BCJobOffer(
        hourly_wage=float(value["hourly_wage"]),
        area=value.get("area", "metro_vancouver"),
        is_tech_exempt=bool(value.get("is_tech_exempt", False)),
    )


def draw_from_dict(value: Any) -> Draw:
    """Build a `Draw` from JSON. A cutoff without a source is refused (trust posture:
    no uncited cutoff enters the engine)."""
    if isinstance(value, Draw):
        return value
    source = value.get("source")
    if not source:
        raise ValueError(f"draw {value.get('name')!r} has no source citation; refusing it")
    return Draw(
        kind=value["kind"],
        name=value["name"],
        cutoff=int(value["cutoff"]),
        date=_parse_date(value["date"]),
        source=source,
        category=value.get("category"),
        eligible_override=value.get("eligible_override"),
    )


# ------------------------------------------------------------------ output side
def score_to_dict(score: Score) -> dict:
    return {
        "total": score.total,
        "core": score.core,
        "spouse": score.spouse,
        "skill_transfer": score.skill_transfer,
        "additional": score.additional,
        "breakdown": [{"factor": li.factor, "points": li.points} for li in score.breakdown],
    }


def _cliff_to_dict(c: Cliff) -> dict:
    return {"date": c.date.isoformat(), "kind": c.kind, "label": c.label, "delta": c.delta}


def deadlines_to_dict(d: Deadlines) -> dict:
    return {
        "age_cliffs": [_cliff_to_dict(c) for c in d.age_cliffs],
        "test_expiry": d.test_expiry.isoformat() if d.test_expiry else None,
        "test_expiry_cliff": _cliff_to_dict(d.test_expiry_cliff) if d.test_expiry_cliff else None,
    }


def trajectory_to_dict(t: Trajectory) -> dict:
    return {
        "points": [{"date": p.date.isoformat(), "total": p.total} for p in t.points],
        "cliffs": [_cliff_to_dict(c) for c in t.cliffs],
    }


def sirs_to_dict(r: SirsResult) -> dict:
    return {
        "score": r.score,
        "breakdown": [{"factor": li.factor, "points": li.points} for li in r.breakdown],
        "job_offer_required": r.job_offer_required,
        "eligible_to_register": r.eligible_to_register,
        "crs_bonus_if_nominated": r.crs_bonus_if_nominated,
    }


def _move_to_dict(m: MoveResult) -> dict:
    return {"move": m.move, "effort": m.effort, "new_score": m.new_score,
            "closes_gap": m.closes_gap}


def _path_to_dict(p: PathResult) -> dict:
    out = {
        "draw": {"kind": p.draw.kind, "name": p.draw.name, "cutoff": p.draw.cutoff,
                 "date": p.draw.date.isoformat(), "source": p.draw.source,
                 "category": p.draw.category},
        "score_kind": p.score_kind,
        "your_score": p.your_score,
        "cutoff": p.cutoff,
        "eligible": p.eligible,
        "eligibility_reason": p.eligibility_reason,
        "clears": p.clears,
        "gap": p.gap,
        "closing_moves": [_move_to_dict(m) for m in p.closing_moves],
    }
    if p.job_offer_required is not None:
        out["job_offer_required"] = p.job_offer_required
    if p.crs_bonus_if_nominated is not None:
        out["crs_bonus_if_nominated"] = p.crs_bonus_if_nominated
    return out


def reachability_to_dict(r: Reachability) -> dict:
    return {
        "as_of": r.as_of.isoformat(),
        "reachable": [_path_to_dict(p) for p in r.reachable],
        "within_reach": [_path_to_dict(p) for p in r.within_reach],
        "blocked": [_path_to_dict(p) for p in r.blocked],
        "needs_eligibility_check": [_path_to_dict(p) for p in r.needs_eligibility_check],
    }


_REACHABILITY_BUCKETS = ("reachable", "within_reach", "blocked", "needs_eligibility_check")


def _draw_key(name: Any, draw_date: Any, source: Any) -> tuple:
    return (name, str(draw_date), source)


def attach_draw_provenance(reachability: dict, input_draws: list) -> dict:
    """Echo each input draw's `provenance` (the full ingest citation: round number, per-round
    page, fetch date) onto the matching draw in the reachability output, in place.

    `paths.Draw` carries only a single `source` string, so the richer citation `ingest_draws`
    produces is dropped at the engine boundary. This re-attaches it in the agent layer, keyed
    by (name, date, source), so a reported cutoff travels with its full provenance. It only
    copies a citation the caller already supplied; it never fabricates provenance.
    """
    index: dict[tuple, Any] = {}
    for d in input_draws:
        if not isinstance(d, dict):
            continue
        prov = d.get("provenance")
        if prov:
            index[_draw_key(d.get("name"), d.get("date"), d.get("source"))] = prov
    if not index:
        return reachability
    for bucket in _REACHABILITY_BUCKETS:
        for path in reachability.get(bucket, []):
            dd = path.get("draw", {})
            key = _draw_key(dd.get("name"), dd.get("date"), dd.get("source"))
            if key in index:
                dd["provenance"] = index[key]
    return reachability
