"""Tests for the autonomous monitoring loop (agent/monitor.py).

The loop is the autonomy the product shows: unprompted, it ingests draws, diffs against the
last snapshot, re-scores every profile, and emits a cited alert for those a new draw affects.
These tests exercise the whole cycle with fixture draws and sample profiles — no network, no
model, no AWS. The diff and the alert decision are deterministic, so they are asserted exactly.

Run:  cd agents-for-humans/mapleguard && PYTHONPATH=. python3 -m pytest -q
"""
import json
import pathlib

import pytest

from agent.monitor import (Alert, CollectingAlertSink, FileSnapshotStore, InMemoryProfileStore,
                           InMemorySnapshotStore, MonitorDeps, Snapshot, StoredProfile,
                           scheduled_handler, tick)

FIXTURE = pathlib.Path(__file__).parent.parent / "ingest" / "fixtures" / "ee_rounds_sample.json"
SOURCE = "https://www.canada.ca/rounds.json"

STRONG_PROFILE = {  # clears the top general cutoffs; a new general draw is actionable
    "education": "bachelors-or-three-year",
    "first_language": {"speaking": 10, "listening": 10, "reading": 10, "writing": 10},
    "date_of_birth": "1996-07-01", "canadian_work_years": 3,
    "first_language_test_date": "2025-09-30",
}
WEAK_PROFILE = {  # far below every cutoff and no single move closes it -> not actionable
    "education": "secondary",
    "first_language": {"speaking": 5, "listening": 5, "reading": 5, "writing": 5},
    "age": 44,
}


def _deps(profiles, snapshots=None, sink=None, doc=None, narrator=None):
    return MonitorDeps(
        fetch_rounds=lambda: doc if doc is not None else FIXTURE.read_text(),
        profiles=InMemoryProfileStore(profiles),
        snapshots=snapshots or InMemorySnapshotStore(),
        sink=sink or CollectingAlertSink(),
        source_url=SOURCE,
        narrator=narrator,
    )


# --- The cycle ------------------------------------------------------------------------
def test_first_tick_finds_all_draws_new_and_alerts_an_affected_profile():
    sink = CollectingAlertSink()
    deps = _deps([StoredProfile("p1", STRONG_PROFILE)], sink=sink)
    result = tick(deps, as_of="2026-08-25")
    assert result.new_draw_count > 0
    assert len(result.alerts) == 1 and result.alerts[0].profile_id == "p1"
    assert sink.alerts == result.alerts  # the sink received (and logged) exactly these


def test_second_tick_on_same_feed_is_idempotent_no_new_draws():
    snaps = InMemorySnapshotStore()
    deps = _deps([StoredProfile("p1", STRONG_PROFILE)], snapshots=snaps)
    tick(deps, as_of="2026-08-25")
    again = tick(deps, as_of="2026-08-26")   # snapshot now current
    assert again.new_draw_count == 0 and again.alerts == []


def test_alert_carries_cited_provenance_and_deadlines():
    result = tick(_deps([StoredProfile("p1", STRONG_PROFILE)]), as_of="2026-08-25")
    alert = result.alerts[0]
    # Every impacted draw's cutoff is cited to a primary government source.
    assert alert.citations and all(c.startswith("https://www.canada.ca") for c in alert.citations)
    for row in alert.impact:
        assert row["round_number"] and "your_score" in row and "cutoff" in row
    # Deadlines are included as cited context (profile has a birthdate + test date).
    assert alert.deadlines is not None and alert.deadlines["test_expiry"] == "2027-09-30"


def test_a_profile_no_new_draw_can_act_on_gets_no_alert():
    result = tick(_deps([StoredProfile("weak", WEAK_PROFILE)]), as_of="2026-08-25")
    assert result.alerts == []  # relevance is computed; silence when nothing is actionable


def test_only_genuinely_new_draws_trigger_after_a_prior_snapshot():
    # Seed the snapshot as if every fixture round was already seen, then add one newer round.
    base = json.loads(FIXTURE.read_text())
    seen_first = tick(_deps([StoredProfile("p1", STRONG_PROFILE)],
                            snapshots=(s := InMemorySnapshotStore())), as_of="2026-08-25")
    assert seen_first.new_draw_count > 0
    # Append a brand-new, higher round to the same feed.
    base["rounds"].insert(0, {
        "drawNumber": "999", "drawDate": "2026-09-05", "drawName": "General",
        "drawCRS": "400", "drawSize": "5,000",
    })
    deps2 = _deps([StoredProfile("p1", STRONG_PROFILE)], snapshots=s, doc=json.dumps(base))
    second = tick(deps2, as_of="2026-08-26")
    assert second.new_draw_count == 1  # only round 999 is new
    assert second.alerts and second.alerts[0].new_draws[0]["provenance"]["round_number"] == "999"


# --- Persistence + the send posture ---------------------------------------------------
def test_file_snapshot_store_persists_across_ticks(tmp_path):
    path = str(tmp_path / "snap.json")
    deps = _deps([StoredProfile("p1", STRONG_PROFILE)], snapshots=FileSnapshotStore(path))
    tick(deps, as_of="2026-08-25")
    # A fresh store reading the same file sees the saved snapshot -> no re-alert.
    deps2 = _deps([StoredProfile("p1", STRONG_PROFILE)], snapshots=FileSnapshotStore(path))
    assert tick(deps2, as_of="2026-08-26").new_draw_count == 0


def test_sink_produces_and_logs_but_never_sends():
    # CollectingAlertSink is the honest default: it has no send path, only collect + log.
    sink = CollectingAlertSink()
    assert not hasattr(sink, "send")
    tick(_deps([StoredProfile("p1", STRONG_PROFILE)], sink=sink), as_of="2026-08-25")
    assert sink.alerts and isinstance(sink.alerts[0], Alert)


# --- Scheduler entrypoint -------------------------------------------------------------
def test_scheduled_handler_runs_a_tick_and_returns_json_safe_summary():
    deps = _deps([StoredProfile("p1", STRONG_PROFILE)])
    out = scheduled_handler({"as_of": "2026-08-25"}, None, deps=deps)
    assert out["new_draws"] > 0 and out["ran_at"] == "2026-08-25"
    json.dumps(out)  # must be JSON-serializable for a Lambda / AgentCore return


def test_scheduled_handler_without_deps_refuses_rather_than_guessing():
    with pytest.raises(RuntimeError, match="needs deps"):
        scheduled_handler({}, None)


# --- Agent narration (optional; the agent explains, never decides) --------------------
def test_narrator_summary_is_attached_without_changing_the_decision():
    class _FakeAgent:
        def __call__(self, prompt):
            class R:
                message = "A new general draw landed that you clear. See the cited impact."
            return R()

    deps = _deps([StoredProfile("p1", STRONG_PROFILE)], narrator=_FakeAgent())
    result = tick(deps, as_of="2026-08-25")
    assert result.alerts[0].summary.startswith("A new general draw")
    # Narration adds prose only; the cited payload is unchanged.
    assert result.alerts[0].citations


# --- Eligibility-driven relevance + deadline trigger + the per-user ledger -------------
from agent.monitor import InMemoryAlertLedger, FileAlertLedger, MonitorDeps  # noqa: E402

# A registered nurse (NOC 31301 is on the 2026 healthcare list) with a low score: in-category for
# healthcare but far below its cutoff. Their category's bar moving is still relevant to them.
HEALTHCARE_LOW = {
    "education": "secondary",
    "first_language": {"speaking": 6, "listening": 6, "reading": 6, "writing": 6},
    "date_of_birth": "1990-07-01", "canadian_work_years": 0, "noc_code": "31301",
}


def test_category_draw_alerts_an_in_category_profile_even_below_cutoff():
    result = tick(_deps([StoredProfile("nurse", HEALTHCARE_LOW)]), as_of="2026-09-07")
    draw_alerts = [a for a in result.alerts if a.kind == "draw"]
    assert draw_alerts, "an in-category profile should be alerted when its category draws"
    impacts = [i for a in draw_alerts for i in a.impact]
    healthcare = [i for i in impacts if i.get("category") == "healthcare"]
    assert healthcare, "the healthcare draw should be surfaced to a healthcare-NOC profile"
    assert all(i["eligible"] is True for i in healthcare)
    assert any(i["clears"] is False for i in healthcare)  # below cutoff, still surfaced


def test_ineligible_profile_is_not_alerted_on_a_category_draw():
    # No NOC, no French, weak score: not in any category and cannot reach general -> silence.
    result = tick(_deps([StoredProfile("weak", WEAK_PROFILE)]), as_of="2026-09-07")
    assert [a for a in result.alerts if a.kind == "draw"] == []


# A profile whose language test expires within the 60-day horizon, with no category eligibility so
# only the deadline alert fires. Test date 2024-10-01 -> expiry 2026-10-01, ~24 days after as_of.
EXPIRING_SOON = {
    "education": "secondary",
    "first_language": {"speaking": 6, "listening": 6, "reading": 6, "writing": 6},
    "date_of_birth": "1996-07-01", "first_language_test_date": "2024-10-01",
}


def _deps_with_ledger(profiles, ledger):
    return MonitorDeps(fetch_rounds=lambda: FIXTURE.read_text(),
                       profiles=InMemoryProfileStore(profiles),
                       snapshots=InMemorySnapshotStore(), sink=CollectingAlertSink(),
                       source_url=SOURCE, ledger=ledger)


def test_deadline_alert_fires_within_horizon_and_dedups_across_ticks():
    ledger = InMemoryAlertLedger()
    deps = _deps_with_ledger([StoredProfile("p", EXPIRING_SOON)], ledger)
    first = tick(deps, as_of="2026-09-07")
    deadline = [a for a in first.alerts if a.kind == "deadline"]
    assert len(deadline) == 1
    assert deadline[0].impact[0]["deadline_kind"] == "test_expiry"
    assert deadline[0].impact[0]["crs_delta"] < 0 and deadline[0].impact[0]["days_away"] <= 60
    # A second tick on the same feed and date must NOT re-send the deadline alert (ledger dedup).
    second = tick(deps, as_of="2026-09-07")
    assert [a for a in second.alerts if a.kind == "deadline"] == []
    # The feed shows exactly one deadline notification for this user.
    feed = ledger.list_for("p")
    assert sum(1 for a in feed if a["kind"] == "deadline") == 1


def test_alert_ledger_records_once_and_feeds_newest_first(tmp_path):
    for ledger in (InMemoryAlertLedger(), FileAlertLedger(str(tmp_path))):
        assert ledger.record("u", "e1", {"event_id": "e1", "as_of": "2026-09-01"}) is True
        assert ledger.record("u", "e1", {"event_id": "e1", "as_of": "2026-09-01"}) is False  # dup
        assert ledger.record("u", "e2", {"event_id": "e2", "as_of": "2026-09-05"}) is True
        feed = ledger.list_for("u")
        assert [a["event_id"] for a in feed] == ["e2", "e1"]  # newest first
        assert ledger.list_for("someone-else") == []
