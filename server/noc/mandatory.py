"""Deterministic check for the required elements of an employment reference letter.

IRCC expects an employment reference letter to show the company letterhead, the job
title, the period of employment, hours per week, salary and benefits, the signatory's
name and title, and the duties performed. Some of these can be detected from the letter
text; letterhead is a visual element and is reported as needing a manual check rather
than guessed at. Detection is conservative: an element is reported MISSING only when a
targeted search finds nothing, and NEEDS_MANUAL_CHECK when text alone cannot confirm it.
"""
from __future__ import annotations

import re
from typing import List

from .models import ElementResult, ElementStatus

_MONTHS = (r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*")
_DATE = rf"(?:{_MONTHS}\.?\s+\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}/\d{{1,2}}/\d{{2,4}})"

_PATTERNS = {
    "employment_period": re.compile(
        rf"(?:from\s+)?{_DATE}\s*(?:-|–|to|until|through|present)\s*(?:{_DATE}|present)",
        re.IGNORECASE),
    "hours_per_week": re.compile(
        r"\b\d{1,2}(?:\.\d+)?\s*(?:hours|hrs)\b[^.\n]{0,20}\b(?:per|a|/|each)\s*week", re.IGNORECASE),
    "salary": re.compile(
        r"(?:\$\s?[\d,]{4,}|\b(?:salary|annual salary|per annum|per year|annually|compensation)\b)",
        re.IGNORECASE),
    "signature": re.compile(
        r"\b(?:sincerely|regards|yours (?:truly|sincerely)|signature|signed)\b", re.IGNORECASE),
    "company_contact": re.compile(
        r"(?:\b[\w.%-]+@[\w.-]+\.[a-z]{2,}\b|\b(?:tel|phone|fax)\b|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b)",
        re.IGNORECASE),
    "job_title": re.compile(
        r"\b(?:position of|title of|employed as|worked as|role of|as an?\s+[A-Z])", re.IGNORECASE),
    "duties_section": re.compile(
        r"\b(?:duties|responsibilities|responsible for|tasks included)\b", re.IGNORECASE),
}

# Elements that a plain-text letter cannot confirm and must be checked manually.
_MANUAL_ONLY = ("company_letterhead",)

_LABELS = {
    "company_letterhead": "Company letterhead",
    "job_title": "Job title",
    "employment_period": "Period of employment (dates)",
    "hours_per_week": "Hours per week",
    "salary": "Salary and benefits",
    "signature": "Signatory / signature",
    "company_contact": "Company contact information",
    "duties_section": "Duties described",
}

# Elements whose absence in text is inconclusive rather than a confirmed omission.
_INCONCLUSIVE_IF_ABSENT = {"job_title", "signature", "company_contact"}


def check_mandatory_elements(letter_text: str) -> List[ElementResult]:
    results: List[ElementResult] = []

    for name in _MANUAL_ONLY:
        results.append(ElementResult(_LABELS[name], ElementStatus.NEEDS_MANUAL_CHECK))

    for name, pattern in _PATTERNS.items():
        match = pattern.search(letter_text)
        if match:
            results.append(ElementResult(_LABELS[name], ElementStatus.PRESENT, match.group(0).strip()))
        elif name in _INCONCLUSIVE_IF_ABSENT:
            results.append(ElementResult(_LABELS[name], ElementStatus.NEEDS_MANUAL_CHECK))
        else:
            results.append(ElementResult(_LABELS[name], ElementStatus.MISSING))

    return results
