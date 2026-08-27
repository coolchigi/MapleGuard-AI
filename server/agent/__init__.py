"""MapleGuard agent layer — a single Strands orchestrator over the deterministic core.

The agent never computes a number, asserts eligibility, or submits an application. It
registers the pure functions in `crs` / `paths` / `pnp` / `noc` / `ingest` as TOOLS, calls
them for every value, explains the cited results, and drafts corrections. Two deterministic
policy gates (`gates.py`) enforce never-submit and never-assert-eligibility below the model.

Public surface:
  build_orchestrator  build the Strands agent (model + tools injectable)
  MAPLEGUARD_TOOLS    the registered tool list
  SYSTEM_PROMPT       the compute-and-refuse system prompt
  handle              the AWS-free request handler (what AgentCore Runtime hosts)
  build_app           wrap the handler in a Bedrock AgentCore app for deployment
  never_submit, never_assert_eligibility, GateDecision   the policy gates
"""
from .citations import cite_gaps_from_corpus, retrieve_citation
from .config import Deployment, build_memory, build_session_manager
from .gates import GateDecision, forbidden_tools, never_assert_eligibility, never_submit
from .memory import (build_agentcore_session_manager, build_kb_memory, build_test_memory,
                     noc_seed_passages)
from .observability import (DEFAULT_TRACE_ATTRIBUTES, agent_loop_trace, enable_tracing,
                            format_loop_trace)
from .sandbox import (AgentCoreCodeSandbox, LocalSubprocessSandbox, ReproducibleScore,
                      SandboxResult, build_agentcore_sandbox, crs_sandbox_snippet,
                      run_crs_in_sandbox)
from .monitor import (Alert, CollectingAlertSink, FileSnapshotStore, InMemoryProfileStore,
                      InMemorySnapshotStore, MonitorDeps, Snapshot, StoredProfile, TickResult,
                      scheduled_handler, tick)
from .orchestrator import (SYSTEM_PROMPT, build_dev_orchestrator, build_orchestrator,
                           make_policy_gate, screen_response, tool_name)
from .runtime import build_app, handle
from .team import (build_advisor_team, build_document_auditor, build_strategist)
from .tools import (MAPLEGUARD_TOOLS, NOC_TOOLS, POSITION_TOOLS, ToolDeps, configure_deps)

__all__ = [
    "build_orchestrator",
    "build_dev_orchestrator",
    "build_advisor_team",
    "build_strategist",
    "build_document_auditor",
    "build_test_memory",
    "build_kb_memory",
    "build_agentcore_session_manager",
    "noc_seed_passages",
    "run_crs_in_sandbox",
    "crs_sandbox_snippet",
    "build_agentcore_sandbox",
    "LocalSubprocessSandbox",
    "AgentCoreCodeSandbox",
    "SandboxResult",
    "ReproducibleScore",
    "enable_tracing",
    "agent_loop_trace",
    "format_loop_trace",
    "DEFAULT_TRACE_ATTRIBUTES",
    "cite_gaps_from_corpus",
    "retrieve_citation",
    "Deployment",
    "build_memory",
    "build_session_manager",
    "MAPLEGUARD_TOOLS",
    "POSITION_TOOLS",
    "NOC_TOOLS",
    "SYSTEM_PROMPT",
    "make_policy_gate",
    "tool_name",
    "screen_response",
    "handle",
    "build_app",
    "configure_deps",
    "ToolDeps",
    "never_submit",
    "never_assert_eligibility",
    "forbidden_tools",
    "GateDecision",
    "tick",
    "scheduled_handler",
    "MonitorDeps",
    "StoredProfile",
    "Snapshot",
    "Alert",
    "TickResult",
    "InMemorySnapshotStore",
    "FileSnapshotStore",
    "InMemoryProfileStore",
    "CollectingAlertSink",
]
