"""AWS Lambda entrypoint for the autonomous monitor — the deploy assembly of the tick loop.

`monitor.py` has the pure loop (`tick`) and the scheduler entrypoint (`scheduled_handler`),
which needs a `MonitorDeps` assembled from the configured backends. This module is that
assembly for AWS: it wires the LIVE IRCC feed (`ingest.fetch_rounds_json`) to the DynamoDB
snapshot + profile stores and an SNS (or logging) sink, and exposes `lambda_handler` for an
EventBridge Scheduler rule to invoke on a cadence with no prompt. That unprompted, scheduled
invocation is the autonomy in ARCHITECTURE.md.

Goal state: only AWS provisioning remains. The code path is complete — an EventBridge rule ->
this handler -> live fetch -> diff snapshot -> relevance-filtered alerts -> DynamoDB/SNS. The
`infra/` Terraform + `make aws-up` stands the resources up; nothing here is a stub.

Everything is injectable, so the handler and the assembly TEST offline with a fixture fetch and
fake stores (no boto3, no network). The env below is read only on the default (deploy) path.

Env:
  MAPLEGUARD_PROFILES_TABLE    DynamoDB table of monitored profiles (required on default path)
  MAPLEGUARD_SNAPSHOT_TABLE    DynamoDB table for the feed snapshot   (required on default path)
  MAPLEGUARD_ALERT_TOPIC_ARN   SNS topic for user-facing alerts       (optional; else log only)
  AWS_REGION                   region for the boto3 clients
  MAPLEGUARD_ROUNDS_URL        override the IRCC feed URL (default ingest.ROUNDS_JSON_URL)
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

from .monitor import CollectingAlertSink, MonitorDeps, scheduled_handler

logger = logging.getLogger("mapleguard.monitor.lambda")


def build_monitor_deps(env: Optional[dict] = None, *,
                       fetch_rounds: Optional[Callable[[], str]] = None,
                       profiles: Any = None, snapshots: Any = None, sink: Any = None,
                       narrator: Any = None) -> MonitorDeps:
    """Assemble MonitorDeps for the scheduled run. Any component can be injected (tests do); the
    rest default to the live/AWS wiring:

      - fetch_rounds -> `ingest.fetch_rounds_json` (the LIVE IRCC feed; the loop's only I/O)
      - profiles     -> `DynamoDBProfileStore(MAPLEGUARD_PROFILES_TABLE)`
      - snapshots    -> `DynamoDBSnapshotStore(MAPLEGUARD_SNAPSHOT_TABLE)`
      - sink         -> `SnsAlertSink(MAPLEGUARD_ALERT_TOPIC_ARN)` if set, else the logging sink
    """
    e = os.environ if env is None else env
    region = e.get("AWS_REGION")

    if fetch_rounds is None:
        from ingest import ROUNDS_JSON_URL, fetch_rounds_json
        url = e.get("MAPLEGUARD_ROUNDS_URL", ROUNDS_JSON_URL)
        fetch_rounds = lambda: fetch_rounds_json(url)  # noqa: E731 - tiny live-fetch closure
        source_url = url
    else:
        source_url = e.get("MAPLEGUARD_ROUNDS_URL") or _default_source_url()

    if profiles is None:
        # The deploy monitor needs a durable store (a Lambda file store is ephemeral), so require
        # the table, then build via the shared config seam — the SAME store the API's
        # save-a-profile endpoint writes, so the monitor watches exactly the intake profiles.
        _require(e, "MAPLEGUARD_PROFILES_TABLE")
        from .config import Deployment, build_profile_store
        profiles = build_profile_store(Deployment.from_env(e))
    if snapshots is None:
        from .stores_aws import DynamoDBSnapshotStore
        snapshots = DynamoDBSnapshotStore(_require(e, "MAPLEGUARD_SNAPSHOT_TABLE"), region=region)
    if sink is None:
        topic = e.get("MAPLEGUARD_ALERT_TOPIC_ARN")
        if topic:
            from .stores_aws import SnsAlertSink
            sink = SnsAlertSink(topic, region=region)
        else:
            logger.info("no MAPLEGUARD_ALERT_TOPIC_ARN set; alerts are logged, not sent")
            sink = CollectingAlertSink()

    return MonitorDeps(fetch_rounds=fetch_rounds, profiles=profiles, snapshots=snapshots,
                       sink=sink, source_url=source_url, narrator=narrator)


def _require(env: dict, key: str) -> str:
    value = env.get(key)
    if not value:
        raise RuntimeError(f"{key} is required on the default monitor path (set it, or inject a "
                           f"store). See agent/monitor_lambda.py.")
    return value


def _default_source_url() -> str:
    from ingest import ROUNDS_JSON_URL
    return ROUNDS_JSON_URL


def lambda_handler(event: Optional[dict] = None, context: Any = None,
                   deps: Optional[MonitorDeps] = None) -> dict:
    """The AWS Lambda handler an EventBridge Scheduler rule invokes. Assembles the live/AWS deps
    (unless injected) and runs one monitoring tick via `scheduled_handler`. Returns the
    JSON-safe tick summary (alert count + snapshot)."""
    # Deps come from the environment (os.environ); the event only carries an optional as_of,
    # which scheduled_handler reads.
    deps = deps if deps is not None else build_monitor_deps()
    return scheduled_handler(event, context, deps=deps)
