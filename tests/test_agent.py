"""Tests for the Strands orchestrator layer.

Three groups, none of which touch the network:

  1. Tools     the deterministic functions are registered, directly callable, and return
               the right typed results with their citations intact.
  2. Gates     the never-submit and never-assert-eligibility policy gates actually block.
  3. Loop      a mocked-model smoke test drives the real Strands Agent through a tool call
               and back, proving the orchestration wiring (Strands only; skipped if absent).

The pure layers (tools, serde, gates) import and run with or without Strands installed, so
the bulk of the suite is green on any machine. The loop test uses `importorskip("strands")`
and a fake model modelled on the SDK's own MockedModelProvider, so it exercises the genuine
event loop offline. A live test at the end runs only when a Bedrock key is configured.
"""
import json
import os

import pytest

from agent import (GateDecision, MAPLEGUARD_TOOLS, SYSTEM_PROMPT, configure_deps,
                   forbidden_tools, handle, never_assert_eligibility, never_submit)
from agent.orchestrator import screen_response, tool_name
from agent.tools import (audit_reference_letter, compute_crs, crs_deadlines, crs_trajectory,
                         ingest_draws, reachable_paths, sirs_bc)
from crs import Profile, crs

PROFILE = {
    "education": "bachelors-or-three-year",
    "first_language": {"speaking": 9, "listening": 9, "reading": 9, "writing": 9},
    "date_of_birth": "1996-07-01",
    "canadian_work_years": 1,
    "first_language_test_date": "2025-09-30",
}


# --- 1. Tools: registered, callable, right typed results, citations intact -----------
def test_all_tools_registered_and_named():
    names = [tool_name(t) for t in MAPLEGUARD_TOOLS]
    assert names == [
        "compute_crs", "crs_trajectory", "crs_deadlines", "sirs_bc",
        "reachable_paths", "ingest_draws", "audit_reference_letter", "draft_corrected_letter",
    ]


def test_compute_crs_matches_the_deterministic_engine():
    from datetime import date
    result = compute_crs(PROFILE, as_of="2026-08-25")
    expected = crs(Profile(education="bachelors-or-three-year",
                           first_language=__import__("crs").LanguageScores(9, 9, 9, 9),
                           date_of_birth=date(1996, 7, 1), canadian_work_years=1),
                   date(2026, 8, 25))
    assert result["total"] == expected.total
    assert result["core"] + result["spouse"] + result["skill_transfer"] + result["additional"] \
        == result["total"]
    assert {li["factor"] for li in result["breakdown"]} >= {"age", "education", "first_language"}


def test_trajectory_and_deadlines_return_dated_cliffs():
    traj = crs_trajectory(PROFILE, start="2026-08-25", end="2028-01-01")
    assert traj["points"][0]["date"] == "2026-08-25"
    # The language test (dated 2025-09-30) expires 2027-09-30, inside the range -> a cliff.
    assert any(c["kind"] == "test_expiry" for c in traj["cliffs"])
    dl = crs_deadlines(PROFILE, as_of="2026-08-25")
    assert dl["test_expiry"] == "2027-09-30"
    assert dl["test_expiry_cliff"]["delta"] < 0  # losing language points is a drop


def test_sirs_bc_flags_job_offer_and_reports_out_of_200():
    result = sirs_bc(PROFILE)  # no offer
    assert result["job_offer_required"] is True
    assert result["eligible_to_register"] is False
    assert 0 <= result["score"] <= 200
    assert result["crs_bonus_if_nominated"] == 600
    # A tech-exempt offer makes registration possible and scores the economic factors.
    with_offer = sirs_bc(PROFILE, offer={"hourly_wage": 45, "area": "northern_bc",
                                         "is_tech_exempt": True})
    assert with_offer["eligible_to_register"] is True
    assert with_offer["score"] > result["score"]


def test_reachable_paths_classifies_against_cited_cutoffs():
    total = compute_crs(PROFILE, as_of="2026-08-25")["total"]
    draws = [
        {"kind": "general", "name": "EE #340", "cutoff": total - 10, "date": "2026-08-06",
         "source": "https://www.canada.ca/en/immigration-refugees-citizenship/x"},
        {"kind": "general", "name": "EE #341", "cutoff": total + 200, "date": "2026-08-20",
         "source": "https://www.canada.ca/en/immigration-refugees-citizenship/y"},
    ]
    r = reachable_paths(PROFILE, draws, as_of="2026-08-25")
    assert len(r["reachable"]) == 1 and r["reachable"][0]["clears"] is True
    assert r["reachable"][0]["draw"]["source"].startswith("https://www.canada.ca")


def test_reachable_paths_refuses_uncited_cutoff():
    draws = [{"kind": "general", "name": "mystery", "cutoff": 400, "date": "2026-08-06"}]
    with pytest.raises(ValueError, match="no source"):
        reachable_paths(PROFILE, draws, as_of="2026-08-25")


def test_ingest_draws_parses_cited_records_without_network():
    import pathlib
    doc = (pathlib.Path(__file__).parent.parent / "ingest" / "fixtures"
           / "ee_rounds_sample.json").read_text()
    out = ingest_draws(doc, source_url="https://www.canada.ca/rounds.json")
    assert out["draws"], "no usable draws parsed"
    assert all(d["source"] == "https://www.canada.ca/rounds.json" for d in out["draws"])
    assert all(isinstance(d["cutoff"], int) for d in out["draws"])


def test_audit_tool_returns_cited_report_with_injected_fake_matcher():
    # Fake matcher: claims two verbatim duties; the deterministic scorer/validator do the
    # rest. No network, no real model.
    letter = ("This confirms Jane Doe worked as a Web Developer. She works 37.5 hours per "
              "week at $85,000 per year. Monitor and maintain website functionality. "
              "Develop and implement procedures for ongoing website revision. Sincerely.")

    def fake_matcher(letter_text, occupation):
        return ({"21234.4": "Monitor and maintain website functionality.",
                 "21234.3": "Develop and implement procedures for ongoing website revision."},
                "worked as a Web Developer")

    configure_deps(matcher=fake_matcher)
    try:
        report = audit_reference_letter(letter, "21234")
    finally:
        configure_deps()  # reset to defaults
    assert report["noc_code"] == "21234"
    assert report["duties"]["required"] == 4
    assert all(g["noc_code"] == "21234" and g["source"] for g in report["duties"]["gaps"])


# --- 2. Gates: the two policy gates actually block -----------------------------------
def test_never_submit_blocks_submission_tool_names():
    for name in ["submit_application", "file_ee_application", "efile", "upload_to_ircc"]:
        d = never_submit(name)
        assert isinstance(d, GateDecision) and d.allowed is False and d.gate == "never_submit"
    for name in [tool_name(t) for t in MAPLEGUARD_TOOLS]:
        assert never_submit(name).allowed is True  # none of our real tools submit


def test_forbidden_tools_flags_a_submit_tool_in_a_list():
    assert forbidden_tools(["compute_crs", "submit_application"]) == ["submit_application"]
    assert forbidden_tools([tool_name(t) for t in MAPLEGUARD_TOOLS]) == []


def test_never_assert_eligibility_blocks_verdicts_but_allows_cited_facts():
    for verdict in ["You are eligible for Express Entry.", "You are not eligible.",
                    "you qualify for PR", "You do not qualify.", "We guarantee you an ITA."]:
        assert never_assert_eligibility(verdict).allowed is False
    for fact in ["Your CRS is 470, which clears the cutoff of 468 (source: canada.ca).",
                 "French NCLC 7 across abilities is met.",
                 "You could submit this yourself once you decide."]:
        assert never_assert_eligibility(fact).allowed is True


def test_screen_response_is_the_never_assert_gate():
    assert screen_response("You are eligible.").gate == "never_assert_eligibility"
    assert screen_response("Your CRS is 470.").allowed is True


# --- 3. Loop: mocked-model smoke test of the real Strands orchestration ---------------
def _fake_model(agent_messages, usages=None):
    """A Strands Model that replays canned assistant messages, so the real Agent event loop
    runs offline. Modelled on the SDK's tests/fixtures MockedModelProvider."""
    strands_models = pytest.importorskip("strands.models")

    class FakeModel(strands_models.Model):
        def __init__(self):
            self._responses = list(agent_messages)
            self._i = 0

        def get_config(self):
            return {}

        def update_config(self, **kwargs):
            pass

        async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
            yield {"output": None}

        async def stream(self, messages, tool_specs=None, system_prompt=None,
                         tool_choice=None, **kwargs):
            msg = self._responses[self._i]
            self._i += 1
            yield {"messageStart": {"role": "assistant"}}
            stop = "end_turn"
            for block in msg["content"]:
                if "text" in block:
                    yield {"contentBlockStart": {"start": {}}}
                    yield {"contentBlockDelta": {"delta": {"text": block["text"]}}}
                    yield {"contentBlockStop": {}}
                if "toolUse" in block:
                    stop = "tool_use"
                    tu = block["toolUse"]
                    yield {"contentBlockStart": {"start": {"toolUse": {
                        "name": tu["name"], "toolUseId": tu["toolUseId"]}}}}
                    yield {"contentBlockDelta": {"delta": {"toolUse": {
                        "input": json.dumps(tu["input"])}}}}
                    yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": stop}}

    return FakeModel()


def test_orchestration_loop_calls_a_tool_then_answers():
    pytest.importorskip("strands")
    from agent import build_orchestrator

    # Turn 1: the model calls compute_crs. Turn 2: it answers using the tool's result.
    model = _fake_model([
        {"role": "assistant", "content": [{"toolUse": {
            "name": "compute_crs", "toolUseId": "t1",
            "input": {"profile": PROFILE, "as_of": "2026-08-25"}}}]},
        {"role": "assistant", "content": [{"text": "Your CRS is computed above; here it is."}]},
    ])
    agent = build_orchestrator(model=model)
    result = agent("Where do I stand?")
    # The tool actually ran inside the loop: its result is in the conversation as a toolResult.
    tool_results = [b["toolResult"] for m in agent.messages for b in m["content"]
                    if isinstance(b, dict) and "toolResult" in b]
    assert tool_results, "the orchestrator did not execute the tool"
    payload = tool_results[0]["content"][0]
    body = payload.get("json", payload.get("text"))
    if isinstance(body, str):
        body = json.loads(body)
    assert "total" in body and body["core"] + body["spouse"] + body["skill_transfer"] \
        + body["additional"] == body["total"]
    assert "eligible" not in str(result.message).lower() or screen_response(str(result.message)).allowed


def test_build_orchestrator_refuses_a_submission_tool():
    pytest.importorskip("strands")
    from strands import tool as strands_tool
    from agent import build_orchestrator

    @strands_tool
    def submit_application(profile: dict) -> dict:
        """Would file to IRCC — must never be registerable."""
        return {"filed": True}

    with pytest.raises(ValueError, match="never submits"):
        build_orchestrator(model=_fake_model([]),
                           tools=list(MAPLEGUARD_TOOLS) + [submit_application])


def test_never_submit_hook_cancels_a_submit_tool_call_below_the_model():
    pytest.importorskip("strands")
    from strands import Agent, tool as strands_tool
    from agent.orchestrator import make_policy_gate

    calls = {"ran": False}

    @strands_tool
    def file_application(profile: dict) -> dict:
        """A submit tool used ONLY to prove the gate cancels it at runtime."""
        calls["ran"] = True
        return {"filed": True}

    # Register it directly (bypassing build's refusal) to prove the runtime hook blocks it.
    model = _fake_model([
        {"role": "assistant", "content": [{"toolUse": {
            "name": "file_application", "toolUseId": "t1", "input": {"profile": PROFILE}}}]},
        {"role": "assistant", "content": [{"text": "I cannot submit; you file it yourself."}]},
    ])
    agent = Agent(model=model, tools=[file_application], system_prompt=SYSTEM_PROMPT,
                  hooks=[make_policy_gate()])
    agent("Please submit my application.")
    assert calls["ran"] is False, "never-submit gate did not cancel the tool call"


def test_handle_blocks_an_eligibility_verdict_from_the_model():
    pytest.importorskip("strands")
    model = _fake_model([
        {"role": "assistant", "content": [{"text": "You are eligible for Express Entry."}]},
    ])
    out = handle({"prompt": "Am I eligible?"}, model=model)
    assert out.get("blocked") is True and out["gate"] == "never_assert_eligibility"


# --- Optional live test: only when a Bedrock model + AWS creds are configured ---------
@pytest.mark.skipif(
    not os.environ.get("MAPLEGUARD_AGENT_INTEGRATION"),
    reason="set MAPLEGUARD_AGENT_INTEGRATION=1 (and configure AWS Bedrock) to run live",
)
def test_orchestrator_live():
    pytest.importorskip("strands")
    from agent import build_orchestrator
    agent = build_orchestrator()  # default Bedrock model
    result = agent("My CRS please. Education bachelors, all four language abilities CLB 9, "
                   "age 30, one year Canadian work.")
    assert screen_response(str(result.message)).allowed  # never asserts eligibility
