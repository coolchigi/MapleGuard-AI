"""The autonomous monitoring loop (Feature 4 core) — the work MapleGuard does unasked.

This is the honest answer to "isn't compute-and-refuse just refusing to act?". No: the refusal
is only on the final button (submit an application, send on the user's behalf). The WORK — watch
the draws, re-score every stored profile the instant they change, and surface the cited impact —
runs autonomously, on a schedule, without anyone asking. That work is this module.

`tick()` is the entrypoint a scheduler calls. Each tick, deterministically and with no network of
its own:
  1. ingests the latest rounds document (fetched through an injected callable — the only I/O),
  2. diffs it against the last stored snapshot to find genuinely NEW draws (via the numeric-aware
     `ingest.sort_records` "latest draw" ordering, not a string sort),
  3. re-scores every stored profile against the current pool (`reachable_paths`) and reads its
     dated cliffs (`crs.deadlines`),
  4. for each profile a new draw actually affects, emits a CITED alert payload — what changed, the
     impact on that profile, the reachable alternatives, and the deadlines — every value carrying
     its source (draw provenance + the deterministic deadline computation),
  5. records the new snapshot.

Determinism below the model: the diff and the alert DECISION are pure Python, so the loop is
reliable and testable with no AWS and no model. The Strands agent's role, when attached, is to
NARRATE the finished deterministic payload (explain, never decide) — matching ARCHITECTURE.md,
where the policy-diff worker is a background worker, not a conversational agent.

Every backend is behind an interface: in-memory / file stores for dev (fully offline), and marked
DynamoDB / SES seams for deploy. The alert is PRODUCED and logged here; the actual send stays a
gated action (compute-and-refuse on the button), so no email leaves this module.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Callable, Optional, Protocol

from ingest import parse_rounds_json, sort_records
from ingest.models import DrawRecord

from .tools import compute_crs, crs_deadlines, ingest_draws, reachable_paths

logger = logging.getLogger("mapleguard.monitor")


# --------------------------------------------------------------------- data model
@dataclass(frozen=True)
class StoredProfile:
    """A monitored candidate: an id, the CRS profile dict (the same shape `crs.Profile`
    consumes, via serde), an optional BC job offer, and an optional stored reference letter so a
    NOC-type policy change can trigger a re-audit. `to_dict`/`from_dict` are the one serialization
    used by every profile store (file, DynamoDB), so the stored shape is identical across backends.

    `reference_letter` is `{"noc_code": str, "letter_text": str}`. PII CAVEAT: a reference letter
    contains personal data (names, employer, salary). It rides the same store as the profile (which
    is already PII) and is stored UNSCRUBBED — Bedrock Guardrails PII redaction is not provisioned
    yet (no Guardrails resource in infra/). This is flagged, not faked: scrub on write once
    Guardrails is stood up.
    """
    id: str
    profile: dict
    bc_offer: Optional[dict] = None
    reference_letter: Optional[dict] = None  # {"noc_code": str, "letter_text": str}

    def to_dict(self) -> dict:
        d = {"id": self.id, "profile": self.profile}
        if self.bc_offer is not None:
            d["bc_offer"] = self.bc_offer
        if self.reference_letter is not None:
            d["reference_letter"] = self.reference_letter
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "StoredProfile":
        return cls(id=data["id"], profile=data["profile"], bc_offer=data.get("bc_offer"),
                   reference_letter=data.get("reference_letter"))


@dataclass(frozen=True)
class Snapshot:
    """The last-seen state of the draw feed, so the next tick can find what is new. Stores the
    latest round's ordering key and every round id seen (robust against a re-published feed)."""
    latest_key: Optional[list] = None            # [date_iso, round_int, suffix] of the newest draw
    seen_round_numbers: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"latest_key": self.latest_key, "seen_round_numbers": list(self.seen_round_numbers)}

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "Snapshot":
        if not data:
            return cls()
        return cls(latest_key=data.get("latest_key"),
                   seen_round_numbers=tuple(data.get("seen_round_numbers", ())))


@dataclass(frozen=True)
class Alert:
    """A cited alert for one profile: what changed, its impact, alternatives, deadlines, and a
    ranked citation list (primary government source first). `summary` is optional agent-narrated
    prose; it never carries a decision the deterministic payload did not already make."""
    profile_id: str
    as_of: str
    new_draws: list[dict]
    impact: list[dict]
    reachable_alternatives: list[dict]
    deadlines: Optional[dict]
    citations: list[str]
    summary: str = ""
    # Policy-change fields, set only on a policy-change alert (a NOC/CRS-weight/... rule change),
    # None on a draw alert. `policy_change` is the validated change; `crs` is the deterministic
    # position with the before/after delta; `letter_gaps` are the re-audit gaps cited to the
    # (new) NOC/TEER duty text.
    policy_change: Optional[dict] = None
    crs: Optional[dict] = None
    letter_gaps: Optional[list[dict]] = None

    def to_dict(self) -> dict:
        out = {
            "profile_id": self.profile_id, "as_of": self.as_of, "new_draws": self.new_draws,
            "impact": self.impact, "reachable_alternatives": self.reachable_alternatives,
            "deadlines": self.deadlines, "citations": self.citations, "summary": self.summary,
        }
        if self.policy_change is not None:
            out["policy_change"] = self.policy_change
        if self.crs is not None:
            out["crs"] = self.crs
        if self.letter_gaps is not None:
            out["letter_gaps"] = self.letter_gaps
        return out


@dataclass(frozen=True)
class TickResult:
    ran_at: str
    new_draw_count: int
    alerts: list[Alert]
    snapshot: Snapshot


# ------------------------------------------------------------------- store interfaces
class SnapshotStore(Protocol):
    def load(self) -> Snapshot: ...
    def save(self, snapshot: Snapshot) -> None: ...


class ProfileStore(Protocol):
    def list_profiles(self) -> list[StoredProfile]: ...


class WritableProfileStore(ProfileStore, Protocol):
    """A profile store the intake path writes to. The monitor only needs `list_profiles`
    (read); the API's save-a-profile endpoint needs `put`/`get`. The file store (dev) and the
    DynamoDB store (deploy) both satisfy this, so a profile saved through the API is the same
    profile the monitor lists — one store, two readers/writers, no hand-seeded items."""
    def put(self, profile: StoredProfile) -> None: ...
    def get(self, profile_id: str) -> Optional[StoredProfile]: ...


class AlertSink(Protocol):
    def emit(self, alert: Alert) -> None: ...


# ----------------------------------------------------------------- dev implementations
class InMemorySnapshotStore:
    """A snapshot store in process memory. Dev/test default."""
    def __init__(self, snapshot: Optional[Snapshot] = None):
        self._snapshot = snapshot or Snapshot()

    def load(self) -> Snapshot:
        return self._snapshot

    def save(self, snapshot: Snapshot) -> None:
        self._snapshot = snapshot


class FileSnapshotStore:
    """A snapshot store backed by a local JSON file. Dev/demo persistence, no AWS."""
    def __init__(self, path: str):
        self._path = path

    def load(self) -> Snapshot:
        import os
        if not os.path.exists(self._path):
            return Snapshot()
        with open(self._path) as f:
            return Snapshot.from_dict(json.load(f))

    def save(self, snapshot: Snapshot) -> None:
        with open(self._path, "w") as f:
            json.dump(snapshot.to_dict(), f)


class InMemoryProfileStore:
    """The monitored profiles, in memory. Dev/test default (DynamoDB holds them in deploy).
    Writable: `put` upserts by id so a test can exercise the same save->list path the API uses."""
    def __init__(self, profiles: Optional[list[StoredProfile]] = None):
        self._profiles: dict[str, StoredProfile] = {p.id: p for p in (profiles or [])}

    def list_profiles(self) -> list[StoredProfile]:
        return list(self._profiles.values())

    def put(self, profile: StoredProfile) -> None:
        self._profiles[profile.id] = profile

    def get(self, profile_id: str) -> Optional[StoredProfile]:
        return self._profiles.get(profile_id)


class FileProfileStore:
    """The monitored profiles, one JSON file per id under a directory. Dev/demo persistence with
    no AWS, and the shared store for a locally-run API + a locally-run monitor: the API writes a
    profile here, the monitor reads the same directory. The stored shape is `StoredProfile.to_dict`,
    identical to the DynamoDB item's `data`, so swapping file->DynamoDB is config only."""
    def __init__(self, directory: str):
        self._dir = directory

    def _path(self, profile_id: str) -> str:
        import os
        # Keep the id filesystem-safe without losing round-trip fidelity (the id also lives in
        # the file body, which is the source of truth on read).
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in profile_id) or "_"
        return os.path.join(self._dir, f"{safe}.json")

    def _index(self) -> dict[str, str]:
        import os
        return {} if not os.path.isdir(self._dir) else {
            name: os.path.join(self._dir, name)
            # Skip dotfiles (e.g. macOS "._demo.json" AppleDouble sidecars on exFAT/network
            # volumes). They end in .json but are not profile documents.
            for name in os.listdir(self._dir) if name.endswith(".json") and not name.startswith(".")
        }

    def list_profiles(self) -> list[StoredProfile]:
        profiles = []
        for path in self._index().values():
            with open(path) as f:
                profiles.append(StoredProfile.from_dict(json.load(f)))
        return profiles

    def put(self, profile: StoredProfile) -> None:
        import os
        os.makedirs(self._dir, exist_ok=True)
        with open(self._path(profile.id), "w") as f:
            json.dump(profile.to_dict(), f)

    def get(self, profile_id: str) -> Optional[StoredProfile]:
        import os
        path = self._path(profile_id)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return StoredProfile.from_dict(json.load(f))


class CollectingAlertSink:
    """Produces and LOGS each alert, and keeps them for inspection. It does NOT send. Sending is
    the gated action (compute-and-refuse on the button); wiring an actual send is a deliberate,
    separate step. This is the dev/test sink and the honest default."""
    def __init__(self):
        self.alerts: list[Alert] = []

    def emit(self, alert: Alert) -> None:
        self.alerts.append(alert)
        logger.info("ALERT profile=%s new_draws=%d citations=%s", alert.profile_id,
                    len(alert.new_draws), alert.citations)


# --------------------------------------------------------------------- deps + the loop
@dataclass
class MonitorDeps:
    """Everything a tick needs, injected so the loop runs offline. `fetch_rounds` returns the raw
    rounds JSON text (the only I/O; inject a fixture reader in tests). `narrator`, if set, is a
    Strands agent that turns the finished deterministic alert into prose — it explains, it never
    decides."""
    fetch_rounds: Callable[[], str]
    profiles: ProfileStore
    snapshots: SnapshotStore
    sink: AlertSink
    source_url: Optional[str] = None
    narrator: Any = None
    horizon_within_reach: bool = True   # also alert when a new draw is one move away
    # Policy-change watch (optional; the loop only runs it when BOTH are wired):
    #   fetch_policy_update -> the raw IRCC update text (the only new I/O; inject a fixture in tests)
    #   classify_update     -> classify+validate that text -> a validated PolicyChange dict or None
    #                          (the model extracts, the validator drops bad output; see ingest.policy)
    #   policy_source_url   -> citation for the update
    #   matcher             -> a noc.DutyMatcher for the NOC re-audit (inject a fake offline)
    fetch_policy_update: Optional[Callable[[], str]] = None
    classify_update: Optional[Callable[[str], Optional[dict]]] = None
    policy_source_url: Optional[str] = None
    matcher: Any = None


def _record_key(rec: DrawRecord) -> list:
    """A JSON-safe ordering key for a record: [date_iso, round_int, suffix]. Matches the numeric
    ordering of `ingest.round_sort_key` so 'latest' is a real comparison, not a string sort."""
    from ingest import round_sort_key
    n, suffix = round_sort_key(rec.round_number)
    return [rec.date.isoformat(), n, suffix]


def _new_records(records: list[DrawRecord], snapshot: Snapshot) -> list[DrawRecord]:
    """Records newer than the snapshot: strictly greater ordering key AND an unseen round id, so
    neither a re-published feed nor a same-key duplicate re-alerts."""
    usable = [r for r in records if not r.needs_manual_check and r.cutoff is not None]
    seen = set(snapshot.seen_round_numbers)
    last = snapshot.latest_key
    fresh = []
    for r in usable:
        key = _record_key(r)
        if r.round_number in seen:
            continue
        if last is None or key > last:
            fresh.append(r)
    return sort_records(fresh, newest_first=True)


def _updated_snapshot(records: list[DrawRecord], snapshot: Snapshot) -> Snapshot:
    usable = [r for r in records if not r.needs_manual_check and r.cutoff is not None]
    if not usable:
        return snapshot
    latest = sort_records(usable, newest_first=True)[0]
    seen = set(snapshot.seen_round_numbers) | {r.round_number for r in usable}
    return Snapshot(latest_key=_record_key(latest), seen_round_numbers=tuple(sorted(seen)))


def _self_actionable(path: dict) -> bool:
    """A within-reach draw counts as a real near-miss only if the candidate can close it with a
    move OTHER than securing a provincial nomination. The +600 nomination lever closes almost
    any gap, so alerting on it would fire for everyone — noise. Relevance is computed, and
    silence is a feature (ARCHITECTURE.md), so the universal lever alone does not trigger."""
    return any("nomination" not in m["move"].lower() for m in path.get("closing_moves", []))


def _profile_alert(sp: StoredProfile, current_draws: list[dict], new_round_numbers: set[str],
                   as_of: Optional[str], want_within_reach: bool) -> Optional[Alert]:
    """Deterministic decision for one profile: does a NEW draw land in its reachable set (or a
    self-actionable near-miss)? If so, build the cited alert. Pure over the tool outputs."""
    reach = reachable_paths(sp.profile, current_draws, as_of=as_of, bc_offer=sp.bc_offer)
    all_options = list(reach["reachable"]) + list(reach["within_reach"])
    trigger_set = list(reach["reachable"])
    if want_within_reach:
        trigger_set += [p for p in reach["within_reach"] if _self_actionable(p)]

    impacted = [p for p in trigger_set
                if (p["draw"].get("provenance") or {}).get("round_number") in new_round_numbers
                or p["draw"]["name"] in new_round_numbers]
    if not impacted:
        return None

    # Deadlines are cited context (deterministic computation); only available with a birthdate.
    deadlines = None
    if sp.profile.get("date_of_birth"):
        deadlines = crs_deadlines(sp.profile, as_of=as_of)

    # Ranked citations: primary government source (the draw's provenance URL) first.
    citations: list[str] = []
    for p in impacted:
        prov = p["draw"].get("provenance") or {}
        src = prov.get("source_url") or p["draw"].get("source")
        if src and src not in citations:
            citations.append(src)

    return Alert(
        profile_id=sp.id,
        as_of=as_of or date.today().isoformat(),
        new_draws=[p["draw"] for p in impacted],
        impact=[{"draw": p["draw"]["name"], "round_number": (p["draw"].get("provenance") or {}).get("round_number"),
                 "your_score": p["your_score"], "cutoff": p["cutoff"], "clears": p["clears"],
                 "gap": p["gap"], "closing_moves": p.get("closing_moves", [])} for p in impacted],
        reachable_alternatives=all_options,
        deadlines=deadlines,
        citations=citations,
    )


def _policy_profile_alert(sp: StoredProfile, change: dict, as_of: str,
                          matcher: Any) -> Optional[Alert]:
    """Deterministic decision for one profile against a validated NOC-type policy change: if the
    change touches the profile's stored reference letter's NOC code, RE-AUDIT that letter against
    the current (new-TEER) occupation text and, if the change actually moves them (the re-audit now
    shows gaps or fails), build a cited alert carrying the deterministic CRS position and the gap
    list. Reuses the real audit path (`noc.audit_letter`); it does not reimplement scoring.

    Returns None when the profile is not moved: no stored letter, the letter's NOC code is not in
    the change's affected codes, or the re-audit still passes with no gaps (silence is a feature).
    """
    letter = sp.reference_letter or {}
    noc_code = letter.get("noc_code")
    letter_text = letter.get("letter_text")
    if not noc_code or not letter_text:
        return None
    if noc_code not in set(change.get("affected_noc_codes", [])):
        return None

    from noc import audit_letter, get_occupation
    try:
        occupation = get_occupation(noc_code)
    except (KeyError, ValueError):
        return None  # we do not hold this occupation's cited text; cannot audit -> do not guess
    report = audit_letter(letter_text, occupation, matcher).to_dict()
    duties = report.get("duties", {})
    gaps = duties.get("gaps", [])
    if duties.get("passed") and not gaps:
        return None  # the reclassification did not create a gap for this profile -> no alert

    # Deterministic CRS position from the core. A NOC reclassification does not change CRS POINTS
    # (it changes eligibility / the reference-letter bar), so before == after and the delta is 0 —
    # the honest number; the letter gaps are this change's real impact.
    crs = None
    total = compute_crs(sp.profile, as_of=as_of).get("total")
    if total is not None:
        crs = {"before": total, "after": total, "delta": 0,
               "note": ("a NOC reclassification does not change CRS points; it changes the "
                        "reference-letter bar — see letter_gaps")}

    # Citations: the change source, then each gap's NOC/TEER text source.
    citations = [change.get("source")] if change.get("source") else []
    for g in gaps:
        src = g.get("source")
        if src and src not in citations:
            citations.append(src)

    return Alert(
        profile_id=sp.id, as_of=as_of,
        new_draws=[], impact=[], reachable_alternatives=[],
        deadlines=(crs_deadlines(sp.profile, as_of=as_of) if sp.profile.get("date_of_birth") else None),
        citations=citations,
        policy_change=change, crs=crs, letter_gaps=gaps,
    )


def tick(deps: MonitorDeps, as_of: Optional[str] = None) -> TickResult:
    """Run one monitoring cycle. Deterministic apart from `deps.fetch_rounds` (the feed read).

    Ingests the latest draws, finds what is new versus the stored snapshot, re-scores every
    profile, emits a cited alert for each profile a new draw affects, and saves the snapshot.
    Returns a `TickResult`. Sends nothing — alerts go to the sink, which logs (dev) or would
    hand off to a gated send (deploy).
    """
    ran_at = as_of or date.today().isoformat()
    raw = deps.fetch_rounds()

    kwargs = {"source_url": deps.source_url} if deps.source_url else {}
    records = parse_rounds_json(raw, **kwargs)
    snapshot = deps.snapshots.load()
    new_records = _new_records(records, snapshot)

    alerts: list[Alert] = []
    if new_records:
        current = ingest_draws(raw, source_url=deps.source_url)["draws"]
        new_round_numbers = {r.round_number for r in new_records} | {r.name for r in new_records}
        for sp in deps.profiles.list_profiles():
            alert = _profile_alert(sp, current, new_round_numbers, ran_at,
                                   deps.horizon_within_reach)
            if alert is None:
                continue
            if deps.narrator is not None:
                alert = replace(alert, summary=_narrate(deps.narrator, alert))
            deps.sink.emit(alert)
            alerts.append(alert)

    # Policy-change routing: the OTHER watch. When an update fetcher + classifier are wired, classify
    # the latest IRCC update (model extracts, validator drops bad output), and for a validated NOC
    # change re-audit each affected profile's stored letter. Relevance still applies (only profiles
    # the change actually moves). Independent of the draw delta above.
    if deps.fetch_policy_update is not None and deps.classify_update is not None:
        change = deps.classify_update(deps.fetch_policy_update())  # validated dict or None (dropped)
        if change and change.get("change_type") == "noc":
            for sp in deps.profiles.list_profiles():
                pa = _policy_profile_alert(sp, change, ran_at, deps.matcher)
                if pa is None:
                    continue
                if deps.narrator is not None:
                    pa = replace(pa, summary=_narrate(deps.narrator, pa))
                deps.sink.emit(pa)
                alerts.append(pa)

    new_snapshot = _updated_snapshot(records, snapshot)
    deps.snapshots.save(new_snapshot)
    return TickResult(ran_at=ran_at, new_draw_count=len(new_records), alerts=alerts,
                      snapshot=new_snapshot)


def _narrate(agent: Any, alert: Alert) -> str:
    """Have the Strands agent explain a finished alert in plain language. The agent receives the
    deterministic payload and only phrases it — it makes no new claim and no eligibility verdict.
    Any failure degrades to an empty summary; the cited payload stands on its own."""
    prompt = (
        "Summarize this MapleGuard monitoring alert for the candidate in two or three plain "
        "sentences. Use only the facts and citations in the payload. Do not assert eligibility "
        "and do not invent numbers.\n\n" + json.dumps(alert.to_dict(), default=str)
    )
    try:
        return str(agent(prompt).message)
    except Exception as exc:  # pragma: no cover - narration is best-effort
        logger.warning("narration failed, using cited payload only: %s", exc)
        return ""


# ------------------------------------------------------------------ scheduler entrypoint
def scheduled_handler(event: Optional[dict] = None, context: Any = None,
                      deps: Optional[MonitorDeps] = None) -> dict:
    """The cron/EventBridge entrypoint. An Amazon EventBridge Scheduler rule (or any cron)
    invokes this on a fixed cadence with no prompt — that unprompted, scheduled invocation is the
    autonomy. `deps` is injected in tests; in deploy it is assembled from the configured backends
    (DynamoDB snapshot + profile stores, SES-gated sink) by the hosting layer.

    Returns a JSON-safe summary of the tick (alert count + snapshot), suitable as a Lambda /
    AgentCore return value.
    """
    if deps is None:  # pragma: no cover - deploy path, assembled by the host with live backends
        raise RuntimeError("scheduled_handler needs deps; the deploy host assembles them from "
                           "the configured stores. Inject MonitorDeps to run.")
    as_of = (event or {}).get("as_of") if isinstance(event, dict) else None
    result = tick(deps, as_of=as_of)
    return {"ran_at": result.ran_at, "new_draws": result.new_draw_count,
            "alerts": [a.to_dict() for a in result.alerts], "snapshot": result.snapshot.to_dict()}
