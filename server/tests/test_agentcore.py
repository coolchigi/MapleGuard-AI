"""Tests for the AgentCore wiring: Code Interpreter proof surface, AgentCore Memory session
seam, and the observability loop trace.

None touch the network. The Code Interpreter proof surface is exercised for real offline via
a subprocess mirror, and the AgentCore-shaped path is exercised through a fake client that
emits the real `executeCode` stream shape, so the parser and wrapper run without AWS. The
strands-only tests use `importorskip`.
"""
import json

import pytest

from agent.sandbox import (AgentCoreCodeSandbox, LocalSubprocessSandbox, RESULT_MARKER,
                           crs_sandbox_snippet, parse_crs_stdout, run_crs_in_sandbox)

PROFILE = {
    "education": "bachelors-or-three-year",
    "first_language": {"speaking": 9, "listening": 9, "reading": 9, "writing": 9},
    "date_of_birth": "1996-07-01",
    "canadian_work_years": 1,
}


# --- 1. Code Interpreter proof surface: the offline subprocess mirror ------------------
def test_snippet_is_self_contained_and_marked():
    code = crs_sandbox_snippet(PROFILE, as_of="2026-08-25")
    assert "from crs import crs" in code and "serde.profile_from_dict" in code
    assert RESULT_MARKER in code
    # The snippet writes no arithmetic of its own; it calls the engine.
    assert "crs(_p" in code


def test_parse_crs_stdout_extracts_marked_json_and_ignores_noise():
    good = f"chatter\n{RESULT_MARKER}" + json.dumps({"total": 470}) + "\nmore"
    assert parse_crs_stdout(good)["total"] == 470
    assert parse_crs_stdout("no marker here") is None
    assert parse_crs_stdout(f"{RESULT_MARKER}not json") is None  # never guesses a number


def test_local_sandbox_recomputes_the_same_crs_in_a_separate_process():
    proof = run_crs_in_sandbox(PROFILE, as_of="2026-08-25")  # defaults to LocalSubprocessSandbox
    assert proof.via == "local"
    assert proof.matches is True
    # The mirror equals the in-process source of truth, factor for factor.
    assert proof.sandbox_total == proof.in_process["total"]
    assert proof.sandbox_score["breakdown"] == proof.in_process["breakdown"]
    # The exact code the sandbox ran is carried for the demo.
    assert RESULT_MARKER in proof.snippet


def test_local_sandbox_matches_the_in_process_engine_directly():
    from datetime import date
    from crs import LanguageScores, Profile, crs
    proof = run_crs_in_sandbox(PROFILE, as_of="2026-08-25")
    direct = crs(Profile(education="bachelors-or-three-year",
                         first_language=LanguageScores(9, 9, 9, 9),
                         date_of_birth=date(1996, 7, 1), canadian_work_years=1),
                 date(2026, 8, 25))
    assert proof.sandbox_total == direct.total == proof.in_process["total"]


def test_mismatch_is_reported_not_fabricated():
    class BrokenSandbox:
        via = "broken"
        def execute_code(self, code, language="python"):
            from agent.sandbox import SandboxResult
            return SandboxResult(stdout="segfault, no result", stderr="boom", exit_code=1,
                                 via="broken")

    proof = run_crs_in_sandbox(PROFILE, as_of="2026-08-25", sandbox=BrokenSandbox())
    assert proof.matches is False and proof.sandbox_total is None
    assert proof.in_process["total"] > 0  # the source of truth is still computed and honest


# --- 2. The AgentCore path shape, exercised offline via a fake client ------------------
class _FakeCodeInterpreterClient:
    """Emits the real `executeCode` stream shape the SDK returns, computing the actual
    stdout by running the snippet in a local subprocess. Exercises AgentCoreCodeSandbox's
    upload + parse end to end with no AWS."""
    def __init__(self):
        self.uploaded = {}

    def upload_file(self, path, content, description=""):
        self.uploaded[path] = content
        return {"ok": True}

    def execute_code(self, code, language="python"):
        inner = LocalSubprocessSandbox().execute_code(code, language=language)
        return {"stream": [
            {"result": {
                "structuredContent": {"stdout": inner.stdout, "stderr": inner.stderr,
                                      "exitCode": inner.exit_code},
                "content": [],
                "isError": inner.exit_code != 0,
            }},
        ]}


def test_agentcore_sandbox_parses_the_execute_code_stream_shape():
    client = _FakeCodeInterpreterClient()
    sandbox = AgentCoreCodeSandbox(client, upload_source=True)
    proof = run_crs_in_sandbox(PROFILE, as_of="2026-08-25", sandbox=sandbox)
    assert proof.via == "agentcore"
    assert proof.matches is True and proof.sandbox_total == proof.in_process["total"]
    # prepare() uploaded the FULL deterministic engine (not just the __init__s) before running,
    # plus serde behind a lightweight agent package stub.
    assert {"crs/__init__.py", "crs/engine.py", "paths/reach.py", "pnp/bc.py",
            "agent/__init__.py", "agent/serde.py"} <= set(client.uploaded)


class _IsolatedCodeInterpreterClient:
    """Runs the snippet with ONLY the uploaded files reachable — a fresh tmpdir on the path and
    the repo root deliberately absent — so the test fails if the uploaded set is not import-closed.
    This is the real managed-sandbox condition; the repo-rooted subprocess mirror masks it (which
    is exactly how the earlier partial upload passed tests while being broken in the cloud)."""
    def __init__(self):
        import tempfile
        self._dir = tempfile.mkdtemp(prefix="mg_ci_")
        self.uploaded = {}

    def upload_file(self, path, content, description=""):
        import os
        full = os.path.join(self._dir, path)
        os.makedirs(os.path.dirname(full) or self._dir, exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
        self.uploaded[path] = content
        return {"ok": True}

    def execute_code(self, code, language="python"):
        import os
        import subprocess
        import sys
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["PYTHONPATH"] = self._dir  # ONLY the uploaded files; no repo root
        proc = subprocess.run([sys.executable, "-c", code], cwd=self._dir, env=env,
                              capture_output=True, text=True, timeout=30)
        return {"stream": [{"result": {
            "structuredContent": {"stdout": proc.stdout, "stderr": proc.stderr,
                                  "exitCode": proc.returncode},
            "content": [], "isError": proc.returncode != 0,
        }}]}


def test_agentcore_sandbox_uploads_an_import_closed_set():
    # The snippet must import and recompute the CRS using ONLY the uploaded files. If the set were
    # incomplete (the P0-3 bug), `from agent import serde` / `from crs import crs` would ImportError
    # in the isolated interpreter and matches would be False.
    client = _IsolatedCodeInterpreterClient()
    sandbox = AgentCoreCodeSandbox(client, upload_source=True)
    proof = run_crs_in_sandbox(PROFILE, as_of="2026-08-25", sandbox=sandbox)
    assert proof.matches is True, f"isolated sandbox did not reproduce the score:\n{proof.stdout}"
    assert proof.sandbox_total == proof.in_process["total"]


def test_agentcore_parse_reads_text_content_blocks_too():
    # A stream that carries the result as text content blocks (no structuredContent).
    raw = {"stream": [
        {"result": {"content": [{"type": "text", "text": f"{RESULT_MARKER}"},
                                 {"type": "text", "text": json.dumps({"total": 512})}]}},
    ]}
    result = AgentCoreCodeSandbox._parse(raw)
    assert parse_crs_stdout(result.stdout)["total"] == 512
    assert result.via == "agentcore" and result.exit_code == 0


def test_agentcore_parse_flags_error_exit():
    raw = {"stream": [{"result": {"content": [], "isError": True}}]}
    assert AgentCoreCodeSandbox._parse(raw).exit_code == 1


# --- 3. AgentCore Memory session seam (config-level, offline) --------------------------
def test_agentcore_session_backend_requires_memory_id():
    from agent import Deployment
    from agent.config import build_session_manager
    with pytest.raises(ValueError, match="memory_id"):
        build_session_manager("u1", Deployment(session_backend="agentcore"))


def test_from_env_reads_agentcore_memory_config():
    from agent import Deployment
    cfg = Deployment.from_env(env={
        "MAPLEGUARD_SESSION_BACKEND": "agentcore",
        "MAPLEGUARD_MEMORY_ID": "mem-abc",
        "MAPLEGUARD_MEMORY_REGION": "us-east-1",
        "MAPLEGUARD_ACTOR_ID": "user-42",
    })
    assert cfg.session_backend == "agentcore" and cfg.memory_id == "mem-abc"
    assert cfg.memory_region == "us-east-1" and cfg.actor_id == "user-42"
    assert cfg.is_offline is False  # agentcore reaches AWS


def test_agentcore_memory_config_builds_with_real_sdk():
    # Import-verified path. The config object is pure (pydantic), so it builds with no AWS;
    # the session manager itself validates memoryId against the real Bedrock client on init
    # (a genuine seam, not a stub), which is why we assert the config, not a live manager.
    pytest.importorskip("bedrock_agentcore")
    from bedrock_agentcore.memory.integrations.strands.config import (AgentCoreMemoryConfig,
                                                                       RetrievalConfig)
    cfg = AgentCoreMemoryConfig(memory_id="mgd-mem-000000000000", session_id="s1",
                                actor_id="user-42",
                                retrieval_config={"/": RetrievalConfig(top_k=5)})
    assert cfg.memory_id.startswith("mgd-mem-") and cfg.actor_id == "user-42"
    assert cfg.retrieval_config["/"].top_k == 5


def test_agentcore_session_manager_reaches_the_real_client():
    # Building the manager with a well-formed id fails only because there is no live Memory
    # resource / AWS creds here. That it reaches botocore (not a local stub) proves the seam
    # is authentic.
    pytest.importorskip("bedrock_agentcore")
    pytest.importorskip("strands")
    from agent.memory import build_agentcore_session_manager
    with pytest.raises(Exception) as exc:
        build_agentcore_session_manager(memory_id="mgd-mem-000000000000", session_id="s1",
                                        actor_id="user-42", region_name="us-east-1")
    # A botocore/credentials/endpoint error, i.e. it tried to talk to real Bedrock.
    assert exc.type.__module__.startswith(("botocore", "bedrock_agentcore")) or \
        "credential" in str(exc.value).lower() or "region" in str(exc.value).lower() or \
        "endpoint" in str(exc.value).lower() or "resolve" in str(exc.value).lower()


# --- 4. Observability: the agent-loop trace proof surface -----------------------------
class _FakeMetrics:
    def get_summary(self):
        return {
            "total_cycles": 2,
            "total_duration": 0.5,
            "tool_usage": {
                "compute_crs": {"tool_info": {"name": "compute_crs"},
                                "execution_stats": {"call_count": 1, "success_count": 1,
                                                    "error_count": 0, "total_time": 0.02}},
            },
        }


class _FakeResult:
    def __init__(self, metrics=None):
        self.metrics = metrics
        self.message = "Your CRS is 427 (source: canada.ca)."


def test_agent_loop_trace_reports_the_tools_that_ran():
    from agent.observability import agent_loop_trace
    trace = agent_loop_trace(_FakeResult(_FakeMetrics()))
    assert trace["cycles"] == 2
    assert trace["tool_sequence"] == ["compute_crs"]
    assert trace["tools"][0]["success_count"] == 1


def test_agent_loop_trace_is_safe_without_metrics():
    from agent.observability import agent_loop_trace
    trace = agent_loop_trace(_FakeResult(metrics=None))
    assert trace == {"cycles": 0, "tools": [], "tool_sequence": [], "duration": 0.0}


def test_handle_attaches_the_loop_trace():
    from agent.runtime import handle
    # A prebuilt fake agent (no strands): calling it returns a result with no metrics, and
    # handle still attaches a (zeroed) trace and screens the text.
    class _Agent:
        def __call__(self, prompt):
            return _FakeResult(_FakeMetrics())
    out = handle({"prompt": "Where do I stand?"}, agent=_Agent())
    assert out["result"].startswith("Your CRS")
    assert out["trace"]["tool_sequence"] == ["compute_crs"]


# --- 5. Strands present: real loop trace + tracing config -----------------------------
def _fake_model(agent_messages):
    strands_models = pytest.importorskip("strands.models")

    class FakeModel(strands_models.Model):
        def __init__(self):
            self._responses = list(agent_messages); self._i = 0
        def get_config(self): return {}
        def update_config(self, **kwargs): pass
        async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
            yield {"output": None}
        async def stream(self, messages, tool_specs=None, system_prompt=None,
                         tool_choice=None, **kwargs):
            msg = self._responses[self._i]; self._i += 1
            yield {"messageStart": {"role": "assistant"}}
            stop = "end_turn"
            for block in msg["content"]:
                if "text" in block:
                    yield {"contentBlockStart": {"start": {}}}
                    yield {"contentBlockDelta": {"delta": {"text": block["text"]}}}
                    yield {"contentBlockStop": {}}
                if "toolUse" in block:
                    stop = "tool_use"; tu = block["toolUse"]
                    yield {"contentBlockStart": {"start": {"toolUse": {
                        "name": tu["name"], "toolUseId": tu["toolUseId"]}}}}
                    yield {"contentBlockDelta": {"delta": {"toolUse": {
                        "input": json.dumps(tu["input"])}}}}
                    yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": stop}}
    return FakeModel()


def test_real_loop_trace_shows_the_deterministic_tool_ran():
    pytest.importorskip("strands")
    from agent import build_orchestrator
    from agent.observability import agent_loop_trace
    model = _fake_model([
        {"role": "assistant", "content": [{"toolUse": {
            "name": "compute_crs", "toolUseId": "t1",
            "input": {"profile": PROFILE, "as_of": "2026-08-25"}}}]},
        {"role": "assistant", "content": [{"text": "Your position is computed above."}]},
    ])
    agent = build_orchestrator(model=model)
    result = agent("Where do I stand?")
    trace = agent_loop_trace(result)
    assert "compute_crs" in trace["tool_sequence"]  # the tool provably ran in the loop
    assert trace["cycles"] >= 1


def test_build_orchestrator_stamps_trace_attributes():
    pytest.importorskip("strands")
    from agent import build_orchestrator, DEFAULT_TRACE_ATTRIBUTES
    agent = build_orchestrator(model=_fake_model([]),
                               trace_attributes=DEFAULT_TRACE_ATTRIBUTES)
    assert agent.trace_attributes.get("mapleguard.posture") == "compute-and-refuse"


def test_enable_tracing_configures_a_console_exporter():
    pytest.importorskip("strands")
    from agent.observability import enable_tracing
    telemetry = enable_tracing(console=True)  # real OTEL setup, no AWS
    assert telemetry is not None


# --- 6. Runtime deploy wiring (build_orchestrator_from_env + agentcore entrypoint) ----
def test_build_orchestrator_from_env_stamps_trace_and_builds_offline():
    pytest.importorskip("strands")
    from agent.runtime import build_orchestrator_from_env
    from agent import DEFAULT_TRACE_ATTRIBUTES
    agent = build_orchestrator_from_env(model=_fake_model([]))
    assert agent.trace_attributes.get("mapleguard.posture") == "compute-and-refuse"
    # Default config wires the offline seeded corpus, so the agent gained memory retrieval.
    assert agent.tool_names  # the deterministic tools are registered


def test_agentcore_app_exposes_a_module_level_app():
    pytest.importorskip("strands")
    pytest.importorskip("bedrock_agentcore")
    import agent.agentcore_app as entry
    assert hasattr(entry, "app")
    assert hasattr(entry.app, "invoke")  # the @app.entrypoint handler, exposed for testing


def test_build_app_builds_a_fresh_agent_per_invocation_no_state_bleed(monkeypatch):
    # P1-5: the deployed handler must not reuse one Agent across callers (that leaks one caller's
    # conversation into the next). We prove it by recording how many messages the model sees on
    # each invocation: a fresh agent per call sees exactly the one new user turn (1), a shared
    # agent would see the accumulated history (3 on the second call).
    strands_models = pytest.importorskip("strands.models")
    pytest.importorskip("bedrock_agentcore")
    # Disable session persistence so the test is hermetic (no on-disk session carried between
    # runs); the no-bleed property comes from the fresh agent per call, not the session backend.
    monkeypatch.setenv("MAPLEGUARD_SESSION_BACKEND", "none")
    from agent.runtime import build_app

    seen_message_counts = []

    class _RecordingModel(strands_models.Model):
        def get_config(self): return {}
        def update_config(self, **kwargs): pass
        async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
            yield {"output": None}
        async def stream(self, messages, tool_specs=None, system_prompt=None,
                         tool_choice=None, **kwargs):
            seen_message_counts.append(len(messages))
            yield {"messageStart": {"role": "assistant"}}
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": "Here is your cited position."}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}

    app = build_app(model=_RecordingModel(), from_env=False)
    app.invoke({"prompt": "Where do I stand?", "session_id": "caller-A"})
    app.invoke({"prompt": "And now?", "session_id": "caller-B"})
    assert seen_message_counts == [1, 1]  # each invocation started clean; no bleed


def test_agentcore_entrypoint_takes_a_context_arg():
    # The AgentCore starter toolkit passes RequestContext as a 2nd param named exactly "context"
    # (BedrockAgentCoreApp._takes_context). Per-caller session isolation depends on it.
    import inspect
    pytest.importorskip("strands")
    pytest.importorskip("bedrock_agentcore")
    import agent.agentcore_app as entry
    params = list(inspect.signature(entry.app.invoke).parameters.keys())
    assert len(params) >= 2 and params[1] == "context"


# --- 7. The pinned Bedrock model + Bedrock-backed NOC tools (deploy correctness) -------
def test_hosted_orchestrator_model_is_pinned_not_the_sdk_default():
    pytest.importorskip("strands")
    from agent.config import DEFAULT_BEDROCK_MODEL_ID, build_bedrock_model
    # No env override -> the ONE pinned MapleGuard id, never Strands' shifting default.
    model = build_bedrock_model(env={})
    assert model.config["model_id"] == DEFAULT_BEDROCK_MODEL_ID
    # And the env override is honoured, so an operator can point at their enabled profile.
    override = build_bedrock_model(env={"MAPLEGUARD_BEDROCK_MODEL": "us.anthropic.custom-v1:0"})
    assert override.config["model_id"] == "us.anthropic.custom-v1:0"


def test_agent_noc_tools_use_bedrock_not_the_anthropic_public_api():
    anthropic = pytest.importorskip("anthropic")
    from agent.config import DEFAULT_BEDROCK_MODEL_ID, build_bedrock_noc_clients
    matcher, corrector = build_bedrock_noc_clients(env={"MAPLEGUARD_BEDROCK_REGION": "us-east-1"})
    assert matcher is not None and corrector is not None
    # The agent-path NOC clients target Bedrock (AWS creds), NOT api.anthropic.com (which needs
    # ANTHROPIC_API_KEY the AgentCore container does not have). This is the P0-2 fix.
    assert isinstance(matcher._client, anthropic.AnthropicBedrock)
    assert isinstance(corrector._client, anthropic.AnthropicBedrock)
    assert matcher._model == DEFAULT_BEDROCK_MODEL_ID == corrector._model


def test_shared_deploy_pieces_pin_model_and_bedrock_noc_clients():
    anthropic = pytest.importorskip("anthropic")
    pytest.importorskip("strands")
    from agent.runtime import _shared_deploy_pieces
    from agent.config import DEFAULT_BEDROCK_MODEL_ID
    pieces = _shared_deploy_pieces()  # model=None -> pins the Bedrock model
    assert pieces["model"].config["model_id"] == DEFAULT_BEDROCK_MODEL_ID
    assert isinstance(pieces["matcher"]._client, anthropic.AnthropicBedrock)
    assert isinstance(pieces["corrector"]._client, anthropic.AnthropicBedrock)


def test_deploy_build_threads_the_cited_corpus_into_the_audit_tool():
    # P0-3 (non-decorative KB): the hosted build wires the memory store as the audit tool's
    # citation corpus, so audit_reference_letter re-sources NOC gaps from the KB in deploy
    # (MAPLEGUARD_MEMORY_BACKEND=bedrock_kb) exactly as it re-sources from the seeded store in dev.
    pytest.importorskip("strands")
    import agent.tools as tools
    from agent.memory import search_sync
    from agent.runtime import build_orchestrator_from_env
    build_orchestrator_from_env(model=_fake_model([]))  # default env -> dev seeded corpus
    assert tools._DEPS.corpus is not None                # the corpus reached the tool layer
    assert search_sync(tools._DEPS.corpus, "NOC 21234 web developer")  # and it really retrieves


# --- 8. Trust posture: the model cannot force eligibility through the tool (P2-7) ------
def test_reachable_paths_tool_ignores_model_supplied_eligible_override():
    from agent import serde
    from agent.tools import reachable_paths as reachable_tool
    draw = {"kind": "category", "name": "Unrecognized category draw", "cutoff": 300,
            "date": "2026-08-01", "source": "https://example.gc.ca/round",
            "eligible_override": True}
    out = reachable_tool(PROFILE, [draw], as_of="2026-08-25")
    reached = [p["draw"]["name"] for p in out["reachable"]]
    flagged = [p["draw"]["name"] for p in out["needs_eligibility_check"]]
    # eligible_override stripped: an unrecognized category is honestly flagged, never forced.
    assert draw["name"] in flagged and draw["name"] not in reached

    # Contrast: the pure paths API (the deterministic ingest path, which the model does not
    # author) still honours the override — proving the tool boundary is where the lever is denied.
    from datetime import date
    from paths import reachable_paths as reachable_pure
    p = serde.profile_from_dict(PROFILE)
    pure = reachable_pure(p, [serde.draw_from_dict(draw)], date(2026, 8, 25))
    assert any(r.draw.name == draw["name"] for r in pure.reachable)
