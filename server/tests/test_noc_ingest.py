"""Tests for the NOC 2021 ingestion pipeline (noc/ingest.py).

All offline: they parse saved ESDC profile fixtures, never the network. The trust rules under
test are the point of the pipeline: verified=True is earned by a DETERMINISTIC source-match, and
the LLM judge is VETO-ONLY (it can downgrade, never certify).

Run:  cd server && PYTHONPATH=. python3 -m pytest -q tests/test_noc_ingest.py
"""
import pathlib

import pytest

from noc import (content_hash, ingest_batch, ingest_profile, occupation_from_dict,
                 occupation_to_dict, parse_noc_profile, records_for_spotcheck,
                 verify_against_html)

FIX = pathlib.Path(__file__).parent.parent / "noc" / "fixtures"
CODES = ["21230", "21231", "21232", "21233", "21234"]


def _html(code: str) -> str:
    return (FIX / f"noc_{code}_2021.html").read_text(encoding="utf-8")


# --- Deterministic parse -------------------------------------------------------------
@pytest.mark.parametrize("code", CODES)
def test_parse_extracts_code_title_teer_and_duties(code):
    p = parse_noc_profile(_html(code), code)
    assert p.problems == [], p.problems
    assert p.code == code
    assert p.title and p.lead_statement
    assert p.teer == 1  # every 2123x tech code is TEER 1 (the code's 2nd digit)
    assert p.main_duties
    for i, duty in enumerate(p.main_duties, 1):
        assert duty.id == f"{code}.{i}"
        assert duty.text
        # optional is exactly the "May ..." rule, nothing else.
        assert duty.optional == duty.text.startswith("May ")


def test_parse_matches_known_web_developer_shape():
    p = parse_noc_profile(_html("21234"), "21234")
    assert p.title == "Web developers and programmers"
    assert len(p.main_duties) == 6
    assert sum(1 for d in p.main_duties if d.optional) == 2  # the two "May ..." duties
    assert p.main_duties[0].text.startswith("Develop, write, modify")


# --- Deterministic source-match earns verified=True ----------------------------------
@pytest.mark.parametrize("code", CODES)
def test_ingest_confers_verified_on_source_match(code):
    occ = ingest_profile(_html(code), code)
    assert occ.verified is True
    assert "source-match" in occ.verification_note
    assert occ.teer == 1
    assert occ.fetched  # ISO date stamped
    assert len(occ.content_hash) == 64
    # The content hash is a function of the extracted content, and stable across re-parses.
    again = ingest_profile(_html(code), code)
    assert again.content_hash == occ.content_hash


def test_content_hash_changes_when_content_changes():
    occ = ingest_profile(_html("21234"), "21234")
    from noc import Duty
    tampered = content_hash("Web developers and programmers", occ.lead_statement,
                            [Duty("x", "a different duty")])
    assert tampered != occ.content_hash


def test_reverify_against_a_different_page_fails():
    # Drift detection: a stored record re-checked against the WRONG page (or a page whose NOC text
    # has since changed) must fail the source-match. Verify 21234's record against 21231's page.
    occ = ingest_profile(_html("21234"), "21234")
    matched, note = verify_against_html(occ, _html("21231"))
    assert matched is False
    assert "source-match failed" in note
    # And it still matches its own page.
    assert verify_against_html(occ, _html("21234"))[0] is True


def test_parse_problems_block_verification():
    occ = ingest_profile("<html><body>no profile here</body></html>", "21234")
    assert occ.verified is False
    assert "parse incomplete" in occ.verification_note


# --- The LLM judge is VETO-ONLY ------------------------------------------------------
def test_judge_can_downgrade_a_verified_record():
    def vetoing_judge(parsed, page_text):
        return False, "duty 3 looks paraphrased"
    occ = ingest_profile(_html("21234"), "21234", judge=vetoing_judge)
    assert occ.verified is False
    assert "needs-review" in occ.verification_note and "judge veto" in occ.verification_note


def test_judge_cannot_certify_an_unverified_record():
    # A judge that approves must NEVER raise an unverified record to verified. On a record that
    # fails deterministic verification (here: an unparseable page), the judge is not even consulted
    # and verified stays False. The model can veto ground truth, never confer it.
    def approving_judge(parsed, page_text):
        return True, "looks great"
    occ = ingest_profile("<html><body>not a profile</body></html>", "21234", judge=approving_judge)
    assert occ.verified is False
    assert "parse incomplete" in occ.verification_note  # not a judge-approved note


def test_judge_error_never_silently_certifies():
    def broken_judge(parsed, page_text):
        raise RuntimeError("model unavailable")
    occ = ingest_profile(_html("21234"), "21234", judge=broken_judge)
    assert occ.verified is False and "judge veto" in occ.verification_note


# --- Batch + corpus round-trip + spot-check ------------------------------------------
def test_ingest_batch_with_injected_fetcher_runs_offline():
    occs = ingest_batch(CODES, fetcher=_html)
    assert set(occs) == set(CODES)
    assert all(o.verified for o in occs.values())


def test_corpus_round_trip_preserves_every_field():
    occ = ingest_profile(_html("21231"), "21231")
    back = occupation_from_dict(occupation_to_dict(occ))
    assert back == occ  # frozen dataclasses compare by value


def test_records_for_spotcheck_is_a_deterministic_sample():
    occs = ingest_batch(CODES, fetcher=_html)
    sample = records_for_spotcheck(occs, every=2)
    assert sample == ["21230", "21232", "21234"]  # sorted, every 2nd
