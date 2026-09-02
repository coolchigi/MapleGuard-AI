"""Tests for the deploy assembly of the autonomous monitor: DynamoDB/SNS stores + the Lambda
entrypoint. Fully offline — a fake DynamoDB table and a fake SNS client exercise every path, so
no boto3 and no network are needed. The live IRCC fetch is replaced by the sample fixture.
"""
import json
import pathlib

from agent.monitor import Alert, Snapshot, StoredProfile
from agent.monitor_lambda import build_monitor_deps, lambda_handler
from agent.stores_aws import DynamoDBProfileStore, DynamoDBSnapshotStore, SnsAlertSink

FIXTURE = pathlib.Path(__file__).parent.parent / "ingest" / "fixtures" / "ee_rounds_sample.json"
SOURCE = "https://www.canada.ca/rounds.json"

STRONG_PROFILE = {
    "education": "bachelors-or-three-year",
    "first_language": {"speaking": 10, "listening": 10, "reading": 10, "writing": 10},
    "date_of_birth": "1996-07-01", "canadian_work_years": 3,
    "first_language_test_date": "2025-09-30",
}


class FakeTable:
    """A minimal in-memory stand-in for a boto3 DynamoDB Table (get_item/put_item/scan)."""
    def __init__(self, items=None, pk="id"):
        self._pk = pk
        self._items = {i[pk]: dict(i) for i in (items or [])}

    def get_item(self, Key):
        key = Key[self._pk]
        item = self._items.get(key)
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item):
        self._items[Item[self._pk]] = dict(Item)
        return {}

    def scan(self, **kwargs):
        return {"Items": [dict(v) for v in self._items.values()]}


class FakeSns:
    def __init__(self):
        self.published = []

    def publish(self, **kwargs):
        self.published.append(kwargs)
        return {"MessageId": "fake"}


# --- DynamoDB snapshot store ----------------------------------------------------------
def test_snapshot_store_round_trips_through_dynamo_shape():
    table = FakeTable()
    store = DynamoDBSnapshotStore(table=table)
    assert store.load() == Snapshot()  # empty table -> fresh snapshot
    snap = Snapshot(latest_key=["2026-08-06", 340, ""], seen_round_numbers=("340", "341"))
    store.save(snap)
    # Stored as a single JSON 'data' attribute keyed by id='snapshot'.
    assert "data" in table.get_item(Key={"id": "snapshot"})["Item"]
    assert store.load() == snap


# --- DynamoDB profile store -----------------------------------------------------------
def test_profile_store_reads_json_records():
    table = FakeTable(items=[
        {"id": "p1", "data": json.dumps({"id": "p1", "profile": STRONG_PROFILE})},
        {"id": "p2", "data": json.dumps({"id": "p2", "profile": STRONG_PROFILE,
                                         "bc_offer": {"hourly_wage": 40}})},
    ])
    profiles = DynamoDBProfileStore(table=table).list_profiles()
    by_id = {p.id: p for p in profiles}
    assert set(by_id) == {"p1", "p2"}
    assert by_id["p1"].profile["education"] == "bachelors-or-three-year"
    assert by_id["p2"].bc_offer == {"hourly_wage": 40}


# --- SNS sink -------------------------------------------------------------------------
def test_sns_sink_publishes_the_alert_json():
    sns = FakeSns()
    sink = SnsAlertSink(topic_arn="arn:aws:sns:us-east-1:0:mapleguard", client=sns)
    alert = Alert(profile_id="p1", as_of="2026-08-25", new_draws=[{"name": "EE #340"}],
                  impact=[], reachable_alternatives=[], deadlines=None,
                  citations=["https://www.canada.ca/x"])
    sink.emit(alert)
    assert len(sns.published) == 1
    pub = sns.published[0]
    assert pub["TopicArn"].endswith("mapleguard")
    assert json.loads(pub["Message"])["profile_id"] == "p1"


def test_sns_sink_truncates_oversized_alert_under_the_limit():
    # A first tick diffs against an empty snapshot, so every current draw is "new"; the alert
    # must not serialize past SNS's 256 KB Message limit (real InvalidParameter seen in deploy).
    sns = FakeSns()
    sink = SnsAlertSink(topic_arn="arn:aws:sns:us-east-1:0:mg", client=sns)
    big = [{"name": f"EE #{i}", "cutoff": 400 + i, "blob": "x" * 800} for i in range(500)]
    sink.emit(Alert(profile_id="p1", as_of="2026-08-25", new_draws=big, impact=[],
                    reachable_alternatives=[], deadlines=None, citations=["https://x"]))
    assert len(sns.published) == 1
    msg = sns.published[0]["Message"]
    assert len(msg.encode("utf-8")) <= 256 * 1024
    body = json.loads(msg)
    assert body["profile_id"] == "p1"       # identity + citations survive truncation
    assert body["truncated"] is True
    assert body["new_draws_omitted"] == 500 - 25


def test_sns_sink_swallows_publish_errors():
    class Boom:
        def publish(self, **kwargs):
            raise RuntimeError("throttled")
    sink = SnsAlertSink(topic_arn="arn", client=Boom())
    # A publish failure must not kill the tick.
    sink.emit(Alert("p1", "2026-08-25", [], [], [], None, []))


# --- build_monitor_deps + lambda_handler end to end -----------------------------------
def test_build_monitor_deps_wires_injected_components():
    table = FakeTable(items=[{"id": "p1", "data": json.dumps({"id": "p1",
                                                              "profile": STRONG_PROFILE})}])
    deps = build_monitor_deps(
        env={"MAPLEGUARD_ROUNDS_URL": SOURCE},
        fetch_rounds=FIXTURE.read_text,
        profiles=DynamoDBProfileStore(table=table),
        snapshots=DynamoDBSnapshotStore(table=FakeTable()),
    )
    assert deps.source_url == SOURCE
    assert [p.id for p in deps.profiles.list_profiles()] == ["p1"]


def test_lambda_handler_runs_a_full_tick_offline():
    profile_table = FakeTable(items=[{"id": "p1", "data": json.dumps({"id": "p1",
                                                                     "profile": STRONG_PROFILE})}])
    snap_table = FakeTable()
    sns = FakeSns()
    deps = build_monitor_deps(
        env={"MAPLEGUARD_ROUNDS_URL": SOURCE},
        fetch_rounds=FIXTURE.read_text,
        profiles=DynamoDBProfileStore(table=profile_table),
        snapshots=DynamoDBSnapshotStore(table=snap_table),
        sink=SnsAlertSink(topic_arn="arn:aws:sns:us-east-1:0:mg", client=sns),
    )
    out = lambda_handler({"as_of": "2026-08-25"}, None, deps=deps)
    # First run: every fixture draw is new; the strong profile gets a cited alert, published.
    assert out["new_draws"] >= 1 and out["alerts"]
    assert out["alerts"][0]["profile_id"] == "p1" and out["alerts"][0]["citations"]
    assert len(sns.published) == len(out["alerts"])
    # The snapshot was persisted to (the fake) DynamoDB, so a re-run finds nothing new.
    assert "data" in snap_table.get_item(Key={"id": "snapshot"})["Item"]
    again = lambda_handler({"as_of": "2026-08-26"}, None, deps=deps)
    assert again["new_draws"] == 0 and again["alerts"] == []


def test_default_path_requires_table_env():
    import pytest
    with pytest.raises(RuntimeError, match="MAPLEGUARD_PROFILES_TABLE"):
        build_monitor_deps(env={}, fetch_rounds=lambda: "{}")
