"""AgentCore Runtime entrypoint — the clean handler AgentCore hosts.

Amazon Bedrock AgentCore Runtime is how the Strands agent deploys to AWS without
hand-rolling the container, scaling, and tracing. It hosts a callable marked with
`@app.entrypoint`. This module provides that entrypoint and keeps it thin: build the
orchestrator, run the prompt, screen the answer through the never-assert-eligibility gate,
and return the result. The two policy gates run below the model on every request.

The `bedrock_agentcore` import is guarded so this module imports with no AWS SDK present:
`build_app()` raises a clear error if AgentCore is not installed, but `handle()` — the pure
request handler — runs anywhere a model is injected, which is what the offline tests use.
The hosting layer is a thin wrapper over `handle`, so AgentCore attaches later without
touching the orchestration logic.
"""
from __future__ import annotations

from typing import Any, Optional

from .orchestrator import build_orchestrator, screen_response


def handle(payload: dict, agent: Any = None, model: Any = None,
           include_trace: bool = True) -> dict:
    """Process one invocation. AWS-free and synchronous, so it is unit-testable offline.

    Args:
        payload: The request. Reads `prompt` (the user's message).
        agent: A prebuilt orchestrator to reuse. If None, one is built (with `model`).
        model: Model to build the agent with when `agent` is None (inject a fake offline).
        include_trace: Attach the agent-loop trace (which tools ran, cycle count) to the
            result. This is the observability proof surface — it shows every deterministic
            tool the loop executed to build the answer, so "the model computed nothing
            itself" is verifiable, not asserted. See agent/observability.py.

    Returns:
        {"result": <text>, "trace": {...}} on success, or
        {"blocked": True, "gate": ..., "reason": ...} when the never-assert-eligibility gate
        refuses the model's answer.
    """
    prompt = payload.get("prompt", "")
    if agent is None:
        agent = build_orchestrator(model=model)

    result = agent(prompt)
    text = _result_text(result)

    decision = screen_response(text)
    if not decision.allowed:
        return {"blocked": True, "gate": decision.gate, "reason": decision.reason}
    out = {"result": text}
    if include_trace:
        from .observability import agent_loop_trace
        out["trace"] = agent_loop_trace(result)
    return out


def _result_text(result: Any) -> str:
    """Pull plain text out of a Strands AgentResult (`.message` is a Message dict with
    content blocks), tolerating a plain string or object."""
    message = getattr(result, "message", result)
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        parts = [b.get("text", "") for b in message.get("content", []) if isinstance(b, dict)]
        return "".join(parts).strip() or str(message)
    return str(message)


def build_orchestrator_from_env(model: Any = None):
    """Build the orchestrator wired to the deploy backends the environment selects: the cited
    corpus (Bedrock KB when `MAPLEGUARD_MEMORY_BACKEND=bedrock_kb`, else the offline dev store)
    and the MapleGuard trace attributes, so a hosted instance retrieves + is traced without any
    code change. Session persistence per user is applied per request (AgentCore Memory keyed by
    the caller), not baked into the shared agent, so it is not wired here.

    Falls back to a plain orchestrator if the SDK/config is unavailable, so this never blocks a
    minimal deploy."""
    from .observability import DEFAULT_TRACE_ATTRIBUTES
    kwargs: dict[str, Any] = {"model": model, "trace_attributes": DEFAULT_TRACE_ATTRIBUTES}
    try:
        from .config import Deployment, build_memory
        mem = build_memory(Deployment.from_env())
        if mem is not None:
            kwargs["memory"], kwargs["corpus"] = mem[0], mem[1]
    except Exception:  # pragma: no cover - memory is additive; a failure must not block hosting
        pass
    return build_orchestrator(**kwargs)


def build_app(model: Any = None, from_env: bool = True):
    """Wrap the entrypoint in a `BedrockAgentCoreApp` for hosting. Requires AgentCore.

    The agent is built once and reused across invocations. `from_env=True` wires the
    environment-selected backends (see `build_orchestrator_from_env`); pass False (or inject a
    model) for a bare agent. Returns the app so the caller (`agent/agentcore_app.py`, a deploy
    script, or `__main__`) can `app.run()`.
    """
    try:
        from bedrock_agentcore.runtime import BedrockAgentCoreApp
    except ImportError as exc:  # pragma: no cover - deploy-time dependency
        raise RuntimeError(
            "bedrock_agentcore is required to host the agent on AgentCore Runtime. "
            "Install it (pip install bedrock-agentcore) or call `handle` directly."
        ) from exc

    app = BedrockAgentCoreApp()
    agent = build_orchestrator_from_env(model=model) if from_env else build_orchestrator(model=model)

    @app.entrypoint
    def invoke(payload: dict) -> dict:
        return handle(payload, agent=agent)

    app.invoke = invoke  # expose for direct testing of the wrapped handler
    return app


if __name__ == "__main__":  # pragma: no cover - runs only inside the AgentCore container
    build_app().run()
