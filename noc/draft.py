"""The correction draft: a revised reference letter for the employer to sign.

Once the audit finds gaps, this rewrites the letter so it aligns with the NOC lead
statement and covers the required duties that were flagged. The model drafts prose, but
under the same compute-and-refuse spine as the matcher:

- It never asserts or implies eligibility. That call is the officer's, not ours.
- It never invents work. Every duty it describes must trace to something real: a passage
  already in the original letter, or an explicit fact the caller supplies. Titles, dates,
  hours, salary, and names are carried over unchanged, never conjured.
- When a required duty has no support in any input, the draft must LEAVE A GAP -- an
  ``[employer to confirm: <duty>]`` placeholder -- instead of fabricating coverage. That
  honesty is the product, not a limitation of it.

The output is re-auditable: run ``audit_letter`` on the draft and the gaps close for every
duty that had real support, while unsupported duties stay open as placeholders.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .matcher import DEFAULT_MODEL
from .models import Duty, DutyCoverageResult, NocOccupation

# The placeholder the model must emit for a duty it cannot honestly support. We surface
# these so the employer sees exactly what still needs confirming.
PLACEHOLDER_RE = re.compile(r"\[employer to confirm:[^\]]*\]", re.IGNORECASE)

_SYSTEM = (
    "You revise a Canadian immigration reference letter so it aligns with a National "
    "Occupational Classification (NOC) occupation, for the employer to review and sign. "
    "You are a careful drafter, not an advocate.\n\n"
    "Hard rules:\n"
    "- Never state, imply, or comment on whether the applicant is eligible for anything. "
    "You align paperwork; you do not assess cases.\n"
    "- Only describe work that is supported by the ORIGINAL letter or the SUPPORTING FACTS "
    "given to you. Never invent duties, accomplishments, metrics, dates, job titles, hours, "
    "salary, or names. Carry every such factual detail over from the original unchanged.\n"
    "- Where the underlying work is genuinely supported, you may rephrase and reorganise it "
    "to describe it in the NOC's own duty language so an officer can match it.\n"
    "- For any required duty with NO support in the original letter or supporting facts, do "
    "NOT describe it. Instead insert a line exactly of the form "
    "'[employer to confirm: <the duty text>]'. Leaving this gap is correct and expected.\n"
    "- Preserve the letter's mandatory elements when present (employment period, hours per "
    "week, salary, and employer contact/signature).\n"
    "- Output ONLY the revised letter text. No preamble, no explanation, no code fences."
)


@dataclass(frozen=True)
class CorrectionDraft:
    """A revised letter plus the honest gaps it could not close."""
    letter_text: str
    placeholders: List[str]  # the "[employer to confirm: ...]" lines left in the draft

    @property
    def has_open_gaps(self) -> bool:
        return bool(self.placeholders)


def _uncovered_required_duties(coverage: DutyCoverageResult) -> List[Duty]:
    return [m.duty for m in coverage.matches if not m.covered]


def _build_user_prompt(letter_text: str, occupation: NocOccupation,
                       coverage: DutyCoverageResult, supporting_facts: Sequence[str]) -> str:
    gaps = _uncovered_required_duties(coverage)
    gap_lines = "\n".join(f"- {d.id}: {d.text}" for d in gaps) or "- (none)"
    all_required = "\n".join(f"- {d.id}: {d.text}" for d in occupation.required_duties())
    facts = "\n".join(f"- {f}" for f in supporting_facts) if supporting_facts else "- (none provided)"
    lead_note = ("The lead statement is NOT yet reflected; make the opening describe the role "
                 "in these terms where the original supports it.\n"
                 if not coverage.lead_statement_covered else "")
    return (
        f"NOC occupation {occupation.code} - {occupation.title}\n\n"
        f"Lead statement (align the letter's description of the role to this):\n"
        f"{occupation.lead_statement}\n\n"
        f"All required main duties:\n{all_required}\n\n"
        f"Duties flagged as GAPS to close (only if supported):\n{gap_lines}\n\n"
        f"{lead_note}"
        f"SUPPORTING FACTS the caller has attested (you MAY rely on these; nothing else):\n{facts}\n\n"
        f"ORIGINAL letter:\n\"\"\"\n{letter_text}\n\"\"\"\n\n"
        "Rewrite the letter. Cover each flagged duty ONLY where the original letter or the "
        "supporting facts support it, using the NOC duty wording. For any flagged duty with "
        "no support, insert '[employer to confirm: <duty text>]' instead of describing it. "
        "Output only the revised letter."
    )


def _extract_letter(text: str) -> str:
    """Return the drafted letter, unwrapping a code fence if the model added one."""
    text = (text or "").strip()
    if text.startswith("```"):
        # drop the opening fence line (``` or ```text) and a trailing fence if present
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _extract_text(response) -> str:
    parts = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


class LetterCorrector:
    """Drafts a corrected reference letter with a Claude model.

    Callable as ``(letter_text, occupation, coverage, supporting_facts=None) -> CorrectionDraft``,
    where ``coverage`` is the ``DutyCoverageResult`` from a prior audit (it tells the drafter
    which duties are gaps and whether the lead statement still needs work).

    The client is created lazily, so importing and constructing this needs no key or
    network; inject a client to test offline.
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
                    "The 'anthropic' package is required for LetterCorrector. "
                    "Install it (pip install anthropic) or inject a client."
                ) from exc
            self._client = anthropic.Anthropic()
        return self._client

    def __call__(self, letter_text: str, occupation: NocOccupation,
                 coverage: DutyCoverageResult,
                 supporting_facts: Optional[Sequence[str]] = None) -> CorrectionDraft:
        response = self._get_client().messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _build_user_prompt(
                letter_text, occupation, coverage, supporting_facts or [])}],
        )
        drafted = _extract_letter(_extract_text(response))
        placeholders = PLACEHOLDER_RE.findall(drafted)
        return CorrectionDraft(letter_text=drafted, placeholders=placeholders)
