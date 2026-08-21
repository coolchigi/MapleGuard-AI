"""Data models for the reference-letter audit.

A reference letter for an Express Entry work-experience claim is assessed on two things:
the presence of the required elements of a valid letter, and whether the described work
substantially matches the claimed occupation's lead statement and main duties in the
National Occupational Classification (NOC).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Duty:
    """One main duty from a NOC occupation.

    ``optional`` is True for duties phrased as "May ..." in the NOC, which a candidate
    is not required to have performed.
    """
    id: str
    text: str
    optional: bool = False


@dataclass(frozen=True)
class NocOccupation:
    code: str
    title: str
    lead_statement: str
    main_duties: List[Duty]
    source: str
    version: str
    verified: bool = False

    def required_duties(self) -> List[Duty]:
        return [duty for duty in self.main_duties if not duty.optional]


class ElementStatus(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    NEEDS_MANUAL_CHECK = "needs_manual_check"  # cannot be confirmed from letter text alone


@dataclass(frozen=True)
class ElementResult:
    name: str
    status: ElementStatus
    evidence: str = ""  # the matched snippet, when present


@dataclass(frozen=True)
class DutyMatch:
    """A required duty and whether the letter was found to cover it."""
    duty: Duty
    covered: bool
    evidence: str = ""  # the sentence from the letter that covers it, when covered


@dataclass(frozen=True)
class Citation:
    noc_code: str
    version: str
    source: str
    text: str  # the exact NOC text the gap refers to


@dataclass(frozen=True)
class DutyCoverageResult:
    lead_statement_covered: bool
    matches: List[DutyMatch]
    threshold: float
    coverage: float             # fraction of required duties covered
    passed: bool
    gaps: List[Citation]        # required duties not covered, each cited to the NOC

    @property
    def covered_count(self) -> int:
        return sum(1 for m in self.matches if m.covered)

    @property
    def required_count(self) -> int:
        return len(self.matches)


@dataclass(frozen=True)
class AuditReport:
    noc_code: str
    elements: List[ElementResult]
    duties: DutyCoverageResult

    @property
    def elements_missing(self) -> List[str]:
        return [e.name for e in self.elements if e.status is ElementStatus.MISSING]

    def to_dict(self) -> dict:
        return {
            "noc_code": self.noc_code,
            "elements": [{"name": e.name, "status": e.status.value, "evidence": e.evidence}
                         for e in self.elements],
            "duties": {
                "lead_statement_covered": self.duties.lead_statement_covered,
                "coverage": round(self.duties.coverage, 3),
                "threshold": self.duties.threshold,
                "passed": self.duties.passed,
                "covered": self.duties.covered_count,
                "required": self.duties.required_count,
                "gaps": [{"noc_code": g.noc_code, "version": g.version,
                          "source": g.source, "text": g.text} for g in self.duties.gaps],
            },
        }
