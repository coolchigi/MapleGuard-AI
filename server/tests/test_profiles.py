"""Profile intake: the store write path, the config seam, the API endpoints, and the loop.

The product loop is: a user saves a profile -> it lands in the monitored store -> the autonomous
monitor lists that same store and re-scores each profile against new draws. Before this, the
store was read-only and nothing wrote to it, so the monitor watched an empty set. These tests
prove the write path and that the API and the monitor share ONE store.

Offline and deterministic: file/in-memory stores and a fake DynamoDB table; the API is driven
through the TestClient with an injected store; the loop uses the fixture feed, no network.
"""
import json
import pathlib

import pytest

from agent.config import Deployment, build_profile_store
from agent.monitor import (CollectingAlertSink, FileProfileStore, InMemoryProfileStore,
                           InMemorySnapshotStore, MonitorDeps, StoredProfile, tick)

FIXTURE = pathlib.Path(__file__).parent.parent / "ingest" / "fixtures" / "ee_rounds_sample.json"
SOURCE = "https://www.canada.ca/rounds.json"

STRONG_PROFILE = {  # clears the top general cutoffs; a new general draw is actionable
    "education": "bachelors-or-three-year",
    "first_language": {"speaking": 10, "listening": 10, "reading": 10, "writing": 10},
    "date_of_birth": "1996-07-01", "canadian_work_years": 3,
    "first_language_test_date": "2025-09-30",
}


# --- 1. The stores round-trip (put -> list/get), across backends -----------------------
def test_storedprofile_serialization_round_trips():
    sp = StoredProfile(id="u1", profile=STRONG_PROFILE, bc_offer={"hourly_wage": 45.0})
    assert StoredProfile.from_dict(sp.to_dict()) == sp
    # bc_offer omitted when None (keeps the stored shape minimal)
    assert "bc_offer" not in StoredProfile(id="u2", profile=STRONG_PROFILE).to_dict()


def test_in_memory_profile_store_put_get_list_upsert():
    store = InMemoryProfileStore()
    assert store.list_profiles() == []
    store.put(StoredProfile(id="u1", profile=STRONG_PROFILE))
    store.put(StoredProfile(id="u1", profile={**STRONG_PROFILE, "canadian_work_years": 4}))  # upsert
    assert len(store.list_profiles()) == 1
    assert store.get("u1").profile["canadian_work_years"] == 4
    assert store.get("missing") is None


def test_file_profile_store_persists_across_instances(tmp_path):
    d = str(tmp_path / "profiles")
    FileProfileStore(d).put(StoredProfile(id="user-42", profile=STRONG_PROFILE,
                                          bc_offer={"hourly_wage": 50.0}))
    # A fresh instance over the same dir reads it back (this is the API<->monitor sharing locally).
    reread = FileProfileStore(d)
    assert [p.id for p in reread.list_profiles()] == ["user-42"]
    got = reread.get("user-42")
    assert got.profile == STRONG_PROFILE and got.bc_offer == {"hourly_wage": 50.0}
    assert reread.get("nope") is None


class _FakeDynamoTable:
    """A minimal DynamoDB Table: get_item/put_item/scan over an in-memory dict, item shape
    {"id": ..., "data": ...} as the real store writes."""
    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[Item["id"]] = Item

    def get_item(self, Key):
        item = self.items.get(Key["id"])
        return {"Item": item} if item else {}

    def scan(self, **kwargs):
        return {"Items": list(self.items.values())}


def test_dynamodb_profile_store_put_get_list_with_fake_table():
    from agent.stores_aws import DynamoDBProfileStore
    table = _FakeDynamoTable()
    store = DynamoDBProfileStore(table=table)
    store.put(StoredProfile(id="u1", profile=STRONG_PROFILE))
    # stored as one item with a JSON `data` attribute (the shared shape)
    assert "data" in table.items["u1"] and json.loads(table.items["u1"]["data"])["id"] == "u1"
    assert store.get("u1").profile == STRONG_PROFILE
    assert [p.id for p in store.list_profiles()] == ["u1"]
    assert store.get("missing") is None


# --- 2. The config seam selects file (dev) vs dynamodb (deploy) ------------------------
def test_build_profile_store_defaults_to_file_and_flips_to_dynamodb(tmp_path):
    from agent.monitor import FileProfileStore
    from agent.stores_aws import DynamoDBProfileStore
    # No table set -> file store (dev/local).
    dev = build_profile_store(Deployment.from_env(env={"MAPLEGUARD_PROFILES_DIR": str(tmp_path)}))
    assert isinstance(dev, FileProfileStore)
    # A table named -> DynamoDB (deploy). Construction is lazy on the boto3 client shape, but the
    # backend selection is what we assert here.
    deploy = Deployment.from_env(env={"MAPLEGUARD_PROFILES_TABLE": "mapleguard-profiles"})
    assert deploy.profiles_backend == "dynamodb" and deploy.profiles_table == "mapleguard-profiles"


# --- 3. The API intake endpoints ------------------------------------------------------
def _client(store, scrubber=None):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from api import create_app
    from api.model_config import NocModel
    noc = NocModel(matcher=None, corrector=None, configured=False, backend="fake",
                   model="fake", detail="no key")
    return TestClient(create_app(noc_model=noc, profile_store=store, letter_scrubber=scrubber))


def test_post_profiles_persists_and_is_retrievable():
    store = InMemoryProfileStore()
    client = _client(store)
    resp = client.post("/profiles", json={"profile": STRONG_PROFILE})
    assert resp.status_code == 200
    pid = resp.json()["id"]
    assert resp.json()["monitored"] is True
    # it is in the store the monitor lists, and fetchable by id
    assert [p.id for p in store.list_profiles()] == [pid]
    assert client.get("/profiles").json()["profiles"] == [{"id": pid}]
    assert client.get(f"/profiles/{pid}").json()["profile"] == STRONG_PROFILE


def test_post_profiles_honours_a_supplied_id_and_upserts():
    store = InMemoryProfileStore()
    client = _client(store)
    client.post("/profiles", json={"profile": STRONG_PROFILE, "id": "me"})
    client.post("/profiles", json={"profile": {**STRONG_PROFILE, "canadian_work_years": 5},
                                   "id": "me"})
    assert len(store.list_profiles()) == 1
    assert client.get("/profiles/me").json()["profile"]["canadian_work_years"] == 5


def test_post_profiles_rejects_a_malformed_profile_422():
    client = _client(InMemoryProfileStore())
    # Missing required education / first_language -> serde raises -> 422 (same path as /position).
    resp = client.post("/profiles", json={"profile": {"canadian_work_years": 1}})
    assert resp.status_code == 422


def test_get_unknown_profile_404():
    assert _client(InMemoryProfileStore()).get("/profiles/nope").status_code == 404


# --- 3b. Guardrails: reference letters are PII-scrubbed on write ----------------------
_LETTER_PII = "This confirms Jane Doe worked as a Web Developer, reachable at 555-123-4567."


class _FakeScrubber:
    """Stands in for a Bedrock Guardrail: redacts a known token so tests prove the write path
    routes letters through the scrubber before storing."""
    configured = True

    def scrub(self, text):
        from api.guardrail import ScrubResult
        redacted = text.replace("Jane Doe", "{NAME}").replace("555-123-4567", "{PHONE}")
        return ScrubResult(text=redacted, applied=True, intervened=redacted != text)


def test_post_profiles_scrubs_letter_pii_when_guardrail_configured():
    store = InMemoryProfileStore()
    client = _client(store, scrubber=_FakeScrubber())
    resp = client.post("/profiles", json={"profile": STRONG_PROFILE, "id": "p",
                                          "reference_letter": {"noc_code": "21234",
                                                               "letter_text": _LETTER_PII}})
    assert resp.status_code == 200 and resp.json()["pii_scrubbed"] is True
    stored = store.get("p").reference_letter["letter_text"]
    assert "Jane Doe" not in stored and "555-123-4567" not in stored
    assert "{NAME}" in stored and "{PHONE}" in stored


def test_put_letter_scrubs_pii_when_guardrail_configured():
    store = InMemoryProfileStore()
    client = _client(store, scrubber=_FakeScrubber())
    client.post("/profiles", json={"profile": STRONG_PROFILE, "id": "p"})
    resp = client.put("/profiles/p/letter", json={"noc_code": "21234", "letter_text": _LETTER_PII})
    assert resp.status_code == 200 and resp.json()["pii_scrubbed"] is True
    assert "Jane Doe" not in store.get("p").reference_letter["letter_text"]


def test_letter_stored_unscrubbed_is_flagged_not_faked_without_a_guardrail():
    # No guardrail configured -> the letter is stored as-is, but the response says so honestly.
    from api.guardrail import NoopScrubber
    store = InMemoryProfileStore()
    client = _client(store, scrubber=NoopScrubber())
    client.post("/profiles", json={"profile": STRONG_PROFILE, "id": "p"})
    resp = client.put("/profiles/p/letter", json={"noc_code": "21234", "letter_text": _LETTER_PII})
    assert resp.json()["pii_scrubbed"] is False
    assert store.get("p").reference_letter["letter_text"] == _LETTER_PII


# --- 4. THE LOOP: a profile saved via the API is watched by the monitor ----------------
def test_profile_saved_through_the_api_is_watched_by_the_monitor():
    # ONE store, written by the API and listed by the monitor.
    store = InMemoryProfileStore()
    client = _client(store)
    pid = client.post("/profiles", json={"profile": STRONG_PROFILE}).json()["id"]

    deps = MonitorDeps(fetch_rounds=lambda: FIXTURE.read_text(), source_url=SOURCE,
                       profiles=store, snapshots=InMemorySnapshotStore(),
                       sink=CollectingAlertSink())
    result = tick(deps, as_of="2026-08-25")
    # The monitor re-scored the just-saved profile against new draws and alerted it by id.
    assert result.new_draw_count > 0
    assert any(a.profile_id == pid for a in result.alerts)
