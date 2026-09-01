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

import logging
from typing import Any, Optional

from .orchestrator import build_orchestrator, screen_response

logger = logging.getLogger("mapleguard.runtime")


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


def _shared_deploy_pieces(model: Any = None) -> dict:
    """The environment-selected orchestrator pieces built ONCE and reused across invocations:
    the pinned Bedrock model, the Bedrock-backed NOC clients, the cited corpus, and the trace
    attributes. Kept separate from Agent construction so `build_app` can build a fresh Agent per
    request (bleed-free) over these shared pieces without rebuilding the expensive ones.

    Every seam degrades safely: a missing SDK or failed backend leaves that piece unset rather
    than blocking hosting.
    """
    from .observability import DEFAULT_TRACE_ATTRIBUTES
    pieces: dict[str, Any] = {"trace_attributes": DEFAULT_TRACE_ATTRIBUTES}

    # Pin the hosted orchestrator's model so the first invoke never falls back to Strands'
    # shifting default (which asks Bedrock for a model the account may not have enabled). An
    # injected model (tests / offline) is respected.
    if model is None:
        try:
            from .config import build_bedrock_model
            model = build_bedrock_model()
        except Exception:  # pragma: no cover - strands is required in deploy; never block hosting
            logger.warning("could not build the pinned Bedrock model; using the SDK default")
            model = None
    pieces["model"] = model

    # Wire the two model-backed NOC tools to Bedrock, so audit/draft work on the deployed agent
    # with only AWS credentials (no ANTHROPIC_API_KEY). (None, None) if anthropic is absent.
    try:
        from .config import build_bedrock_noc_clients
        pieces["matcher"], pieces["corrector"], pieces["classifier"] = build_bedrock_noc_clients()
    except Exception:  # pragma: no cover - additive; a failure must not block hosting
        logger.warning("could not build Bedrock NOC clients; audit/draft will report unconfigured")

    # Cited corpus: Bedrock KB when MAPLEGUARD_MEMORY_BACKEND=bedrock_kb, else the offline store.
    try:
        from .config import Deployment, build_memory
        mem = build_memory(Deployment.from_env())
        if mem is not None:
            pieces["memory"], pieces["corpus"] = mem[0], mem[1]
    except Exception:  # pragma: no cover - memory is additive; a failure must not block hosting
        pass
    return pieces


def build_orchestrator_from_env(model: Any = None):
    """Build one orchestrator wired to the deploy backends the environment selects: the pinned
    Bedrock model, the Bedrock-backed NOC clients, the cited corpus, and the MapleGuard trace
    attributes. Session persistence is per request (see `build_app`), not baked into this shared
    agent. Never blocks a minimal deploy: any unavailable seam is simply left unset."""
    return build_orchestrator(**_shared_deploy_pieces(model))


def _session_manager_for(session_id: Optional[str], deployment: Any) -> Optional[Any]:
    """A per-caller Strands session manager for this request, or None. Keyed by the AgentCore
    session id so each caller's conversation/profile is isolated and (with the agentcore backend)
    restored from AgentCore Memory. Never fatal: a failure degrades to a stateless request."""
    if not session_id or getattr(deployment, "session_backend", None) == "none":
        return None
    try:
        from .config import build_session_manager
        return build_session_manager(session_id, deployment)
    except Exception:  # pragma: no cover - session persistence is additive
        logger.warning("session manager unavailable for session %s; running stateless", session_id)
        return None


def build_app(model: Any = None, from_env: bool = True):
    """Wrap the entrypoint in a `BedrockAgentCoreApp` for hosting. Requires AgentCore.

    Expensive backends (the pinned Bedrock model, NOC clients, seeded corpus) are built ONCE via
    `_shared_deploy_pieces`. Each invocation then builds a FRESH agent over those pieces, keyed by
    the caller's AgentCore session id, so conversation state never bleeds between callers and the
    per-user AgentCore Memory profile is restored when that backend is configured. Tracing is
    enabled so the loop is visible in CloudWatch GenAI Observability. Returns the app so the caller
    can `app.run()`.
    """
    try:
        from bedrock_agentcore.runtime import BedrockAgentCoreApp
    except ImportError as exc:  # pragma: no cover - deploy-time dependency
        raise RuntimeError(
            "bedrock_agentcore is required to host the agent on AgentCore Runtime. "
            "Install it (pip install bedrock-agentcore) or call `handle` directly."
        ) from exc

    app = BedrockAgentCoreApp()

    # Export MapleGuard's spans (stamped with the trust-posture attributes) to the OTLP collector
    # AgentCore Runtime provides via OTEL_EXPORTER_OTLP_ENDPOINT. Never blocks hosting.
    try:
        from .observability import enable_tracing
        enable_tracing(console=False)
    except Exception:  # pragma: no cover - tracing must never block hosting
        logger.warning("tracing setup failed; the agent runs untraced")

    pieces = _shared_deploy_pieces(model) if from_env else {"model": model}
    from .config import Deployment
    deployment = Deployment.from_env()

    @app.entrypoint
    def invoke(payload: dict, context: Any = None) -> dict:
        session_id = getattr(context, "session_id", None) or (payload or {}).get("session_id")
        session_manager = _session_manager_for(session_id, deployment)
        agent = build_orchestrator(session_manager=session_manager, **pieces)
        return handle(payload, agent=agent)

    app.invoke = invoke  # expose for direct testing of the wrapped handler
    return app


if __name__ == "__main__":  # pragma: no cover - runs only inside the AgentCore container
    build_app().run()
