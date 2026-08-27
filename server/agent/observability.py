"""Observability as the PROOF SURFACE for the agent loop.

MapleGuard's trust story is "the model orchestrates, deterministic tools compute". Tracing
is how that becomes inspectable: a trace shows which tools ran, in what order, and how many
model cycles it took to answer, so a judge can SEE that a number came from a tool call, not
from the model's prose. It is the agent-loop counterpart to the Code Interpreter proof
surface for the math.

Two levels, both real, one offline:
  - `agent_loop_trace(result)` reads the `EventLoopMetrics` every Strands `AgentResult`
    already carries (`result.metrics`) and returns a compact, JSON-safe record of the tools
    that ran and the cycle count. No AWS, no exporter, no setup. This is the offline proof
    surface and what the tests assert on.
  - `enable_tracing(...)` wires Strands' OpenTelemetry export. `console` prints real spans
    locally (offline, for dev). `otlp_endpoint` ships them to a collector (AgentCore Runtime
    provides one, feeding CloudWatch GenAI Observability); see docs/agentcore-runbook.md.

Strands is imported lazily so this module imports with or without the SDK. Verified against
strands-agents 1.54.0: `StrandsTelemetry().setup_console_exporter()/setup_otlp_exporter()`,
`AgentResult.metrics` is an `EventLoopMetrics` with `.get_summary()`.
"""
from __future__ import annotations

from typing import Any, Optional

# Trace attributes stamped on the agent's spans, so every trace is identifiable as
# MapleGuard's and carries the trust posture as metadata.
DEFAULT_TRACE_ATTRIBUTES = {
    "service.name": "mapleguard-advisor",
    "mapleguard.posture": "compute-and-refuse",
}


def enable_tracing(console: bool = True, otlp_endpoint: Optional[str] = None,
                   meter: bool = False) -> Any:
    """Configure Strands OpenTelemetry tracing and return the `StrandsTelemetry` handle.

    `console=True` registers a console span exporter (real spans, no AWS) for dev. Pass
    `otlp_endpoint` to also export to a collector (set it, or rely on the standard
    `OTEL_EXPORTER_OTLP_ENDPOINT` env var that AgentCore Runtime injects). `meter=True` also
    starts metric collection. Requires the Strands SDK.
    """
    from strands.telemetry import StrandsTelemetry

    telemetry = StrandsTelemetry()
    if console:
        telemetry.setup_console_exporter()
    if otlp_endpoint is not None:
        telemetry.setup_otlp_exporter(endpoint=otlp_endpoint)
    elif not console:
        # No explicit endpoint and no console: fall back to the env-configured OTLP exporter
        # (AgentCore Runtime sets OTEL_EXPORTER_OTLP_ENDPOINT).
        telemetry.setup_otlp_exporter()
    if meter:
        telemetry.setup_meter()
    return telemetry


def agent_loop_trace(result: Any) -> dict:
    """A compact, JSON-safe trace of one agent invocation, read from the metrics the SDK
    already collected on `result.metrics`. No AWS, no exporter.

    Returns:
        {
          "cycles": <model round-trips>,
          "tools": [{"name", "call_count", "success_count", "error_count", "total_time"}, ...],
          "tool_sequence": ["compute_crs", ...],   # tools that ran, most-called first
          "duration": <total seconds>,
        }
    This is the proof surface: `tools` shows every deterministic tool the loop executed to
    build its answer, so "the model computed nothing itself" is verifiable, not asserted.
    """
    metrics = getattr(result, "metrics", None)
    if metrics is None or not hasattr(metrics, "get_summary"):
        return {"cycles": 0, "tools": [], "tool_sequence": [], "duration": 0.0}

    summary = metrics.get_summary()
    tools = []
    for name, entry in summary.get("tool_usage", {}).items():
        stats = entry.get("execution_stats", {})
        tools.append({
            "name": name,
            "call_count": stats.get("call_count", 0),
            "success_count": stats.get("success_count", 0),
            "error_count": stats.get("error_count", 0),
            "total_time": stats.get("total_time", 0.0),
        })
    tools.sort(key=lambda t: t["call_count"], reverse=True)
    return {
        "cycles": summary.get("total_cycles", 0),
        "tools": tools,
        "tool_sequence": [t["name"] for t in tools],
        "duration": summary.get("total_duration", 0.0),
    }


def format_loop_trace(result: Any) -> str:
    """Strands' own human-readable metrics rendering for one invocation (the tree of cycles,
    tool calls, and token usage), for logs and the demo. Falls back to a one-line summary if
    the richer renderer is unavailable."""
    metrics = getattr(result, "metrics", None)
    if metrics is None:
        return "no metrics on result"
    try:
        from strands.telemetry import metrics_to_string
        return metrics_to_string(metrics)
    except Exception:  # pragma: no cover - renderer is best-effort
        trace = agent_loop_trace(result)
        return f"{trace['cycles']} cycles, tools: {', '.join(trace['tool_sequence']) or 'none'}"
