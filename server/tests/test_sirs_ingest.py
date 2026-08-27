"""Tests for the BC PNP SIRS research/ingestion pipeline (fetch -> parse -> reconcile).

None touch the network. The parser and reconcile run against the structural fixture and
against text generated from the in-code bands, so both the mismatch-catch and the
verified-verdict paths are exercised offline. The AgentCore Browser fetcher is exercised
through a fake client + injected page_reader; the real client surface is checked under
`importorskip`.
"""
import pathlib

import pytest

from pnp import bc as B
from pnp.sirs_ingest import (BC_PNP_SIRS_URL, BcPnpBrowserFetcher, parse_sirs_grid,
                             reconcile_band, reconcile_grid, verify_sirs_grid)

FIXTURE = (pathlib.Path(__file__).parent.parent / "pnp" / "fixtures"
           / "bc_pnp_sirs_grid_sample.txt")

_INT_SECTIONS = {"work_experience", "language", "wage"}


def _grid_text_from_code() -> str:
    """Build normalized grid text that exactly mirrors the in-code bands — the 'source agrees'
    case, generated from the tables themselves so it is obviously a mechanism check."""
    sections = {"work_experience": B.WORK_EXPERIENCE, "education": B.EDUCATION,
                "language": B.LANGUAGE, "wage": B.WAGE, "area": B.AREA}
    lines = []
    for name, table in sections.items():
        lines.append(f"[{name}]")
        for k, v in table.values.items():
            lines.append(f"{k} = {v}")
        lines.append("")
    return "\n".join(lines)


# --- 1. Parser: deterministic, total, never guesses -----------------------------------
def test_parser_reads_every_section_with_typed_keys():
    records = parse_sirs_grid(FIXTURE.read_text(), fetched=None)
    by_factor = {r.factor: r for r in records}
    assert set(by_factor) == {"work_experience", "education", "language", "wage", "area"}
    # Numeric sections carry int keys; string sections carry str keys.
    assert by_factor["work_experience"].bands[5] == 40
    assert by_factor["education"].bands["bachelors-or-three-year"] == 27
    assert by_factor["area"].bands["northern_bc"] == 25
    assert all(isinstance(k, int) for k in by_factor["wage"].bands)
    # Every record carries the source citation.
    assert all(r.citation.source_url == BC_PNP_SIRS_URL for r in records)


def test_parser_flags_missing_section_not_guesses():
    text = "[work_experience]\n0 = 0\n1 = 8\n"  # only one section present
    records = parse_sirs_grid(text)
    missing = {r.factor for r in records if r.needs_manual_check}
    assert {"education", "language", "wage", "area"} <= missing
    for r in records:
        if r.factor in missing:
            assert r.bands == {} and "missing" in r.notes


def test_parser_flags_unparseable_row():
    text = "[language]\n7 = 20\nCLB eight = lots\n"  # second row is not parseable
    rec = [r for r in parse_sirs_grid(text) if r.factor == "language"][0]
    assert rec.needs_manual_check and "unparseable" in rec.notes
    assert rec.bands == {7: 20}  # the good row is still parsed; the bad one is not guessed


def test_parser_rejects_non_integer_key_in_numeric_section():
    text = "[wage]\nfifteen = 4\n20 = 12\n"
    rec = [r for r in parse_sirs_grid(text) if r.factor == "wage"][0]
    assert rec.needs_manual_check and "non-integer key" in rec.notes
    assert rec.bands == {20: 12}


# --- 2. Reconcile: catches the planted discrepancy, confirms an exact match ------------
def test_shipped_fixture_reports_the_planted_wage_discrepancy():
    # The fixture mirrors the in-code bands except a planted wage row (45 = 50 vs code 45 = 51),
    # so the honest offline default is all_verified=False with a wage mismatch.
    v = verify_sirs_grid(fetcher=FIXTURE.read_text)
    assert v.all_verified is False
    assert "wage" in [r.factor for r in v.mismatches]
    wage = [r for r in v.reconciliations if r.factor == "wage"][0]
    assert wage.differing[45] == {"source": 50, "code": 51}
    # Every OTHER factor matches the in-code band exactly.
    others = [r for r in v.reconciliations if r.factor != "wage"]
    assert all(r.matches for r in others)


def test_exact_source_match_yields_verified_verdict():
    # Mechanism proof: when the fetched text equals the in-code bands, reconcile verifies each
    # factor. (This is a pipeline check, NOT a claim the bands are line-verified — that needs
    # the real BC PNP page; the fixture above is the honest shipped default.)
    v = verify_sirs_grid(fetcher=_grid_text_from_code)
    assert v.all_verified is True
    assert all(r.verified and r.matches for r in v.reconciliations)
    assert v.mismatches == []


def test_manual_check_blocks_a_verified_verdict_even_if_present_bands_match():
    # A factor with an unparseable row can never be 'verified', even if its parsed rows happen
    # to match — the source did not parse cleanly.
    text = _grid_text_from_code() + "\n[area]\nmetro_vancouver = 5\ngarbage row\n"
    records = parse_sirs_grid(text)
    area_recon = [reconcile_band(r) for r in records if r.factor == "area"][0]
    assert area_recon.verified is False


def test_reconcile_reports_source_only_and_code_only_keys():
    text = "[area]\nmetro_vancouver = 5\nmars_colony = 99\n"  # missing 3, extra 1
    rec = [r for r in parse_sirs_grid(text) if r.factor == "area"][0]
    recon = reconcile_band(rec)
    assert recon.source_only == {"mars_colony": 99}
    assert set(recon.code_only) == {"other_lower_mainland", "rest_of_bc", "northern_bc"}
    assert recon.matches is False


# --- 3. Fetch seam: injectable, offline --------------------------------------------------
def test_verify_uses_the_injected_fetcher_no_network():
    called = {"n": 0}
    def fetcher():
        called["n"] += 1
        return _grid_text_from_code()
    v = verify_sirs_grid(fetcher=fetcher)
    assert called["n"] == 1 and v.all_verified is True


# --- 4. AgentCore Browser fetcher --------------------------------------------------------
def test_browser_fetcher_drives_the_injected_page_reader():
    reads = {}
    def page_reader(client, url):
        reads["client"] = client
        reads["url"] = url
        return _grid_text_from_code()

    fetcher = BcPnpBrowserFetcher(client="fake-browser-client", page_reader=page_reader)
    text = fetcher()  # callable, so it drops straight into verify_sirs_grid(fetcher=...)
    v = verify_sirs_grid(fetcher=fetcher)
    assert reads["client"] == "fake-browser-client"
    assert reads["url"] == BC_PNP_SIRS_URL
    assert v.all_verified is True and text.startswith("[work_experience]")


def test_browser_client_surface_is_real():
    # Import-verified: the Browser primitive exists with the wired methods. build_...() would
    # start a live session (needs AWS), so we assert the class + its methods, not a live start.
    pytest.importorskip("bedrock_agentcore")
    from bedrock_agentcore.tools.browser_client import BrowserClient
    for method in ("start", "stop", "generate_ws_headers", "generate_live_view_url"):
        assert callable(getattr(BrowserClient, method))


# --- 5. Provenance / honesty guard -------------------------------------------------------
def test_pipeline_does_not_mutate_the_engine_bands():
    # Reconciliation reports; it must never flip pnp/bc.py's verified flags as a side effect.
    before = [t.verified for t in B.ALL_TABLES]
    verify_sirs_grid(fetcher=_grid_text_from_code)
    after = [t.verified for t in B.ALL_TABLES]
    assert before == after == [False] * len(B.ALL_TABLES)  # still unverified, unchanged
