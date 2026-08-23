"""Seed-integrity checks for the NOC occupations.

These assert structure and provenance (duty counts, optional "May ..." flags, source
URLs, id prefixes), not the exact wording -- the wording is transcribed from the official
ESDC profile and its trust is tracked by the ``verified`` flag.

Run:  cd agents-for-humans/mapleguard && PYTHONPATH=. python3 -m pytest -q
"""
import pytest

from noc import OCCUPATIONS, get_occupation, audit_letter

_EMPTY_MATCHER = lambda letter_text, occupation: ({}, "")

BC_TECH_DEV_NOCS = ["21234", "21231", "21232", "21230"]


@pytest.mark.parametrize("code", BC_TECH_DEV_NOCS)
def test_bc_tech_dev_nocs_are_seeded(code):
    occ = get_occupation(code)
    assert occ.code == code
    assert occ.title and occ.lead_statement
    assert occ.main_duties
    assert occ.version == "NOC 2021 Version 1.0"
    assert f"code={code}" in occ.source and "esdc.gc.ca" in occ.source
    for duty in occ.main_duties:
        assert duty.id.startswith(f"{code}.")
        assert duty.text


@pytest.mark.parametrize("code,required,optional", [
    ("21234", 4, 2),
    ("21231", 5, 1),
    ("21232", 7, 0),
    ("21230", 6, 2),
])
def test_required_vs_optional_duty_counts(code, required, optional):
    occ = get_occupation(code)
    assert len(occ.required_duties()) == required
    assert sum(1 for d in occ.main_duties if d.optional) == optional


def test_only_may_duties_are_optional():
    # Every optional duty is a "May ..." duty, and no "May ..." duty is left required.
    for occ in OCCUPATIONS.values():
        for duty in occ.main_duties:
            assert duty.optional == duty.text.startswith("May ")


def test_newly_seeded_nocs_flagged_unverified():
    # Honest provenance: transcribed-but-not-line-checked occupations are verified=False.
    assert get_occupation("21234").verified is True   # the original, verified verbatim
    for code in ["21231", "21232", "21230"]:
        assert get_occupation(code).verified is False


# --- NEEDS_VERIFICATION guard on the audit ------------------------------------------
def test_audit_of_verified_occupation_is_not_flagged():
    report = audit_letter("Some letter text.", get_occupation("21234"), _EMPTY_MATCHER)
    assert report.needs_verification is False
    assert report.verification_note == ""
    assert report.to_dict()["needs_verification"] is False


def test_audit_of_unverified_occupation_is_loudly_flagged():
    occ = get_occupation("21231")  # seeded verbatim but not yet line-verified
    report = audit_letter("Some letter text.", occ, _EMPTY_MATCHER)
    assert report.needs_verification is True
    assert "21231" in report.verification_note and occ.source in report.verification_note
    data = report.to_dict()
    assert data["needs_verification"] is True
    assert data["verification_note"]  # non-empty reason travels with the serialized report

