"""Duty-coverage scoring and the top-level reference-letter audit.

The scorer is deterministic: given which required duties the letter covers, it computes
coverage against the claimed occupation, decides pass/fail against the threshold, and
lists each uncovered duty with a citation to the official NOC text.

Deciding which letter sentences cover which NOC duties is a separate step. In production
that alignment is produced by a language model; here it is injected as a ``DutyMatcher``
so the scoring logic can be tested on its own. Alignments are validated before use: every
piece of cited evidence must appear in the letter, so coverage cannot be claimed for text
that is not there.
"""
from __future__ import annotations

from typing import Dict, List, Protocol, Tuple

from .mandatory import check_mandatory_elements
from .models import (AuditReport, Citation, DutyCoverageResult, DutyMatch, NocOccupation)

DEFAULT_THRESHOLD = 0.8

# An alignment maps a required duty id to the letter sentence that covers it. A separate
# flag says whether the lead statement is covered, with its own supporting sentence.
Alignment = Dict[str, str]


class DutyMatcher(Protocol):
    def __call__(self, letter_text: str, occupation: NocOccupation) -> Tuple[Alignment, str]:
        """Return (duty alignment, lead-statement evidence sentence)."""
        ...


def validate_alignment(letter_text: str, alignment: Alignment, lead_evidence: str) -> Tuple[Alignment, bool]:
    """Drop any claimed coverage whose evidence is not actually present in the letter."""
    haystack = " ".join(letter_text.split()).lower()

    def present(snippet: str) -> bool:
        snippet = " ".join((snippet or "").split()).lower()
        return bool(snippet) and snippet in haystack

    validated = {duty_id: ev for duty_id, ev in alignment.items() if present(ev)}
    return validated, present(lead_evidence)


def score_duties(occupation: NocOccupation, alignment: Alignment, lead_statement_covered: bool,
                 threshold: float = DEFAULT_THRESHOLD) -> DutyCoverageResult:
    required = occupation.required_duties()
    matches = [DutyMatch(duty, duty.id in alignment, alignment.get(duty.id, "")) for duty in required]
    covered = sum(1 for match in matches if match.covered)
    coverage = covered / len(required) if required else 1.0
    passed = lead_statement_covered and coverage >= threshold
    gaps = [Citation(occupation.code, occupation.version, occupation.source, duty.text)
            for duty in required if duty.id not in alignment]
    return DutyCoverageResult(
        lead_statement_covered=lead_statement_covered, matches=matches, threshold=threshold,
        coverage=coverage, passed=passed, gaps=gaps,
    )


def audit_letter(letter_text: str, occupation: NocOccupation, matcher: DutyMatcher,
                 threshold: float = DEFAULT_THRESHOLD) -> AuditReport:
    """Run the full audit: required elements plus duty coverage against the occupation."""
    elements = check_mandatory_elements(letter_text)
    raw_alignment, lead_evidence = matcher(letter_text, occupation)
    alignment, lead_covered = validate_alignment(letter_text, raw_alignment, lead_evidence)
    duties = score_duties(occupation, alignment, lead_covered, threshold)
    return AuditReport(noc_code=occupation.code, elements=elements, duties=duties)
