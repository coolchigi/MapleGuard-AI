"""AWS-backed stores for the autonomous monitor (the deploy side of monitor.py's seams).

`monitor.py` defines the store Protocols (SnapshotStore, ProfileStore, AlertSink) and ships
in-memory / file implementations for dev. These are the DynamoDB + SNS implementations for
deploy, so the scheduled Lambda persists the snapshot, reads the monitored profiles, and emits
alerts with no code change to the loop.

Each record is stored as a single JSON-string attribute (`data`), which sidesteps DynamoDB's
number/empty-string type quirks and keeps the stored shape identical to the dev file store's.
`boto3` is imported lazily and the table/client is injectable, so these classes import and TEST
with no boto3 and no AWS: a fake table object exercises every path offline.

Posture note (unchanged): the SNS sink PUBLISHES a user-facing status alert about the user's own
position. That is the alerting feature, not a government submission — the compute-and-refuse
refusal is only on filing an application. The Lambda still defaults to the logging sink unless a
topic ARN is configured, so nothing is sent unless the operator opts in.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .monitor import Alert, Snapshot, StoredProfile

logger = logging.getLogger("mapleguard.monitor.aws")

_SNAPSHOT_PK = "snapshot"


def _dynamo_table(table_name: str, region: Optional[str], table: Any):
    """The injected table, or a real boto3 DynamoDB Table (lazy import)."""
    if table is not None:
        return table
    import boto3
    kwargs = {"region_name": region} if region else {}
    return boto3.resource("dynamodb", **kwargs).Table(table_name)


class DynamoDBSnapshotStore:
    """The last-seen feed snapshot, in one DynamoDB item keyed by a fixed partition id.

    Table schema: partition key `id` (S). One item, `id="snapshot"`, attribute `data` = the
    JSON of `Snapshot.to_dict()`. Inject `table` (a boto3 Table or a fake) to test offline.
    """
    def __init__(self, table_name: str = "", region: Optional[str] = None,
                 table: Any = None, pk_name: str = "id"):
        self._table = _dynamo_table(table_name, region, table)
        self._pk = pk_name

    def load(self) -> Snapshot:
        resp = self._table.get_item(Key={self._pk: _SNAPSHOT_PK})
        item = resp.get("Item") if isinstance(resp, dict) else None
        if not item or "data" not in item:
            return Snapshot()
        return Snapshot.from_dict(json.loads(item["data"]))

    def save(self, snapshot: Snapshot) -> None:
        self._table.put_item(Item={self._pk: _SNAPSHOT_PK,
                                   "data": json.dumps(snapshot.to_dict())})


class DynamoDBProfileStore:
    """The monitored candidate profiles, one DynamoDB item each.

    Table schema: partition key `id` (S), attribute `data` = JSON of
    {"id", "profile", "bc_offer"?} (`StoredProfile.to_dict`). Reads via a paginated scan (the
    monitored set is small); `put` upserts one item — the same shape the file store writes, so
    the API's save-a-profile path and the monitor's list path share one store. Inject `table`
    to test offline.
    """
    def __init__(self, table_name: str = "", region: Optional[str] = None,
                 table: Any = None, pk_name: str = "id"):
        self._table = _dynamo_table(table_name, region, table)
        self._pk = pk_name

    def list_profiles(self) -> list[StoredProfile]:
        profiles: list[StoredProfile] = []
        kwargs: dict[str, Any] = {}
        while True:
            resp = self._table.scan(**kwargs)
            for item in resp.get("Items", []):
                profiles.append(self._to_profile(item))
            token = resp.get("LastEvaluatedKey")
            if not token:
                break
            kwargs["ExclusiveStartKey"] = token
        return profiles

    def put(self, profile: StoredProfile) -> None:
        self._table.put_item(Item={self._pk: profile.id,
                                   "data": json.dumps(profile.to_dict())})

    def get(self, profile_id: str) -> Optional[StoredProfile]:
        resp = self._table.get_item(Key={self._pk: profile_id})
        item = resp.get("Item") if isinstance(resp, dict) else None
        return self._to_profile(item) if item else None

    def _to_profile(self, item: dict) -> StoredProfile:
        if "data" in item:
            rec = json.loads(item["data"])
            rec.setdefault("id", item.get(self._pk, ""))
            return StoredProfile.from_dict(rec)
        return StoredProfile(id=item.get(self._pk, ""), profile=item["profile"],
                             bc_offer=item.get("bc_offer"))


class SnsAlertSink:
    """Publishes each alert to an SNS topic (user-facing status alerting). Logs on failure and
    keeps going — a monitoring tick must not die because one publish failed. Inject `client` to
    test offline."""
    def __init__(self, topic_arn: str, region: Optional[str] = None, client: Any = None):
        self._topic_arn = topic_arn
        if client is not None:
            self._client = client
        else:
            import boto3
            self._client = boto3.client("sns", **({"region_name": region} if region else {}))

    def emit(self, alert: Alert) -> None:
        try:
            self._client.publish(
                TopicArn=self._topic_arn,
                Subject=f"MapleGuard: {len(alert.new_draws)} new draw(s) affect your position",
                Message=_sns_safe_message(alert.to_dict()),
            )
        except Exception as exc:  # pragma: no cover - publish failure is logged, not fatal
            logger.warning("SNS publish failed for profile=%s: %s", alert.profile_id, exc)


# SNS rejects any Message over 256 KB. A first tick (or a snapshot reset) diffs against an empty
# baseline, so every current draw counts as new and one profile's alert can serialize past that
# limit. Cap the two unbounded lists to a head sample plus a dropped-count when that happens; the
# durable stores keep the full alert, this bound is only what SNS will accept.
_SNS_MAX_BYTES = 256 * 1024
_SNS_SAMPLE = 25


def _sns_safe_message(body: dict) -> str:
    """JSON for SNS, bounded to the 256 KB limit. Returns the full alert when it fits; otherwise
    truncates `new_draws`/`impact` to a head sample (recording how many were dropped), and if it
    still will not fit, falls back to a minimal count-only message."""
    message = json.dumps(body, default=str)
    if len(message.encode("utf-8")) <= _SNS_MAX_BYTES:
        return message

    bounded = dict(body)
    for key in ("new_draws", "impact"):
        items = body.get(key)
        if isinstance(items, list) and len(items) > _SNS_SAMPLE:
            bounded[key] = items[:_SNS_SAMPLE]
            bounded[f"{key}_omitted"] = len(items) - _SNS_SAMPLE
    bounded["truncated"] = True
    message = json.dumps(bounded, default=str)
    if len(message.encode("utf-8")) <= _SNS_MAX_BYTES:
        return message

    return json.dumps({
        "profile_id": body.get("profile_id"), "as_of": body.get("as_of"),
        "new_draws_count": len(body.get("new_draws") or []),
        "impact_count": len(body.get("impact") or []),
        "citations": body.get("citations"), "truncated": True,
        "note": "alert exceeded the SNS size limit; fetch the full alert from the API",
    }, default=str)
