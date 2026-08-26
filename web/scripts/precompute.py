"""Precompute the demo dashboard data from the REAL CRS engine.

Runs the deterministic core once for the demo profile and writes every number
the web dashboard shows into src/data/demo.json. The app never computes a CRS
number itself, it renders these. Re-run after any engine change:

    cd .. && PYTHONPATH=mapleguard python3 mapleguard/.claude/worktrees/<wt>/web/scripts/precompute.py

or from the mapleguard repo root:  PYTHONPATH=. python3 <path>/precompute.py

Every value below comes from crs.crs / crs.deadlines / crs.trajectory. Labels
are descriptive text; points, subtotals, caps and cliff deltas are the engine's.
"""
from __future__ import annotations

import json
import os
from datetime import date

from crs import LanguageScores, Profile, crs, deadlines, trajectory
from crs import tables as T

# --- the demo profile (the shape tests/test_timeline.py uses) --------------
AS_OF = date(2026, 8, 22)          # the "Assessment" date shown on the panels
HORIZON = date(2029, 12, 31)       # trajectory end: today + ~3 years
LAST_GENERAL_DRAW = 518            # canada.ca/rounds-of-invitations, 2026-08-06
LAST_DRAW_DATE = "2026-08-06"


def L(clb: int) -> LanguageScores:
    return LanguageScores(clb, clb, clb, clb)


PROFILE = Profile(
    education="bachelors-or-three-year",
    first_language=L(9),
    date_of_birth=date(1994, 11, 3),
    canadian_work_years=2,
    foreign_work_years=3,
    first_language_test_date=date(2025, 3, 1),  # results valid 2 yrs -> expires 2027-03-01
)

CRS_CRITERIA = "canada.ca/crs-criteria"
ROUNDS = "canada.ca/rounds-of-invitations"


def _fmt(d: date) -> str:
    return d.isoformat()


def _human(d: date) -> str:
    return d.strftime("%b %-d, %Y")


def build() -> dict:
    score = crs(PROFILE, AS_OF)
    pts = {li.factor: li.points for li in score.breakdown}
    age_today = PROFILE.age_at(AS_OF)

    # Category A - core human capital. Points are the engine's; labels describe them.
    core_items = [
        {"label": f"Age · {age_today}", "meta": "single-applicant age grid", "points": pts["age"]},
        {"label": "Education · bachelor’s / 3-year", "points": pts["education"]},
        {"label": "First language · CLB 9", "meta": "= 31 pts × 4 abilities", "points": pts["first_language"]},
        {"label": "Second language · none", "points": pts["second_language"], "muted": True},
        {"label": f"Canadian work · {PROFILE.canadian_work_years} years", "points": pts["canadian_work"]},
    ]

    # Category B - skill transferability. Each factor-group capped at 50, total at 100.
    transfer_items = [
        {"label": "Education × language & Canadian work", "meta": "group capped at 50",
         "points": pts["transfer_education"]},
        {"label": f"Foreign work · {PROFILE.foreign_work_years} yrs × language & Canadian work",
         "meta": "group capped at 50", "points": pts["transfer_foreign_work"]},
    ]
    if pts.get("transfer_certificate"):
        transfer_items.append({"label": "Certificate of qualification × language",
                               "meta": "group capped at 50", "points": pts["transfer_certificate"]})

    # Category C - additional. None active on this profile; show the levers with IRCC values.
    add = T.MAX_ADDITIONAL.values
    levers = [
        {"label": "Provincial nomination", "points": f"+{add['provincial_nomination']}"},
        {"label": "Sibling in Canada", "points": f"+{add['sibling_in_canada']}"},
        {"label": "Canadian study",
         "points": f"+{add['canadian_study_1_2_years']}–{add['canadian_study_3_plus_years']}"},
        {"label": "French-language bonus",
         "points": f"+{add['french_nclc7_english_clb4_or_less']}–{add['french_nclc7_english_clb5_plus']}"},
    ]

    categories = [
        {
            "code": "A", "label": "CORE HUMAN CAPITAL", "cap": T.CORE_MAX_SINGLE,
            "subtotal": score.core, "items": core_items,
            "note": "Each factor read from IRCC’s single-applicant grids, then summed — the category is capped at 500.",
            "cite": CRS_CRITERIA,
        },
        {
            "code": "B", "label": "SKILL TRANSFERABILITY", "cap": T.SKILL_TRANSFER_MAX,
            "subtotal": score.skill_transfer, "items": transfer_items,
            "note": "Three factor-groups, each capped at 50; the total is capped at 100.",
            "cite": CRS_CRITERIA,
        },
        {
            "code": "C", "label": "ADDITIONAL", "cap": T.ADDITIONAL_MAX,
            "subtotal": score.additional, "levers": levers,
            "note": "None active on this profile yet — each is the lever that moves the number.",
            "cite": CRS_CRITERIA,
        },
    ]

    # --- the time machine -------------------------------------------------
    dl = deadlines(PROFILE, as_of=AS_OF)
    traj = trajectory(PROFILE, AS_OF, HORIZON)

    # map date -> resulting total from the trajectory points
    total_at = {_fmt(p.date): p.total for p in traj.points}

    cliff_rows = []
    for c in traj.cliffs:
        cliff_rows.append({
            "date": _fmt(c.date),
            "dateHuman": _human(c.date),
            "kind": c.kind,
            "delta": c.delta,
            "total": total_at.get(_fmt(c.date)),
            "label": c.label,
        })

    points = [{"date": _fmt(p.date), "dateHuman": _human(p.date), "total": p.total} for p in traj.points]

    test_expiry = dl.test_expiry
    days_to_expiry = (test_expiry - AS_OF).days if test_expiry else None

    data = {
        "generatedBy": "web/scripts/precompute.py (real crs engine)",
        "asOf": _fmt(AS_OF),
        "asOfHuman": AS_OF.strftime("%b %-d, %Y"),
        "position": {
            "total": score.total,
            "core": score.core,
            "skillTransfer": score.skill_transfer,
            "additional": score.additional,
            "categories": categories,
        },
        "lastDraw": {
            "score": LAST_GENERAL_DRAW,
            "delta": score.total - LAST_GENERAL_DRAW,
            "cite": ROUNDS,
            "date": LAST_DRAW_DATE,
        },
        "trajectory": {
            "points": points,
            "cliffs": cliff_rows,
            "testExpiry": _fmt(test_expiry) if test_expiry else None,
            "testExpiryHuman": _human(test_expiry) if test_expiry else None,
            "testExpiryDelta": dl.test_expiry_cliff.delta if dl.test_expiry_cliff else None,
            "daysToExpiry": days_to_expiry,
            "endTotal": points[-1]["total"],
        },
    }
    return data


def main() -> None:
    data = build()
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "..", "src", "data", "demo.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {os.path.relpath(out)}  (CRS {data['position']['total']} -> {data['trajectory']['endTotal']})")


if __name__ == "__main__":
    main()
