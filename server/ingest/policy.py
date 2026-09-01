"""Policy-change classification: LLM extracts, deterministic code validates and drops.

MapleGuard already watches DRAWS. This adds the other watch: an IRCC policy update (a NOC
reclassification, a CRS-weight change, a cutoff/program/language rule change). The split is the
same determinism-below-the-model posture as everywhere else:

  - The LLM (`PolicyChangeClassifier`) reads an IRCC update and EXTRACTS a classification:
    {change_type, affected_noc_codes, affected_components, effective_date}. It classifies and
    extracts strings; it never computes a CRS number (there is no number for it to fill).
  - `validate_policy_change` is pure Python. It checks the extraction against a strict schema and
    DROPS anything that does not validate: an unknown change_type, a NOC change naming no
    well-formed code, an unparseable effective date, a missing source. Nothing unvalidated reaches
    the monitor. A dropped extraction is a silent no-op, never a guess.

`anthropic` is imported lazily inside the classifier, so this module imports and its validation
tests run with no key and no network (mirrors `noc/matcher.py`).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from noc import DEFAULT_MODEL  # reuse the pinned Sonnet id; classification is a light extraction

# The only change types the router understands. An extraction outside this set is dropped.
CHANGE_TYPES = frozenset({"noc", "crs_weight", "cutoff", "program", "language"})
# NOC 2021 codes are five digits. A code that is not five digits is not a NOC 2021 code.
NOC_CODE_RE = re.compile(r"^\d{5}$")


@dataclass(frozen=True)
class PolicyChange:
    """A validated, cited IRCC policy change. Every field survived `validate_policy_change`, so a
    `PolicyChange` never carries an unknown type, a malformed NOC code, or a guessed date."""
    change_type: str                       # one of CHANGE_TYPES
    affected_noc_codes: tuple[str, ...]     # well-formed 5-digit NOC 2021 codes only
    affected_components: tuple[str, ...]    # e.g. "arranged_employment", "french", free strings
    effective_date: Optional[date]          # None when the update stated none (never guessed)
    source: str                            # the update's citation URL (required)
    summary: str = ""                      # the update's own wording, for the alert (not a claim)

    def to_dict(self) -> dict:
        return {
            "change_type": self.change_type,
            "affected_noc_codes": list(self.affected_noc_codes),
            "affected_components": list(self.affected_components),
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "source": self.source,
            "summary": self.summary,
        }


def validate_policy_change(raw: object, source: str) -> Optional[PolicyChange]:
    """Validate a raw (LLM-produced) extraction against the strict schema. Returns a
    `PolicyChange`, or None if anything fails — the model's output is DROPPED, never patched.

    Drops when: not a dict; change_type not in CHANGE_TYPES; source missing (no uncited change);
    change_type=='noc' but no well-formed 5-digit code (an unactionable NOC change); or an
    effective_date is present but not ISO-parseable (no guessed dates).
    """
    if not isinstance(raw, dict) or not source:
        return None
    change_type = raw.get("change_type")
    if change_type not in CHANGE_TYPES:
        return None

    codes = tuple(
        c.strip() for c in (raw.get("affected_noc_codes") or [])
        if isinstance(c, str) and NOC_CODE_RE.match(c.strip())
    )
    if change_type == "noc" and not codes:
        return None  # a NOC change that names no valid code cannot be routed to a profile

    components = tuple(
        s.strip() for s in (raw.get("affected_components") or [])
        if isinstance(s, str) and s.strip()
    )

    effective_date: Optional[date] = None
    raw_date = raw.get("effective_date")
    if raw_date:
        try:
            effective_date = date.fromisoformat(str(raw_date))
        except (ValueError, TypeError):
            return None  # a present-but-unparseable date is a malformed field; drop the change

    return PolicyChange(
        change_type=change_type, affected_noc_codes=codes, affected_components=components,
        effective_date=effective_date, source=source,
        summary=str(raw.get("summary") or raw.get("raw_summary") or ""),
    )


def _extract_json(text: str) -> Optional[dict]:
    """Pull the first JSON object out of a model response, or None."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


_SYSTEM = """\
You classify a single IRCC (Immigration, Refugees and Citizenship Canada) policy update. You do
NOT compute or estimate any CRS/SIRS score, cutoff, or points value — you only classify and copy
identifiers that appear in the text. Return ONLY a JSON object with these keys:
  change_type: one of "noc", "crs_weight", "cutoff", "program", "language"
  affected_noc_codes: array of 5-digit NOC 2021 codes named in the update (empty if none)
  affected_components: array of short labels for what changed (e.g. "arranged_employment",
                       "french", "teer_duties"); empty if unclear
  effective_date: the date the change takes effect, as "YYYY-MM-DD", or null if the update states none
  summary: one sentence, using the update's own wording, of what changed
If a field is not clearly stated, use an empty array or null. Never invent a code, a date, or a
number. Output the JSON object and nothing else."""


class PolicyChangeClassifier:
    """The LLM half of the classifier: reads an IRCC update, returns a RAW extraction dict (to be
    validated by `validate_policy_change` — this class never validates or trusts its own output).

    Callable as ``(update_text) -> dict``. The client is created lazily (inject one to test with no
    network); pass a Bedrock-backed client for the deploy path (see `agent.config`)."""

    def __init__(self, model: str = DEFAULT_MODEL, client=None, max_tokens: int = 1024):
        self._model = model
        self._client = client
        self._max_tokens = max_tokens

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise RuntimeError(
                    "The 'anthropic' package is required for PolicyChangeClassifier. "
                    "Install it (pip install anthropic) or inject a client."
                ) from exc
            self._client = anthropic.Anthropic()
        return self._client

    def __call__(self, update_text: str) -> dict:
        response = self._get_client().messages.create(
            model=self._model, max_tokens=self._max_tokens, system=_SYSTEM,
            messages=[{"role": "user", "content": update_text}],
        )
        parts = []
        for block in getattr(response, "content", None) or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", "") or "")
        return _extract_json("".join(parts)) or {}
