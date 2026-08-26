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


def test_tool_specs_are_richly_typed_not_loose_dicts():
    pytest.importorskip("strands")
    from agent.tools import compute_crs, reachable_paths
    crs_spec = json.dumps(compute_crs.tool_spec)
    # The profile is a structured schema (nested language object), not a bare object, and
    # education is an enum of the published levels, not a free string.
    assert "LanguageScoresInput" in crs_spec
    assert "bachelors-or-three-year" in crs_spec  # education Literal became an enum
    # A draw list is typed element-by-element, carrying the required source citation field.
    reach_spec = json.dumps(reachable_paths.tool_spec)
    assert "DrawInput" in reach_spec and "source" in reach_spec


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


# --- 4. Team: the optional auditor + strategist agent-as-tool split -------------------
def _fake_model_factory(scripts):
    """Hand each agent (built in order: strategist, auditor, advisor) its own scripted fake
    model. A stateful fake must not be shared, so the team takes a factory, not one model."""
    queue = list(scripts)

    def make():
        return _fake_model(queue.pop(0))
    return make


def test_advisor_team_is_two_specialists_as_native_agent_tools():
    pytest.importorskip("strands")
    from agent import build_advisor_team, build_document_auditor, build_strategist, NOC_TOOLS, POSITION_TOOLS
    from agent.orchestrator import tool_name
    factory = _fake_model_factory([[], [], []])  # construction only, no invocation
    advisor = build_advisor_team(model_factory=factory)
    # The advisor's tools are exactly the two specialists, wrapped by the SDK's as_tool().
    assert advisor.tool_names == ["strategist", "document_auditor"]
    # Each specialist owns the right deterministic kit and nothing else.
    strat = build_strategist(model=_fake_model([]))
    aud = build_document_auditor(model=_fake_model([]))
    assert strat.tool_names == [tool_name(t) for t in POSITION_TOOLS]
    assert aud.tool_names == [tool_name(t) for t in NOC_TOOLS]


def test_no_team_agent_can_carry_a_submission_tool():
    pytest.importorskip("strands")
    from agent import build_advisor_team, build_document_auditor, build_strategist
    for agent in (build_strategist(model=_fake_model([])),
                  build_document_auditor(model=_fake_model([])),
                  build_advisor_team(model_factory=_fake_model_factory([[], [], []]))):
        assert forbidden_tools(agent.tool_names) == []


def test_strategist_runs_the_real_loop_and_computes_a_number():
    pytest.importorskip("strands")
    from agent import build_strategist
    model = _fake_model([
        {"role": "assistant", "content": [{"toolUse": {
            "name": "compute_crs", "toolUseId": "s1",
            "input": {"profile": PROFILE, "as_of": "2026-08-25"}}}]},
        {"role": "assistant", "content": [{"text": "Your CRS is computed above."}]},
    ])
    strat = build_strategist(model=model)
    strat("Compute my CRS.")
    results = [b["toolResult"] for m in strat.messages for b in m["content"]
               if isinstance(b, dict) and "toolResult" in b]
    assert results, "the strategist did not execute compute_crs"


def test_advisor_routes_to_the_strategist_and_the_tool_runs_nested():
    pytest.importorskip("strands")
    from agent import build_advisor_team
    # strategist script: call compute_crs, then answer. auditor: unused. advisor: call the
    # strategist agent-tool (input arg is "input"), then answer.
    factory = _fake_model_factory([
        [  # strategist
            {"role": "assistant", "content": [{"toolUse": {
                "name": "compute_crs", "toolUseId": "s1",
                "input": {"profile": PROFILE, "as_of": "2026-08-25"}}}]},
            {"role": "assistant", "content": [{"text": "The strategist computed the CRS."}]},
        ],
        [{"role": "assistant", "content": [{"text": "unused"}]}],  # auditor
        [  # advisor
            {"role": "assistant", "content": [{"toolUse": {
                "name": "strategist", "toolUseId": "a1",
                "input": {"input": "Compute this candidate's CRS as of 2026-08-25."}}}]},
            {"role": "assistant", "content": [{"text": "Here is your position, computed and cited."}]},
        ],
    ])
    advisor = build_advisor_team(model_factory=factory)
    result = advisor("Where do I stand?")
    # The advisor delegated to the strategist, and inside that sub-agent the real tool ran.
    advisor_tool_results = [b["toolResult"] for m in advisor.messages for b in m["content"]
                            if isinstance(b, dict) and "toolResult" in b]
    assert advisor_tool_results, "the advisor did not delegate to a specialist"
    assert screen_response(str(result.message)).allowed


# --- 5. Dev-mirror memory + session + state (offline; AWS seams marked) ---------------
def test_deployment_defaults_are_fully_offline():
    from agent import Deployment
    from agent.config import build_memory, build_session_manager
    cfg = Deployment.from_env(env={})
    assert cfg.is_offline and cfg.memory_backend == "dev" and cfg.session_backend == "file"


def test_aws_backends_refuse_without_required_config():
    from agent import Deployment
    from agent.config import build_memory, build_session_manager
    with pytest.raises(ValueError, match="knowledge_base_id"):
        build_memory(Deployment(memory_backend="bedrock_kb"))
    with pytest.raises(ValueError, match="s3_bucket"):
        build_session_manager("u1", Deployment(session_backend="s3"))
    assert build_memory(Deployment(memory_backend="none")) is None
    assert build_session_manager("u1", Deployment(session_backend="none")) is None


def test_noc_corpus_seed_passages_carry_citations():
    from agent import noc_seed_passages
    passages = noc_seed_passages()
    assert passages, "no seed passages built"
    # NOC 21234 (seeded in noc/data.py) has a lead statement and its duties, each cited.
    codes = {m["noc_code"] for _, m in passages}
    assert "21234" in codes
    assert all(m.get("source") for _, m in passages)  # every passage cites its source
    assert any(m["kind"] == "lead_statement" and m["noc_code"] == "21234" for _, m in passages)


def test_dev_memory_retrieves_and_cites_the_noc_source():
    pytest.importorskip("strands")
    from agent.memory import build_test_memory, search_sync
    _, store = build_test_memory(seed=True)
    hits = search_sync(store, "design create and modify web sites", max_results=2)
    assert hits, "retrieval returned nothing"
    # The retrieved passage carries the live NOC source URL as its citation (not a hardcoded
    # string the model could drift from).
    assert any(h.metadata.get("noc_code") == "21234"
               and h.metadata.get("source", "").startswith("https://noc.esdc.gc.ca")
               for h in hits)


def test_dev_orchestrator_persists_conversation_and_profile_state(tmp_path):
    pytest.importorskip("strands")
    from agent import build_dev_orchestrator
    profile = dict(PROFILE)
    model = _fake_model([{"role": "assistant", "content": [{"text": "Here is your position."}]}])
    agent = build_dev_orchestrator("user-xyz", profile=profile, model=model,
                                   storage_dir=str(tmp_path))
    agent("Where do I stand?")
    assert agent.state.get("profile") == profile  # the profile lives in agent.state
    # A fresh agent with the same session_id restores the persisted conversation.
    reloaded = build_dev_orchestrator(
        "user-xyz",
        model=_fake_model([{"role": "assistant", "content": [{"text": "ok"}]}]),
        storage_dir=str(tmp_path))
    assert len(reloaded.messages) > 0


# --- 6. NOC audit cites from the retrieved corpus (live retrieval, offline) -----------
AUDIT_LETTER = ("This confirms Jane Doe worked as a Web Developer at Acme. She works 37.5 "
                "hours per week at $85,000 per year. Monitor and maintain website "
                "functionality. Sincerely, John Manager.")


def _audit_matcher(letter_text, occupation):
    # Covers only one duty, so the rest are flagged as cited gaps.
    return ({"21234.4": "Monitor and maintain website functionality."}, "worked as a Web Developer")


class _FakeEntry:
    def __init__(self, content, metadata):
        self.content = content
        self.metadata = metadata


class _FakeStore:
    """A minimal async store standing in for a memory store, so the citation resolver is
    testable with no SDK. Returns any seeded entry whose content contains a query word."""
    def __init__(self, entries):
        self._entries = entries

    async def search(self, query, options=None):
        words = set(query.lower().split())
        return [e for e in self._entries
                if words & set(e.content.lower().split())]


def test_citation_resolver_resolves_gap_source_from_corpus_no_sdk():
    # Pure-Python: fake store carries a NOC 21234 duty passage with a real source.
    from agent.citations import cite_gaps_from_corpus
    store = _FakeStore([
        _FakeEntry("NOC 21234 main duty 21234.1: Develop write modify integrate and test "
                   "Web site related code",
                   {"noc_code": "21234", "source": "https://noc.esdc.gc.ca/live-passage",
                    "_relevanceScore": 5}),
    ])
    report = {"duties": {"gaps": [
        {"noc_code": "21234", "version": "NOC 2021", "source": "hardcoded-string-from-data.py",
         "text": "Develop, write, modify, integrate and test Web site related code"},
    ]}}
    out = cite_gaps_from_corpus(report, store)
    gap = out["duties"]["gaps"][0]
    assert gap["cited_via"] == "corpus_retrieval"
    assert gap["source"] == "https://noc.esdc.gc.ca/live-passage"   # re-sourced from retrieval
    assert gap["source"] != "hardcoded-string-from-data.py"
    assert out["citations"]["resolved_from"] == "corpus_retrieval"


def test_citation_resolver_falls_back_to_seed_on_miss_no_sdk():
    from agent.citations import cite_gaps_from_corpus
    report = {"duties": {"gaps": [
        {"noc_code": "21234", "version": "v", "source": "seed-source", "text": "some duty text"},
    ]}}
    out = cite_gaps_from_corpus(report, _FakeStore([]))   # empty corpus -> no hit
    gap = out["duties"]["gaps"][0]
    assert gap["cited_via"] == "seed" and gap["source"] == "seed-source"  # never dropped
    assert out["citations"]["resolved_from"] == "seed"


def test_audit_tool_cites_gaps_from_seeded_corpus_end_to_end():
    pytest.importorskip("strands")
    from agent.memory import build_test_memory
    from agent.tools import audit_reference_letter
    from agent import configure_deps
    _, store = build_test_memory(seed=True)
    configure_deps(matcher=_audit_matcher, corpus=store)
    try:
        report = audit_reference_letter(AUDIT_LETTER, "21234")
    finally:
        configure_deps()
    assert report["citations"]["resolved_from"] == "corpus_retrieval"
    assert report["duties"]["gaps"], "expected cited gaps"
    for gap in report["duties"]["gaps"]:
        assert gap["cited_via"] == "corpus_retrieval"
        assert gap["source"].startswith("https://noc.esdc.gc.ca")  # the live-retrieved source


def test_audit_tool_without_a_corpus_is_unchanged():
    # No corpus configured -> deterministic seed citations, no retrieval fields added.
    from agent.tools import audit_reference_letter
    from agent import configure_deps
    configure_deps(matcher=_audit_matcher)  # no corpus
    try:
        report = audit_reference_letter(AUDIT_LETTER, "21234")
    finally:
        configure_deps()
    assert "citations" not in report
    assert all("cited_via" not in g for g in report["duties"]["gaps"])
    assert all(g["source"] for g in report["duties"]["gaps"])  # seed citation still present


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
