"""The dashboard view model — one JSON document the web app renders directly.

The compute endpoints (`/position`, `/trajectory`, `/deadlines`) return the engine's raw result
dicts. The dashboard needs slightly more than that: the same numbers *grouped* into the
categories the panels draw, with the descriptive labels, the IRCC caps, the humanised dates and
the last-draw delta already resolved. Doing that assembly here — once, on the server, over the
typed `Score`/`Trajectory` the engine returned — means the browser never reconstructs a category
from a flat breakdown list, and the shape cannot drift between the live API and the precomputed
demo file.

This module is pure: a `Profile` in, a JSON-safe dict out. No FastAPI, no I/O, no model. It has
two callers, and they produce identical output for the same profile and date:

  * `POST /dashboard` (api/app.py) — the live path the Next.js app calls.
  * `web/scripts/precompute.py` — writes `web/src/data/demo.json`, the app's offline fallback.

That identity is the point: the fallback is not an approximation of the live response, it is the
same document computed ahead of time, so the client needs exactly one TypeScript type for both.

Every *number* here is the engine's. Only the label text and the grouping are added.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from crs import LanguageScores, Profile, Score, crs, deadlines, trajectory
from crs import tables as T

CRS_CRITERIA = "canada.ca/crs-criteria"
ROUNDS = "canada.ca/rounds-of-invitations"

# The most recent general round, used only for the "N points below the last draw" line. It is a
# stated constant with its citation rather than a live fetch, so this stays a pure function;
# callers holding fresher data pass `last_draw_score`/`last_draw_date`, and the live feed is
# available on its own at `GET /draws`.
LAST_GENERAL_DRAW = 518
LAST_DRAW_DATE = "2026-08-06"

DEFAULT_HORIZON_YEARS = 3

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

EDUCATION_LABELS: dict[str, str] = {
    "none-or-less-than-secondary": "Less than secondary school",
    "secondary": "Secondary school (high school)",
    "one-year-post-secondary": "One-year post-secondary credential",
    "two-year-post-secondary": "Two-year post-secondary credential",
    "bachelors-or-three-year": "Bachelor’s degree (or 4-year post-secondary program)",
    "two-or-more-certificates": "Two or more credentials (one 3+ years)",
    "masters-or-professional": "Master’s or professional degree",
    "doctoral": "Doctoral degree (PhD)",
}

# Additional-factor line labels, keyed by the engine's LineItem.factor.
_ADDITIONAL_LABELS = {
    "provincial_nomination": "Provincial nomination",
    "sibling_in_canada": "Sibling in Canada",
    "canadian_study": "Canadian post-secondary study",
    "french_bonus": "French-language bonus",
}


# --------------------------------------------------------------------- formatting
def _iso(d: date) -> str:
    return d.isoformat()


def _human(d: date) -> str:
    """'Aug 22, 2026'. Written out rather than strftime('%b %-d, %Y'): the no-pad '-' flag is
    glibc-only and raises on Windows, and this runs on both."""
    return f"{_MONTHS[d.month - 1]} {d.day}, {d.year}"


def _years(n: int) -> str:
    return "none" if n <= 0 else ("1 year" if n == 1 else f"{n} years")


def _clb_label(scores: LanguageScores) -> str:
    """'CLB 9' when the four abilities match, else the per-ability reading."""
    abilities = (scores.speaking, scores.listening, scores.reading, scores.writing)
    if len(set(abilities)) == 1:
        return f"CLB {abilities[0]}"
    return f"CLB {'/'.join(str(a) for a in abilities)}"


def _even_split_meta(scores: LanguageScores, points: int) -> Optional[str]:
    """'= 31 pts x 4 abilities' when every ability scores the same; nothing to say otherwise."""
    abilities = {scores.speaking, scores.listening, scores.reading, scores.writing}
    if len(abilities) == 1 and points and points % 4 == 0:
        return f"= {points // 4} pts × 4 abilities"
    return None


def _item(label: str, points: int, meta: Optional[str] = None,
          muted: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"label": label, "points": points}
    if meta:
        out["meta"] = meta
    if muted:
        out["muted"] = True
    return out


# ------------------------------------------------------------------- the categories
def _core_category(profile: Profile, score: Score, pts: dict[str, int],
                   as_of: date, spouse_scored: bool) -> dict[str, Any]:
    age = profile.age_at(as_of)
    first = profile.first_language
    second = profile.second_language

    items = [
        _item(f"Age · {age}", pts.get("age", 0),
              meta="spouse-applicant age grid" if spouse_scored else "single-applicant age grid",
              muted=pts.get("age", 0) == 0),
        _item(f"Education · {EDUCATION_LABELS.get(profile.education, profile.education)}",
              pts.get("education", 0)),
        _item(f"First language · {_clb_label(first)}", pts.get("first_language", 0),
              meta=_even_split_meta(first, pts.get("first_language", 0))),
    ]

    if second is not None:
        tongue = "French" if profile.second_language_is_french else "second language"
        cap = T.SECOND_LANG_CAP_SPOUSE if spouse_scored else T.SECOND_LANG_CAP_SINGLE
        items.append(_item(f"Second language · {tongue}, {_clb_label(second)}",
                           pts.get("second_language", 0), meta=f"capped at {cap}",
                           muted=pts.get("second_language", 0) == 0))
    else:
        items.append(_item("Second language · none", 0, muted=True))

    items.append(_item(f"Canadian work · {_years(profile.canadian_work_years)}",
                       pts.get("canadian_work", 0),
                       muted=profile.canadian_work_years <= 0))

    cap = T.CORE_MAX_SPOUSE if spouse_scored else T.CORE_MAX_SINGLE
    grids = "spouse-applicant" if spouse_scored else "single-applicant"
    return {
        "code": "A", "label": "CORE HUMAN CAPITAL", "cap": cap, "subtotal": score.core,
        "items": items,
        "note": f"Each factor read from IRCC’s {grids} grids, then summed — "
                f"the category is capped at {cap}.",
        "cite": CRS_CRITERIA,
    }


def _spouse_category(profile: Profile, score: Score, pts: dict[str, int]) -> dict[str, Any]:
    edu = profile.spouse_education or "none-or-less-than-secondary"
    lang = profile.spouse_first_language
    items = [
        _item(f"Spouse education · {EDUCATION_LABELS.get(edu, edu)}",
              pts.get("spouse_education", 0), muted=pts.get("spouse_education", 0) == 0),
        _item("Spouse language · " + (_clb_label(lang) if lang else "none"),
              pts.get("spouse_language", 0), muted=lang is None),
        _item(f"Spouse Canadian work · {_years(profile.spouse_canadian_work_years)}",
              pts.get("spouse_canadian_work", 0),
              muted=profile.spouse_canadian_work_years <= 0),
    ]
    return {
        "code": "S", "label": "SPOUSE OR PARTNER", "cap": T.SPOUSE_MAX,
        "subtotal": score.spouse, "items": items,
        "note": "Scored only because your partner accompanies you and is not already a citizen "
                f"or permanent resident — capped at {T.SPOUSE_MAX}.",
        "cite": CRS_CRITERIA,
    }


def _transfer_category(profile: Profile, score: Score, pts: dict[str, int]) -> dict[str, Any]:
    items = [
        _item("Education × language & Canadian work", pts.get("transfer_education", 0),
              meta="group capped at 50", muted=pts.get("transfer_education", 0) == 0),
        _item(f"Foreign work · {_years(profile.foreign_work_years)} "
              f"× language & Canadian work", pts.get("transfer_foreign_work", 0),
              meta="group capped at 50", muted=pts.get("transfer_foreign_work", 0) == 0),
    ]
    if profile.has_certificate_of_qualification:
        items.append(_item("Certificate of qualification × language",
                           pts.get("transfer_certificate", 0), meta="group capped at 50",
                           muted=pts.get("transfer_certificate", 0) == 0))
    return {
        "code": "B", "label": "SKILL TRANSFERABILITY", "cap": T.SKILL_TRANSFER_MAX,
        "subtotal": score.skill_transfer, "items": items,
        "note": "Three factor-groups, each capped at 50; the total is capped at "
                f"{T.SKILL_TRANSFER_MAX}.",
        "cite": CRS_CRITERIA,
    }


def _additional_category(score: Score, pts: dict[str, int]) -> dict[str, Any]:
    """Earned additional factors become line items; the ones still unclaimed stay as levers,
    each showing the IRCC value it would add."""
    v = T.MAX_ADDITIONAL.values
    items = [_item(_ADDITIONAL_LABELS[f], p) for f, p in pts.items() if f in _ADDITIONAL_LABELS]

    levers: list[dict[str, str]] = []
    if "provincial_nomination" not in pts:
        levers.append({"label": "Provincial nomination",
                       "points": f"+{v['provincial_nomination']}"})
    if "sibling_in_canada" not in pts:
        levers.append({"label": "Sibling in Canada", "points": f"+{v['sibling_in_canada']}"})
    if "canadian_study" not in pts:
        levers.append({"label": "Canadian study",
                       "points": f"+{v['canadian_study_1_2_years']}"
                                 f"–{v['canadian_study_3_plus_years']}"})
    if "french_bonus" not in pts:
        levers.append({"label": "French-language bonus",
                       "points": f"+{v['french_nclc7_english_clb4_or_less']}"
                                 f"–{v['french_nclc7_english_clb5_plus']}"})

    if items and levers:
        note = "Claimed factors are counted above; every lever below is still on the table."
    elif items:
        note = "Every additional factor on the grid is already claimed on this profile."
    else:
        note = "None active on this profile yet — each is the lever that moves the number."

    out: dict[str, Any] = {
        "code": "C", "label": "ADDITIONAL", "cap": T.ADDITIONAL_MAX,
        "subtotal": score.additional, "note": note, "cite": CRS_CRITERIA,
    }
    if items:
        out["items"] = items
    if levers:
        out["levers"] = levers
    return out


# ---------------------------------------------------------------------- the builder
def _plus_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29 in a non-leap year
        return date(d.year + years, 3, 1)


def build_dashboard(profile: Profile,
                    as_of: Optional[date] = None,
                    horizon: Optional[date] = None,
                    horizon_years: int = DEFAULT_HORIZON_YEARS,
                    last_draw_score: int = LAST_GENERAL_DRAW,
                    last_draw_date: str = LAST_DRAW_DATE,
                    generated_by: str = "api /dashboard (real crs engine)") -> dict:
    """Assemble the whole dashboard document for `profile`.

    `as_of` defaults to today and dates the entire assessment (age is date-dependent). The
    trajectory runs from `as_of` to `horizon`, or to `as_of` + `horizon_years` when no explicit
    horizon is given. Raises ValueError when the profile carries no date_of_birth, since a
    timeline cannot be run from a static age — the API maps that to a 422 rather than returning
    half a document.
    """
    if profile.date_of_birth is None:
        raise ValueError("dashboard needs a date_of_birth on the profile "
                         "(the trajectory runs the published grids forward over dates)")
    today = as_of or date.today()
    if horizon is None:
        if horizon_years < 1:
            raise ValueError("horizon_years must be at least 1")
        horizon = _plus_years(today, horizon_years)
    if horizon <= today:
        raise ValueError("horizon must be after as_of")

    score = crs(profile, today)
    pts = {li.factor: li.points for li in score.breakdown}
    spouse_scored = profile.scored_with_spouse()

    categories = [_core_category(profile, score, pts, today, spouse_scored)]
    if spouse_scored:
        categories.append(_spouse_category(profile, score, pts))
    categories.append(_transfer_category(profile, score, pts))
    categories.append(_additional_category(score, pts))

    # --- the time machine ---------------------------------------------------
    dl = deadlines(profile, as_of=today)
    traj = trajectory(profile, today, horizon)
    total_at = {_iso(p.date): p.total for p in traj.points}

    points = [{"date": _iso(p.date), "dateHuman": _human(p.date), "total": p.total}
              for p in traj.points]
    cliffs = [{"date": _iso(c.date), "dateHuman": _human(c.date), "kind": c.kind,
               "delta": c.delta, "total": total_at.get(_iso(c.date)), "label": c.label}
              for c in traj.cliffs]

    expiry = dl.test_expiry
    return {
        "generatedBy": generated_by,
        "asOf": _iso(today),
        "asOfHuman": _human(today),
        "position": {
            "total": score.total,
            "core": score.core,
            "spouse": score.spouse,
            "skillTransfer": score.skill_transfer,
            "additional": score.additional,
            "categories": categories,
        },
        "lastDraw": {
            "score": last_draw_score,
            "delta": score.total - last_draw_score,
            "cite": ROUNDS,
            "date": last_draw_date,
        },
        "trajectory": {
            "points": points,
            "cliffs": cliffs,
            "testExpiry": _iso(expiry) if expiry else None,
            "testExpiryHuman": _human(expiry) if expiry else None,
            "testExpiryDelta": dl.test_expiry_cliff.delta if dl.test_expiry_cliff else None,
            "daysToExpiry": (expiry - today).days if expiry else None,
            "endTotal": points[-1]["total"],
        },
    }


# ------------------------------------------------------------------ dict boundary
def dashboard_from_dict(profile: dict,
                        as_of: Optional[str] = None,
                        horizon_years: int = DEFAULT_HORIZON_YEARS,
                        last_draw_score: Optional[int] = None,
                        last_draw_date: Optional[str] = None) -> dict:
    """JSON-in / JSON-out wrapper for the HTTP layer.

    Deserialization goes through `agent.serde`, which is the single authoritative validation
    path for a profile dict — it raises on a malformed profile rather than defaulting one, so a
    bad request can never score as a real candidate. Anything it raises (plus the date_of_birth
    and horizon checks in `build_dashboard`) surfaces as a 422 in `api.app`.
    """
    from agent import serde

    return build_dashboard(
        serde.profile_from_dict(profile),
        as_of=serde._parse_date(as_of),
        horizon_years=horizon_years,
        last_draw_score=LAST_GENERAL_DRAW if last_draw_score is None else last_draw_score,
        last_draw_date=last_draw_date or LAST_DRAW_DATE,
    )
