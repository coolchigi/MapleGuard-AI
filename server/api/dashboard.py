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

# The "N points below the last draw" line is benchmarked against a REAL cited round, never a
# hardcoded number. `build_dashboard` takes a `benchmark` (assembled from the live rounds feed by
# `benchmark_from_records`) and refuses to invent one: with no benchmark it reports the comparison
# as unavailable rather than fabricating a cutoff. This keeps the builder pure; the API endpoint
# does the live fetch and passes the result in.

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


# --------------------------------------------------------------------- draw benchmark
_GENERAL_NOTE = ("Last all-program (general) draw; none since. "
                 "Current draws are category-based.")

# How many recent distinct draws to carry for the "other recent draws" comparison list.
_RECENT_LIMIT = 8


def _rec_dict(r) -> dict:
    return {"score": r.cutoff, "date": r.date.isoformat(), "name": r.name,
            "round": r.round_number, "kind": r.kind, "category": r.category,
            "source_url": r.citation.round_url}


def benchmark_from_records(records) -> Optional[dict]:
    """Assemble the draw benchmark from live ingest records, or None when the feed yields no
    usable draw. This stays profile-agnostic: it gathers the real cited rounds and leaves the
    choice of WHICH one to headline to `_last_draw_view`, which has the profile.

    `latest` is the most recent cited round of any kind. `recent` is the most recent distinct
    draws (deduped by category, newest first) so the view can pick the one relevant to the
    applicant and list the rest. `general` is the most recent all-program round when the latest
    is not itself general, so the hero can state, cited, that general draws have stopped. Every
    value is a real cutoff from a real cited round -- nothing is invented."""
    from ingest import latest_draw, sort_records

    latest = latest_draw(records)
    if latest is None:
        return None

    recent: list[dict] = []
    seen: set = set()
    for r in sort_records(records, newest_first=True):
        if r.cutoff is None or r.needs_manual_check:
            continue
        key = (r.kind, r.category)
        if key in seen:
            continue
        seen.add(key)
        recent.append(_rec_dict(r))
        if len(recent) >= _RECENT_LIMIT:
            break

    benchmark = {"latest": _rec_dict(latest), "recent": recent, "general": None}
    if latest.kind != "general":
        general = latest_draw(records, kind="general")
        if general is not None:
            benchmark["general"] = {"score": general.cutoff, "round": general.round_number,
                                    "date": general.date.isoformat(),
                                    "source_url": general.citation.round_url}
    return benchmark


def _benchmark_from_override(score: int, date: Optional[str]) -> dict:
    """A benchmark built from a caller-supplied cutoff (the `/dashboard` override / tests). It is
    still a real number the caller vouches for, just not fetched here."""
    return {"latest": {"score": score, "date": date, "name": None, "round": None,
                       "kind": None, "category": None, "source_url": ROUNDS}, "general": None}


def _relevance(profile: Profile, draw: dict) -> tuple[Optional[bool], str]:
    """Is this cited draw relevant to THIS applicant? Deterministic, read off the profile's own
    fields and the official 2026 category rules. Returns (True / False / None, reason); None means
    the profile lacks the input to decide (an occupation category with no NOC on file), never a
    guess. This is a relevance signal for which real draw to headline, not an assertion of
    eligibility -- that determination stays with IRCC."""
    kind = draw.get("kind")
    category = draw.get("category")
    name = draw.get("name") or ""

    if kind == "general":
        return True, "every candidate in the pool is measured on CRS"
    if category == "canadian-experience-class":
        ok = profile.canadian_work_years >= 1
        return ok, ("you report Canadian skilled work experience" if ok
                    else "these rounds invite candidates with Canadian work experience")
    if category == "provincial-nominee":
        ok = profile.has_provincial_nomination
        return ok, ("you hold a provincial nomination" if ok
                    else "these rounds invite candidates who already hold a provincial nomination")
    if category == "federal-skilled-worker":
        return True, "Federal Skilled Worker is a broad skilled-worker program"
    if category == "federal-skilled-trades":
        ok = profile.has_certificate_of_qualification
        return ok, ("you hold a trade certificate of qualification" if ok
                    else "these rounds invite skilled-trades candidates")

    from ingest import category_eligibility, resolve_category
    slug = resolve_category(category or name)
    if slug == "french":
        sl = profile.second_language
        clb = sl.min_clb() if (profile.second_language_is_french and sl) else 0
        res = category_eligibility("french", french_nclc=clb)
        return res.eligible, res.reason
    if slug is not None:
        res = category_eligibility(slug, noc_code=getattr(profile, "noc_code", None))
        return res.eligible, res.reason
    return None, "eligibility for this round is not derivable from your profile"


def _choose_headline(profile: Profile, benchmark: dict) -> tuple[dict, Optional[str], Optional[str]]:
    """Pick the real cited round to headline: the most recent draw RELEVANT to this profile.
    When none is relevant, fall back to a broad program draw (or the newest) flagged 'reference'
    so the hero can say it is shown for comparison rather than as the applicant's own draw.
    Returns (headline_draw, relevance, reason)."""
    recent = benchmark.get("recent")
    if not recent:
        # override / test path: only a caller-supplied `latest` is present.
        return benchmark["latest"], None, None

    scored = [(d, *_relevance(profile, d)) for d in recent]  # recent is newest first
    matched = [t for t in scored if t[1] is True]
    if matched:
        draw, _ok, reason = matched[0]
        return draw, "matched", reason

    broad = next((t for t in scored if t[0].get("kind") == "general"
                  or t[0].get("category") in ("canadian-experience-class",
                                              "federal-skilled-worker")), None)
    draw = (broad or scored[0])[0]
    return draw, "reference", "no recent draw matches your profile; shown for reference"


def _others(profile: Profile, benchmark: dict, headline: dict) -> list[dict]:
    """The other recent draws, each flagged relevant / not / unknown to this profile with a cited
    reason, so specialty rounds the applicant is not in read as secondary, not the headline."""
    out: list[dict] = []
    for d in benchmark.get("recent") or []:
        if d.get("round") == headline.get("round") and d.get("date") == headline.get("date"):
            continue
        ok, reason = _relevance(profile, d)
        out.append({"score": d["score"], "date": d["date"], "name": d["name"],
                    "round": d["round"], "kind": d["kind"], "category": d.get("category"),
                    "sourceUrl": d.get("source_url"), "relevant": ok, "reason": reason})
    return out


def _last_draw_view(benchmark: Optional[dict], total: int, profile: Profile) -> dict:
    """The `lastDraw` block the client renders. With no benchmark the comparison is reported
    unavailable (never a fabricated cutoff); with one, the headline is the most recent draw
    relevant to this profile, the delta is `total - cutoff`, and the real round's
    name/number/date/source travel with it so the citation links to that exact round. The other
    recent draws ride along in `others`, each flagged for relevance."""
    if not benchmark or not benchmark.get("latest"):
        return {"available": False, "score": None, "delta": None, "cite": ROUNDS, "date": None,
                "note": "No draw benchmark available (live rounds feed unreachable)."}
    headline, relevance, reason = _choose_headline(profile, benchmark)
    view = {"available": True, "score": headline["score"], "delta": total - headline["score"],
            "name": headline.get("name"), "round": headline.get("round"),
            "kind": headline.get("kind"), "category": headline.get("category"),
            "relevance": relevance, "matchReason": reason,
            "cite": ROUNDS, "sourceUrl": headline.get("source_url"), "date": headline["date"]}
    general = benchmark.get("general")
    view["general"] = None if general is None else {
        "score": general["score"], "round": general["round"], "date": general["date"],
        "sourceUrl": general.get("source_url"), "note": _GENERAL_NOTE}
    view["others"] = _others(profile, benchmark, headline)
    return view


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
                    benchmark: Optional[dict] = None,
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
        "lastDraw": _last_draw_view(benchmark, score.total, profile),
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
                        benchmark: Optional[dict] = None,
                        last_draw_score: Optional[int] = None,
                        last_draw_date: Optional[str] = None) -> dict:
    """JSON-in / JSON-out wrapper for the HTTP layer.

    Deserialization goes through `agent.serde`, which is the single authoritative validation
    path for a profile dict — it raises on a malformed profile rather than defaulting one, so a
    bad request can never score as a real candidate. Anything it raises (plus the date_of_birth
    and horizon checks in `build_dashboard`) surfaces as a 422 in `api.app`.

    `benchmark` is the live draw benchmark the endpoint assembled from the feed. A caller may
    instead pass `last_draw_score` (+ optional date) to force a specific cutoff (the request
    override / tests); with neither, the draw comparison is reported unavailable, never faked.
    """
    from agent import serde

    if benchmark is None and last_draw_score is not None:
        benchmark = _benchmark_from_override(last_draw_score, last_draw_date)

    return build_dashboard(
        serde.profile_from_dict(profile),
        as_of=serde._parse_date(as_of),
        horizon_years=horizon_years,
        benchmark=benchmark,
    )
