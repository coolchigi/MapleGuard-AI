"""Precompute the offline demo dashboard from the REAL CRS engine.

Writes `web/src/data/demo.json` — the document the web app renders when the Python API is not
reachable. It calls `api.dashboard.build_dashboard`, the exact function behind `POST /dashboard`,
so the fallback file is not an approximation of the live response: it is the same response,
computed ahead of time for one fixed profile and one fixed assessment date. That is what lets
the client type both with a single `DashboardData` interface.

Re-run after any engine change, from the repo root:

    PYTHONPATH=server python3 web/scripts/precompute.py

(all Python lives under server/ since the 2026-08-26 restructure)
"""
from __future__ import annotations

import json
import os
from datetime import date

from api.dashboard import build_dashboard
from crs import LanguageScores, Profile

# --- the demo profile (the shape tests/test_timeline.py uses) --------------
AS_OF = date(2026, 8, 22)          # the "Assessment" date shown on the panels
HORIZON = date(2029, 12, 31)       # trajectory end: today + ~3 years


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


def build() -> dict:
    return build_dashboard(
        PROFILE,
        as_of=AS_OF,
        horizon=HORIZON,
        generated_by="web/scripts/precompute.py (real crs engine)",
    )


def main() -> None:
    data = build()
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "..", "src", "data", "demo.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {os.path.relpath(out)}  "
          f"(CRS {data['position']['total']} -> {data['trajectory']['endTotal']})")


if __name__ == "__main__":
    main()
