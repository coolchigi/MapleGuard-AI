"""Tests for Express Entry draw ingestion.

Parsing runs against a saved real-data fixture (ingest/fixtures/ee_rounds_sample.json) --
no network. One skipif-guarded live test fetches the real feed when explicitly enabled.

Run:  cd agents-for-humans/mapleguard && PYTHONPATH=. python3 -m pytest -q
"""
import json
import os
from datetime import date
from pathlib import Path

import pytest

from ingest import (DrawRecord, parse_rounds, parse_rounds_json, to_draws, classify,
                    ROUNDS_JSON_URL, fetch_rounds_json)
from paths import Draw

FIXTURE = Path(__file__).resolve().parent.parent / "ingest" / "fixtures" / "ee_rounds_sample.json"
FETCHED = date(2026, 8, 25)


@pytest.fixture(scope="module")
def records():
    payload = json.loads(FIXTURE.read_text())
    return parse_rounds(payload, source_url=ROUNDS_JSON_URL, fetched=FETCHED)


def _by_number(records, number):
    return next(r for r in records if r.round_number == number)


# --- Fixture shape ------------------------------------------------------------------
def test_fixture_parses_every_round(records):
    assert len(records) == 10
    assert all(isinstance(r, DrawRecord) for r in records)


def test_every_record_is_cited(records):
    # The trust posture: no value travels without source URL + fetch date + round number.
    for r in records:
        assert r.citation.source_url == ROUNDS_JSON_URL
        assert r.citation.fetched == FETCHED
        assert r.citation.round_number == r.round_number
        assert f"q={r.round_number}" in r.citation.round_url


# --- Value parsing ------------------------------------------------------------------
def test_general_draw_parsed_with_cutoff_and_size(records):
    g = _by_number(records, "294")           # General, 2024-04-23, CRS 529, size 2,095
    assert g.kind == "general" and g.category is None
    assert g.cutoff == 529 and g.invitations == 2095
    assert g.date == date(2024, 4, 23)
    assert not g.needs_manual_check


def test_thousands_separator_stripped(records):
    assert _by_number(records, "437").invitations == 5000   # "5,000" -> 5000


def test_non_integer_round_number_preserved(records):
    # Round ids "91a"/"91b" are real; they must survive as strings, not be coerced to int.
    assert _by_number(records, "91a").cutoff == 288
    assert _by_number(records, "91b").cutoff == 902


# --- Classification -----------------------------------------------------------------
def test_classification_of_each_kind(records):
    assert _by_number(records, "437").category == "french"            # French proficiency
    assert _by_number(records, "435").category == "provincial-nominee"  # federal PNP
    assert _by_number(records, "422").kind == "category"             # Healthcare occupations
    assert _by_number(records, "293").category == "stem-occupations"  # STEM
    assert _by_number(records, "268").kind == "general"              # No Program Specified


def test_program_restricted_draws_carry_a_caveat(records):
    cec = _by_number(records, "436")         # Canadian Experience Class
    assert cec.kind == "category"
    assert "narrower than all-program" in cec.notes
    pnp = _by_number(records, "435")
    assert "eligibility is holding a nomination" in pnp.notes


def test_classify_general_names():
    assert classify("General") == ("general", None, "")
    assert classify("No Program Specified")[0] == "general"


# --- Never guess: unparseable cutoff is flagged, not fabricated ---------------------
def test_unparseable_cutoff_is_flagged_not_guessed():
    payload = {"rounds": [
        {"drawNumber": "999", "drawDate": "2026-09-01", "drawName": "General",
         "drawCRS": "n/a", "drawSize": "1,000"},
    ]}
    [rec] = parse_rounds(payload, fetched=FETCHED)
    assert rec.cutoff is None
    assert rec.needs_manual_check is True
    assert "unparseable CRS cutoff" in rec.notes
    with pytest.raises(ValueError):
        rec.to_draw()                        # refuses to enter the engine with no cutoff


def test_malformed_date_flagged():
    payload = {"rounds": [
        {"drawNumber": "998", "drawDate": "Sept 1 2026", "drawName": "General",
         "drawCRS": "500", "drawSize": "1,000"},
    ]}
    [rec] = parse_rounds(payload, fetched=FETCHED)
    assert rec.needs_manual_check and "unparseable date" in rec.notes


# --- Mapping onto paths.Draw --------------------------------------------------------
def test_to_draws_maps_clean_records_and_skips_flagged(records):
    draws = to_draws(records)
    assert all(isinstance(d, Draw) for d in draws)
    assert len(draws) == len(records)        # fixture is all-clean
    g = next(d for d in draws if d.name == "General")
    assert g.kind == "general" and g.cutoff == 529 and g.source == ROUNDS_JSON_URL

    # A mixed batch: the flagged one is dropped, not coerced.
    mixed = parse_rounds({"rounds": [
        {"drawNumber": "1", "drawDate": "2026-01-01", "drawName": "General",
         "drawCRS": "500", "drawSize": "100"},
        {"drawNumber": "2", "drawDate": "2026-02-01", "drawName": "General",
         "drawCRS": "", "drawSize": "100"},
    ]}, fetched=FETCHED)
    assert len(to_draws(mixed)) == 1


def test_record_as_dict_is_serializable(records):
    d = _by_number(records, "294").as_dict()
    assert json.dumps(d)                     # round-trips through JSON
    assert d["citation"]["round_number"] == "294"


def test_parse_rounds_json_string_entrypoint():
    recs = parse_rounds_json(FIXTURE.read_text(), fetched=FETCHED)
    assert len(recs) == 10


# --- Optional live fetch (real network), only when explicitly enabled ---------------
@pytest.mark.skipif(
    not os.environ.get("MAPLEGUARD_INGEST_LIVE"),
    reason="set MAPLEGUARD_INGEST_LIVE=1 to hit the real canada.ca feed",
)
def test_live_fetch_and_parse():
    records = parse_rounds_json(fetch_rounds_json())
    assert len(records) > 100                # hundreds of historical rounds
    assert any(r.kind == "general" for r in records)
    assert all(r.citation.source_url == ROUNDS_JSON_URL for r in records)
