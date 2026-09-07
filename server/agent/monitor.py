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
    # `kind` labels the notification for the user's feed; `event_id` is its STABLE identity, so the
    # per-profile ledger records each distinct event once and never re-sends it (see AlertLedger).
    kind: str = "draw"                   # "draw" | "deadline" | "policy"
    event_id: str = ""
    # Policy-change fields, set only on a policy-change alert (a NOC/CRS-weight/... rule change),
    # None on a draw alert. `policy_change` is the validated change; `crs` is the deterministic
    # position with the before/after delta; `letter_gaps` are the re-audit gaps cited to the
    # (new) NOC/TEER duty text.
    policy_change: Optional[dict] = None
    crs: Optional[dict] = None
    letter_gaps: Optional[list[dict]] = None

    def to_dict(self) -> dict:
        out = {
            "profile_id": self.profile_id, "as_of": self.as_of, "kind": self.kind,
            "event_id": self.event_id, "new_draws": self.new_draws,
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


class AlertLedger(Protocol):
    """The per-user notification store and the dedup memory in one.

    `record` writes an alert under (profile_id, event_id) and returns True only when that event is
    NEW for that profile, so a caller emits a notification once and never again on later ticks (the
    deadline trigger runs every tick, so this is what stops it re-sending). `list_for` is the
    dashboard's notification feed for one profile, newest first. Per-user by construction, so it
    scales with users (unlike stuffing alert history into the single global snapshot item)."""
    def record(self, profile_id: str, event_id: str, alert: dict) -> bool: ...
    def list_for(self, profile_id: str) -> list[dict]: ...


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


class InMemoryAlertLedger:
    """Per-user notification store + dedup, in memory. Dev/test default (DynamoDB in deploy)."""
    def __init__(self):
        self._by_profile: dict[str, list[dict]] = {}
        self._seen: dict[str, set[str]] = {}

    def record(self, profile_id: str, event_id: str, alert: dict) -> bool:
        seen = self._seen.setdefault(profile_id, set())
        if event_id in seen:
            return False
        seen.add(event_id)
        self._by_profile.setdefault(profile_id, []).append(alert)
        return True

    def list_for(self, profile_id: str) -> list[dict]:
        # Newest first: alerts carry `as_of`; ties keep insertion order.
        return sorted(self._by_profile.get(profile_id, []),
                      key=lambda a: a.get("as_of", ""), reverse=True)


class FileAlertLedger:
    """Per-user notification store backed by one JSON file per profile. Dev/demo persistence, no
    AWS, same dedup contract as the DynamoDB ledger so the deploy swap is config only."""
    def __init__(self, directory: str):
        self._dir = directory

    def _path(self, profile_id: str) -> str:
        import os
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in profile_id) or "_"
        return os.path.join(self._dir, f"{safe}.json")

    def _load(self, profile_id: str) -> list[dict]:
        import os
        path = self._path(profile_id)
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return json.load(f)

    def record(self, profile_id: str, event_id: str, alert: dict) -> bool:
        import os
        existing = self._load(profile_id)
        if any(a.get("event_id") == event_id for a in existing):
            return False
        existing.append(alert)
        os.makedirs(self._dir, exist_ok=True)
        with open(self._path(profile_id), "w") as f:
            json.dump(existing, f)
        return True

    def list_for(self, profile_id: str) -> list[dict]:
        return sorted(self._load(profile_id), key=lambda a: a.get("as_of", ""), reverse=True)


class CollectingAlertSink:
    """Produces and LOGS each alert, and keeps them for inspection. It does NOT send. Sending is
    the gated action (compute-and-refuse on the button); wiring an actual send is a deliberate,
    separate step. This is the dev/test sink and the honest default."""
    def __init__(self):
        self.alerts: list[Alert] = []

    def emit(self, alert: Alert) -> None:
        self.alerts.append(alert)
        logger.info("ALERT profile=%s kind=%s event=%s citations=%s", alert.profile_id,
                    alert.kind, alert.event_id, alert.citations)


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
    # The per-user notification store + dedup memory. When set, every alert is recorded once per
    # (profile, event_id) and only a NEWLY recorded alert is emitted, so the deadline trigger (which
    # runs every tick) never re-sends. When None, dedup falls back to the draw-snapshot only.
    ledger: Optional[Any] = None
    deadline_horizon_days: int = 60     # alert on a dated cliff this many days out (test expiry, age)
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
    """Deterministic decision for one profile: which NEW draws are RELEVANT to this candidate?

    Relevance is nuanced so it is useful without being noise:
      - General draws (everyone is in the pool): score-based, reachable now or a self-actionable
        near-miss, the same bar as before.
      - Category / BC PNP draws: ELIGIBILITY-based. A new draw in a category the candidate is in
        (or a PNP they can register for) is surfaced even when they cannot clear it yet, because
        their category's bar moving is exactly the signal they asked for. Ineligible or
        eligibility-unknown draws are not surfaced (silence is a feature).
    Builds one cited alert over the relevant new draws. Pure over the tool outputs."""
    reach = reachable_paths(sp.profile, current_draws, as_of=as_of, bc_offer=sp.bc_offer)
    all_options = list(reach["reachable"]) + list(reach["within_reach"])

    impacted: list[dict] = []
    # General draws: score-based relevance (reachable, or a self-actionable near-miss).
    impacted += [p for p in reach["reachable"] if p["draw"].get("kind") == "general"]
    if want_within_reach:
        impacted += [p for p in reach["within_reach"]
                     if p["draw"].get("kind") == "general" and _self_actionable(p)]
    # Category / PNP draws: eligibility-based relevance (in-category / registrable), reach or not.
    for bucket in ("reachable", "within_reach", "blocked"):
        impacted += [p for p in reach[bucket]
                     if p["draw"].get("kind") != "general" and p.get("eligible") is True]

    # Keep only genuinely NEW draws, deduped by round number.
    def _round(p) -> str:
        return str((p["draw"].get("provenance") or {}).get("round_number") or p["draw"]["name"])

    relevant: list[dict] = []
    seen_rounds: set = set()
    for p in impacted:
        rn = _round(p)
        is_new = ((p["draw"].get("provenance") or {}).get("round_number") in new_round_numbers
                  or p["draw"]["name"] in new_round_numbers)
        if not is_new or rn in seen_rounds:
            continue
        seen_rounds.add(rn)
        relevant.append(p)
    if not relevant:
        return None

    # Deadlines are cited context (deterministic computation); only available with a birthdate.
    deadlines = crs_deadlines(sp.profile, as_of=as_of) if sp.profile.get("date_of_birth") else None

    # Ranked citations: primary government source (the draw's provenance URL) first.
    citations: list[str] = []
    for p in relevant:
        prov = p["draw"].get("provenance") or {}
        src = prov.get("source_url") or p["draw"].get("source")
        if src and src not in citations:
            citations.append(src)

    from ingest.categories import resolve_category

    def _impact(p: dict) -> dict:
        d = p["draw"]
        # The CANONICAL pathway slug (the eligibility engine's vocabulary), so the feed and the
        # relevance filter speak the same language. Falls back to the draw's own category/kind.
        pathway = resolve_category(d.get("category") or d.get("name")) or d.get("category") or d.get("kind")
        return {"draw": d["name"],
                "round_number": (d.get("provenance") or {}).get("round_number"),
                "category": pathway, "eligible": p.get("eligible"),
                "eligibility_reason": p.get("eligibility_reason"),
                "your_score": p["your_score"], "cutoff": p["cutoff"], "clears": p["clears"],
                "gap": p["gap"], "closing_moves": p.get("closing_moves", [])}

    return Alert(
        profile_id=sp.id,
        as_of=as_of or date.today().isoformat(),
        kind="draw",
        event_id="draw:" + "+".join(sorted(_round(p) for p in relevant)),
        new_draws=[p["draw"] for p in relevant],
        impact=[_impact(p) for p in relevant],
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
        kind="policy",
        event_id=f"policy:{change.get('change_type')}:{noc_code}:{change.get('effective_date') or ''}",
        new_draws=[], impact=[], reachable_alternatives=[],
        deadlines=(crs_deadlines(sp.profile, as_of=as_of) if sp.profile.get("date_of_birth") else None),
        citations=citations,
        policy_change=change, crs=crs, letter_gaps=gaps,
    )


def _deadline_alerts(sp: StoredProfile, as_of: str, horizon_days: int) -> list[Alert]:
    """Time-based alerts, independent of any draw: the dated cliffs from `crs.deadlines` that fall
    within `horizon_days` of `as_of`. The language-test expiry (in-pool language points drop to
    zero) and the NEXT age-bracket cliff (age points drop on a birthday) are the two modeled today.
    Each is a distinct, cited event, and its stable event_id lets the per-user ledger send it once.

    Needs a date_of_birth (age cliffs) or a test date (expiry); returns [] when neither is near.
    """
    if not sp.profile.get("date_of_birth"):
        return []
    from datetime import date as _date, timedelta
    today = _date.fromisoformat(as_of) if as_of else _date.today()
    horizon = today + timedelta(days=horizon_days)
    dl = crs_deadlines(sp.profile, as_of=as_of)

    cliffs: list[dict] = []
    if dl.get("test_expiry_cliff"):
        cliffs.append(dl["test_expiry_cliff"])
    # Only the NEXT age cliff matters for a near-term alert (the rest are years out).
    upcoming_age = [c for c in dl.get("age_cliffs", []) if c.get("date")]
    if upcoming_age:
        cliffs.append(min(upcoming_age, key=lambda c: c["date"]))

    alerts: list[Alert] = []
    for c in cliffs:
        cdate = c.get("date")
        if not cdate:
            continue
        try:
            when = _date.fromisoformat(cdate)
        except (ValueError, TypeError):
            continue
        if not (today <= when <= horizon):
            continue  # outside the horizon; silence until it approaches
        days = (when - today).days
        alerts.append(Alert(
            profile_id=sp.id, as_of=as_of,
            kind="deadline",
            event_id=f"deadline:{c.get('kind')}:{cdate}",
            new_draws=[], impact=[{
                "deadline_kind": c.get("kind"), "date": cdate, "label": c.get("label"),
                "days_away": days, "crs_delta": c.get("delta"),
            }],
            reachable_alternatives=[],
            deadlines=dl,
            citations=[],  # deterministic computation from the candidate's own dated inputs
        ))
    return alerts


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

    def _emit(alert: Optional[Alert]) -> None:
        """Narrate (if a narrator is wired), dedup through the per-user ledger, then send. A ledger
        that reports the event already recorded for this profile means we do NOT re-send it, which is
        what keeps the every-tick deadline trigger from repeating."""
        if alert is None:
            return
        if deps.narrator is not None:
            alert = replace(alert, summary=_narrate(deps.narrator, alert))
        if deps.ledger is not None and not deps.ledger.record(
                alert.profile_id, alert.event_id, alert.to_dict()):
            return
        deps.sink.emit(alert)
        alerts.append(alert)

    profiles = deps.profiles.list_profiles()

    # 1. Draw alerts: only when the feed produced genuinely new draws.
    if new_records:
        current = ingest_draws(raw, source_url=deps.source_url)["draws"]
        new_round_numbers = {r.round_number for r in new_records} | {r.name for r in new_records}
        for sp in profiles:
            _emit(_profile_alert(sp, current, new_round_numbers, ran_at, deps.horizon_within_reach))

    # 2. Deadline alerts: time-based, every tick, independent of draws. The ledger dedup ensures
    # each dated cliff (test expiry, next age cliff) within the horizon is sent once, not every tick.
    for sp in profiles:
        for da in _deadline_alerts(sp, ran_at, deps.deadline_horizon_days):
            _emit(da)

    # 3. Policy-change routing: the OTHER watch. When an update fetcher + classifier are wired,
    # classify the latest IRCC update (model extracts, validator drops bad output), and for a
    # validated NOC change re-audit each affected profile's stored letter. Relevance still applies
    # (only profiles the change actually moves). Independent of the draw delta above.
    if deps.fetch_policy_update is not None and deps.classify_update is not None:
        change = deps.classify_update(deps.fetch_policy_update())  # validated dict or None (dropped)
        if change and change.get("change_type") == "noc":
            for sp in profiles:
                _emit(_policy_profile_alert(sp, change, ran_at, deps.matcher))

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
