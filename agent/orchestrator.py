"""The MapleGuard orchestrator — one Strands agent over the deterministic tools.

This is a single orchestrator, not a swarm. The flow is knowable (compute a position,
explain it, audit a letter), so one agent that calls typed tools is simpler and easier to
trust than emergent multi-agent handoff. The agent's only powers are to orchestrate,
explain, and draft: every number comes from a tool, every claim carries the citation the
tool returned, and two policy gates below the model block the two things it must never do.

Strands is imported lazily inside `build_orchestrator`, so this module (the system prompt,
the gate provider factory, the helpers) imports and is testable with or without the SDK.
Model and tools are injectable, so the same orchestrator runs against a fake model offline
and a Bedrock model on AgentCore with no code change.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from .gates import forbidden_tools, never_assert_eligibility, never_submit
from .tools import MAPLEGUARD_TOOLS, configure_deps

SYSTEM_PROMPT = """\
You are MapleGuard, an assistant for Canadian immigration (Express Entry and BC PNP). Your
entire value is that you compute from published government grids and refuse to guess. You
orchestrate, explain, and draft. You never do arithmetic yourself and you never give legal
advice.

Absolute rules, in order of importance:

1. NEVER compute a CRS or SIRS number, a breakdown, a trajectory, a reachable-path result,
   or a letter audit yourself. Call the matching tool for every number and every
   classification. If a tool is unavailable, say so; do not estimate.

2. NEVER assert eligibility. Do not tell a person they are eligible, ineligible, qualify,
   do not qualify, or are guaranteed an invitation, a nomination, or permanent residence.
   An officer decides eligibility. You may state cited, computed facts the tools return
   ("your CRS is 470", "you clear this draw's cutoff of 468", "French NCLC 7 is met"),
   because those are comparisons against published numbers, not a verdict on the person.

3. NEVER draft or submit a government application, and never fill or send an IRCC form. You
   prepare artifacts up to the submit button; the human reviews and submits. You may draft
   a corrected employer reference letter (a private document for the employer to sign),
   because that is not a government filing.

4. CITE every value. Each number and each flagged gap comes from a tool result that carries
   its source. Repeat that citation when you state the value. If something is not verified
   (a tool marks needs_verification or needs_manual_check), say so plainly and do not
   present it as settled.

How to work: read the user's situation, call the tools to compute their position, then
explain the results in plain language with the citations attached. When a letter is
involved, audit it first, show the duty-by-duty gaps against the cited NOC text, and offer
the corrected draft. When you are unsure, or a tool refuses a value, report that honestly
rather than filling the gap with a guess. Silence on eligibility is correct; the math and
the citation are what you provide.
"""


def tool_name(t: Any) -> str:
    """A tool's registered name whether it is a Strands DecoratedFunctionTool (`.tool_name`)
    or a plain fallback function (`.__name__`)."""
    name = getattr(t, "tool_name", None)
    if name:
        return name
    return getattr(t, "__name__", str(t))


def make_policy_gate():
    """Build the Strands hook provider that enforces the never-submit gate on every tool
    call, below the model. Imported lazily so the module needs no SDK to import.

    Returns a `HookProvider` that, on `BeforeToolCallEvent`, runs the deterministic
    `never_submit` gate against the selected tool's name and cancels the call if it is a
    submission action. The decision logic lives in `gates.py`; this only adapts it to the
    SDK's hook lifecycle.
    """
    from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

    class MapleGuardPolicyGate(HookProvider):
        """never-submit, wired as a pre-tool-call gate. never-assert-eligibility guards
        model TEXT and is applied by the runtime over the final response (see runtime.py)."""

        def register_hooks(self, registry: "HookRegistry", **_kwargs: Any) -> None:
            registry.add_callback(BeforeToolCallEvent, self._before_tool_call)

        def _before_tool_call(self, event: "BeforeToolCallEvent") -> None:
            name = ""
            if event.selected_tool is not None:
                name = getattr(event.selected_tool, "tool_name", "") or ""
            if not name:
                name = (event.tool_use or {}).get("name", "")
            decision = never_submit(name)
            if not decision.allowed:
                event.cancel_tool = f"blocked by policy ({decision.gate}): {decision.reason}"

    return MapleGuardPolicyGate()


def assert_no_forbidden_tools(tools: Iterable[Any]) -> None:
    """Refuse to build an orchestrator that carries a submission tool (defence in depth: the
    hook would also block the call at runtime, but a submit tool must never be registered)."""
    bad = forbidden_tools(tool_name(t) for t in tools)
    if bad:
        raise ValueError(
            f"refusing to register submission tools {bad}: MapleGuard never submits "
            "applications (the human does). Remove them before building the orchestrator."
        )


def build_orchestrator(model: Any = None, tools: Optional[list] = None,
                       matcher: Any = None, corrector: Any = None,
                       system_prompt: Optional[str] = None,
                       memory: Any = None, session_manager: Any = None,
                       state: Any = None):
    """Construct the MapleGuard Strands agent.

    Args:
        model: A Strands model (or model id). None lets Strands/AgentCore supply the default
            Bedrock model at deploy time. Inject a fake model to run offline.
        tools: Tool list. Defaults to `MAPLEGUARD_TOOLS`.
        matcher: A `noc.DutyMatcher` for the audit tools (inject a fake to run offline).
        corrector: A `noc.LetterCorrector` for the draft tool (inject a fake to run offline).
        system_prompt: Override the compute-and-refuse prompt (defaults to `SYSTEM_PROMPT`).
        memory: A `strands.memory.MemoryManager` for the cited corpus (see agent/memory.py).
            None disables retrieval.
        session_manager: A Strands session manager for conversation/state persistence
            (FileSessionManager dev, S3SessionManager deploy). None disables persistence.
        state: Initial per-user state (the profile dict) for `agent.state`.

    Returns:
        A configured `strands.Agent`. Requires the Strands SDK at call time.
    """
    from strands import Agent

    tools = MAPLEGUARD_TOOLS if tools is None else tools
    assert_no_forbidden_tools(tools)
    configure_deps(matcher=matcher, corrector=corrector)
    gate = make_policy_gate()
    kwargs: dict[str, Any] = {}
    if memory is not None:
        kwargs["memory_manager"] = memory
    if session_manager is not None:
        kwargs["session_manager"] = session_manager
    if state is not None:
        kwargs["state"] = state
    return Agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt or SYSTEM_PROMPT,
        hooks=[gate],
        **kwargs,
    )


def build_dev_orchestrator(session_id: str, profile: Optional[dict] = None, model: Any = None,
                           matcher: Any = None, corrector: Any = None,
                           storage_dir: Optional[str] = None):
    """The fully-offline dev stack in one call: the orchestrator wired to a seeded
    `TestMemoryStore` (cited NOC corpus) and a `FileSessionManager`, with the candidate
    profile in `agent.state`. No AWS. This is the demo/dev assembly; swap the backends via
    `config.Deployment` for deploy.

    Requires the Strands SDK. `profile` is the candidate profile dict the tools consume.
    """
    from .config import Deployment, build_memory, build_session_manager

    config = Deployment(session_dir=storage_dir)  # defaults: dev memory + file sessions
    mem = build_memory(config)
    return build_orchestrator(
        model=model, matcher=matcher, corrector=corrector,
        memory=mem[0] if mem else None,
        session_manager=build_session_manager(session_id, config),
        state={"profile": profile} if profile else None,
    )


def screen_response(text: str):
    """Apply the never-assert-eligibility gate to a final response string. Returns the
    `GateDecision`; the runtime calls this before emitting the model's answer, so an
    eligibility verdict is blocked deterministically even if the prompt failed to prevent
    it. Kept here (not in the hook) because this gate guards TEXT, not tool calls."""
    return never_assert_eligibility(text)
