"""Tests for the reference-letter audit.

Run:  cd agents-for-humans/mapleguard && python -m pytest -q
"""
from noc import (audit_letter, check_mandatory_elements, get_occupation, score_duties,
                 validate_alignment, ElementStatus)

OCC = get_occupation("21234")

COMPLETE_LETTER = """\
Acme Corp
January 15, 2026

To Whom It May Concern:

This letter confirms that Jane Doe was employed as a Web Developer at Acme Corp
from June 2025 to present. She works 37.5 hours per week and earns an annual salary
of $85,000 plus health benefits.

Her duties and responsibilities include:
- Develop, write, modify and test website code and web application interfaces
- Conduct tests and analyze data to monitor quality, security and user experience
- Develop and implement procedures for ongoing website revision
- Monitor and maintain website functionality

Sincerely,
John Manager, Engineering Director
Acme Corp, 123 Main St, Toronto. Phone: 416-555-1234, hr@acme.com
"""

DEFICIENT_LETTER = """\
To Whom It May Concern:

Jane Doe worked as a Web Developer from June 2025 to present. Her responsibilities
included monitoring and maintaining website functionality, and developing and
implementing procedures for ongoing website revision.

Regards,
John Manager
"""


def _status(results, label_fragment):
    return next(r.status for r in results if label_fragment.lower() in r.name.lower())


# --- Mandatory elements -------------------------------------------------------------
def test_complete_letter_elements_present():
    results = check_mandatory_elements(COMPLETE_LETTER)
    assert _status(results, "Period") is ElementStatus.PRESENT
    assert _status(results, "Hours") is ElementStatus.PRESENT
    assert _status(results, "Salary") is ElementStatus.PRESENT
    assert _status(results, "letterhead") is ElementStatus.NEEDS_MANUAL_CHECK


def test_deficient_letter_flags_missing_hours_and_salary():
    results = check_mandatory_elements(DEFICIENT_LETTER)
    assert _status(results, "Hours") is ElementStatus.MISSING
    assert _status(results, "Salary") is ElementStatus.MISSING
    assert _status(results, "Period") is ElementStatus.PRESENT


# --- Duty coverage scoring ----------------------------------------------------------
def test_full_coverage_passes():
    alignment = {
        "21234.1": "Develop, write, modify and test website code and web application interfaces",
        "21234.2": "Conduct tests and analyze data to monitor quality, security and user experience",
        "21234.3": "Develop and implement procedures for ongoing website revision",
        "21234.4": "Monitor and maintain website functionality",
    }
    result = score_duties(OCC, alignment, lead_statement_covered=True)
    assert result.required_count == 4          # the two "May ..." duties are optional
    assert result.coverage == 1.0
    assert result.passed
    assert result.gaps == []


def test_partial_coverage_fails_with_cited_gaps():
    alignment = {
        "21234.3": "developing and implementing procedures for ongoing website revision",
        "21234.4": "monitoring and maintaining website functionality",
    }
    result = score_duties(OCC, alignment, lead_statement_covered=True)
    assert result.coverage == 0.5
    assert not result.passed
    gap_texts = [g.text for g in result.gaps]
    assert any("Develop, write, modify" in t for t in gap_texts)
    assert any("Conduct tests" in t for t in gap_texts)
    for gap in result.gaps:                    # every gap cites the official NOC
        assert gap.noc_code == "21234"
        assert "esdc.gc.ca" in gap.source


def test_lead_statement_uncovered_fails_even_at_full_duty_coverage():
    alignment = {f"21234.{i}": "x" for i in range(1, 5)}
    # evidence "x" is irrelevant here; score_duties trusts the alignment it is given.
    result = score_duties(OCC, alignment, lead_statement_covered=False)
    assert result.coverage == 1.0 and not result.passed


# --- Anti-hallucination: evidence must be in the letter -----------------------------
def test_validate_alignment_drops_evidence_not_in_letter():
    # Evidence must be a snippet actually taken from the letter, not the NOC's own wording.
    alignment = {
        "21234.3": "developing and implementing procedures for ongoing website revision",  # in letter
        "21234.2": "Led a team of forty engineers across three continents",                # not in letter
    }
    validated, lead = validate_alignment(DEFICIENT_LETTER, alignment, "worked as a Web Developer")
    assert "21234.3" in validated
    assert "21234.2" not in validated          # fabricated coverage is discarded
    assert lead is True


# --- End to end ---------------------------------------------------------------------
def _stub_matcher(letter_text, occupation):
    alignment = {
        "21234.1": "Develop, write, modify and test website code and web application interfaces",
        "21234.2": "Conduct tests and analyze data to monitor quality, security and user experience",
        "21234.3": "Develop and implement procedures for ongoing website revision",
        "21234.4": "Monitor and maintain website functionality",
    }
    return alignment, "employed as a Web Developer"


def test_audit_letter_end_to_end_passes_on_complete_letter():
    report = audit_letter(COMPLETE_LETTER, OCC, _stub_matcher)
    assert report.duties.passed
    assert "Hours per week" in [e.name for e in report.elements]
    data = report.to_dict()
    assert data["duties"]["passed"] is True and data["noc_code"] == "21234"
