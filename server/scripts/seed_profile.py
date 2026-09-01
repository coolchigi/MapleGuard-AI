"""Seed one monitored profile through the REAL persistence path (for demos/smoke).

This is not a shortcut around the app: it writes through exactly the store the API's
`POST /profiles` endpoint and the monitor share (`config.build_profile_store`), selected by the
same env (file locally, DynamoDB when `MAPLEGUARD_PROFILES_TABLE` is set). So a profile seeded
here is indistinguishable from one a user saved through the form, and the monitor watches it.

Usage (from server/, with PYTHONPATH=.):
    python scripts/seed_profile.py                 # seeds a demo profile, prints its id
    python scripts/seed_profile.py path/to/profile.json [--id my-id]

The profile JSON is the same shape /position and /dashboard take (validated by serde).
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid

from agent import serde
from agent.config import Deployment, build_profile_store
from agent.monitor import StoredProfile

_DEMO_PROFILE = {
    "education": "bachelors-or-three-year",
    "first_language": {"speaking": 9, "listening": 9, "reading": 9, "writing": 9},
    "date_of_birth": "1996-07-01",
    "canadian_work_years": 1,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed a monitored profile via the real store.")
    parser.add_argument("profile_json", nargs="?", help="path to a profile JSON file")
    parser.add_argument("--id", dest="profile_id", default=None, help="stable profile id")
    args = parser.parse_args(argv)

    profile = _DEMO_PROFILE
    if args.profile_json:
        with open(args.profile_json) as f:
            profile = json.load(f)

    serde.profile_from_dict(profile)  # validate through the single authoritative path
    store = build_profile_store(Deployment.from_env())
    profile_id = args.profile_id or uuid.uuid4().hex
    store.put(StoredProfile(id=profile_id, profile=profile))

    backend = Deployment.from_env().profiles_backend
    print(f"seeded profile id={profile_id} into the {backend} profile store "
          f"(the monitor will watch it on its next tick)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
