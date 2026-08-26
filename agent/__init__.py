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
from .gates import GateDecision, forbidden_tools, never_assert_eligibility, never_submit
from .orchestrator import (SYSTEM_PROMPT, build_orchestrator, make_policy_gate,
                           screen_response, tool_name)
from .runtime import build_app, handle
from .team import (build_advisor_team, build_document_auditor, build_strategist)
from .tools import (MAPLEGUARD_TOOLS, NOC_TOOLS, POSITION_TOOLS, ToolDeps, configure_deps)

__all__ = [
    "build_orchestrator",
    "build_advisor_team",
    "build_strategist",
    "build_document_auditor",
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
]
