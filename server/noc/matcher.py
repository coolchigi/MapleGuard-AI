"""The model-backed ``DutyMatcher``.

The LLM does one job and only one: propose *which sentence in the letter covers which
NOC duty*. It never computes the coverage fraction, never decides pass/fail, and never
asserts eligibility. Those are the deterministic scorer's job (``score_duties``).

Its output is treated as a set of claims, not truth. Each claim is a duty id plus the
*verbatim* sentence from the letter that supposedly covers it, so ``validate_alignment``
can drop any claim whose evidence is not literally in the letter. A model that paraphrases
therefore loses that coverage, which is the intended behaviour: coverage cannot be
fabricated, only cited.
"""
from __future__ import annotations

import json
from typing import Dict, Optional, Tuple

from .models import NocOccupation

# This is a per-letter extraction, so we deliberately use a low-cost model rather than an
# Opus-tier one. Sonnet 4.5 is the default; override via the constructor's ``model`` argument.
# (The API layer pins the Bedrock inference-profile form of this in api/model_config.py.)
DEFAULT_MODEL = "claude-sonnet-4-5"

_SYSTEM = (
    "You pre-audit a Canadian immigration reference letter against a National Occupational "
    "Classification (NOC) occupation. You do exactly one thing: for each NOC duty, decide "
    "whether some sentence in the letter describes that work, and if so quote that sentence "
    "verbatim.\n\n"
    "Hard rules:\n"
    "- Quote sentences EXACTLY as they appear in the letter, character for character. Never "
    "paraphrase, summarise, correct, or stitch fragments together. Copy the substring.\n"
    "- Only map a duty when a sentence genuinely describes that work. If nothing covers a "
    "duty, omit it. A missing duty is a correct and useful answer.\n"
    "- Never assert, imply, or comment on the applicant's eligibility, and never invent work "
    "that is not written in the letter.\n"
    "- Reply with a single JSON object and nothing else."
)


def _build_user_prompt(letter_text: str, occupation: NocOccupation) -> str:
    duties = "\n".join(f"- {d.id}: {d.text}" for d in occupation.required_duties())
    return (
        f"NOC occupation {occupation.code} - {occupation.title}\n\n"
        f"Lead statement:\n{occupation.lead_statement}\n\n"
        f"Required main duties (map each by its id):\n{duties}\n\n"
        f"Reference letter:\n\"\"\"\n{letter_text}\n\"\"\"\n\n"
        "Return JSON of this exact shape:\n"
        "{\n"
        '  "lead_evidence": "<verbatim sentence from the letter that matches the lead '
        'statement, or empty string>",\n'
        '  "duties": { "<duty id>": "<verbatim sentence from the letter that covers it>" }\n'
        "}\n"
        "Include a duty id only when the letter covers it. Every value must be copied "
        "verbatim from the letter above."
    )


def _extract_text(response) -> str:
    """Concatenate the text blocks of a Messages API response, defensively."""
    parts = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


def _parse_response(text: str, occupation: NocOccupation) -> Tuple[Dict[str, str], str]:
    """Pull the alignment out of the model's reply, tolerating fences and stray prose.

    Anything malformed collapses to "no coverage claimed" rather than raising, so a bad
    model turn degrades to an empty (failing) audit instead of crashing the pipeline.
    """
    obj = _load_json_object(text)
    if not isinstance(obj, dict):
        return {}, ""

    valid_ids = {d.id for d in occupation.main_duties}
    raw_duties = obj.get("duties")
    alignment: Dict[str, str] = {}
    if isinstance(raw_duties, dict):
        for duty_id, sentence in raw_duties.items():
            if str(duty_id) in valid_ids and isinstance(sentence, str) and sentence.strip():
                alignment[str(duty_id)] = sentence

    lead = obj.get("lead_evidence")
    lead_evidence = lead if isinstance(lead, str) else ""
    return alignment, lead_evidence


def _load_json_object(text: str):
    """Best-effort parse of the first JSON object in ``text``."""
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None


class LLMDutyMatcher:
    """A ``DutyMatcher`` backed by a Claude model.

    Satisfies the ``noc.audit.DutyMatcher`` protocol: callable as
    ``(letter_text, occupation) -> (alignment, lead_evidence)``.

    The Anthropic client is created lazily on first use, so importing this module and
    constructing the matcher never require the SDK, a key, or a network. Inject a client
    (or any object exposing ``messages.create``) to test without the network.
    """

    def __init__(self, model: str = DEFAULT_MODEL, client=None, max_tokens: int = 4096):
        self._model = model
        self._client = client
        self._max_tokens = max_tokens

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise RuntimeError(
                    "The 'anthropic' package is required for LLMDutyMatcher. "
                    "Install it (pip install anthropic) or inject a client."
                ) from exc
            self._client = anthropic.Anthropic()
        return self._client

    def __call__(self, letter_text: str, occupation: NocOccupation) -> Tuple[Dict[str, str], str]:
        response = self._get_client().messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _build_user_prompt(letter_text, occupation)}],
        )
        return _parse_response(_extract_text(response), occupation)
