"""PII scrubbing for stored reference letters, via Bedrock Guardrails (ApplyGuardrail).

A reference letter carries personal data (candidate and signatory names, contact details). Before
a letter is persisted to the profile store, it is run through a Bedrock Guardrail configured with
PII redaction, so the stored copy — and every downstream re-audit the monitor runs on it — never
holds raw personal data.

Two honest properties:
  * Injectable: the scrubber (and its boto3 client) is passed into `create_app`, so tests exercise
    the write path with a fake and no AWS.
  * Never silently faked: with no guardrail configured (`MAPLEGUARD_GUARDRAIL_ID` unset), the
    scrubber is a NO-OP that returns the text untouched and reports `applied=False`. The server
    runs unchanged locally and the endpoints report `pii_scrubbed: false` rather than pretending.

The `ApplyGuardrail` response parsing here is docs-derived (modelled on the Bedrock API: masked
text in `outputs[].text`, `action == "GUARDRAIL_INTERVENED"` when it redacted). Confirm against a
real guardrail on first live use, the same posture as the other not-yet-exercised AWS surfaces.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

GUARDRAIL_ID_ENV = "MAPLEGUARD_GUARDRAIL_ID"
GUARDRAIL_VERSION_ENV = "MAPLEGUARD_GUARDRAIL_VERSION"
GUARDRAIL_REGION_ENV = "MAPLEGUARD_GUARDRAIL_REGION"


@dataclass(frozen=True)
class ScrubResult:
    """The outcome of scrubbing one piece of text.

    `applied` is True only when a guardrail actually processed the text (never for the no-op).
    `intervened` is True when the guardrail masked or blocked something.
    """
    text: str
    applied: bool
    intervened: bool = False


class NoopScrubber:
    """No guardrail configured: return the text untouched, honestly reporting applied=False."""
    configured = False

    def scrub(self, text: str) -> ScrubResult:
        return ScrubResult(text=text, applied=False)


class BedrockGuardrailScrubber:
    """Run text through a Bedrock Guardrail with PII redaction. boto3 is imported lazily and the
    client is injectable, so this module imports and tests with no AWS and no boto3."""
    configured = True

    def __init__(self, guardrail_id: str, version: str = "DRAFT",
                 region: Optional[str] = None, client: Any = None):
        self._id = guardrail_id
        self._version = version
        if client is not None:
            self._client = client
        else:
            import boto3
            self._client = boto3.client(
                "bedrock-runtime", **({"region_name": region} if region else {}))

    def scrub(self, text: str) -> ScrubResult:
        if not text:
            return ScrubResult(text=text, applied=True)
        # source="OUTPUT" is deliberate and load-bearing. Bedrock applies PII ANONYMIZE (masking)
        # to OUTPUT content only; with source="INPUT" the guardrail runs but returns the text
        # untouched (action=NONE), which would silently store the PII while reporting success.
        # Verified live: OUTPUT returns action=GUARDRAIL_INTERVENED with the masked text in
        # outputs[0].text (e.g. "{NAME}", "{EMAIL}", "{PHONE}").
        resp = self._client.apply_guardrail(
            guardrailIdentifier=self._id, guardrailVersion=self._version,
            source="OUTPUT", content=[{"text": {"text": text}}])
        outputs = resp.get("outputs") or []
        scrubbed = outputs[0]["text"] if outputs and "text" in outputs[0] else text
        return ScrubResult(text=scrubbed, applied=True,
                           intervened=resp.get("action") == "GUARDRAIL_INTERVENED")


def build_letter_scrubber(env: Optional[dict] = None):
    """The env-selected scrubber: a Bedrock guardrail when `MAPLEGUARD_GUARDRAIL_ID` is set, else
    the no-op. This is the one place the server decides whether letters are scrubbed on write."""
    e = os.environ if env is None else env
    guardrail_id = e.get(GUARDRAIL_ID_ENV)
    if not guardrail_id:
        return NoopScrubber()
    return BedrockGuardrailScrubber(
        guardrail_id,
        version=e.get(GUARDRAIL_VERSION_ENV, "DRAFT"),
        region=e.get(GUARDRAIL_REGION_ENV) or e.get("AWS_REGION"))
