"""Module-level AgentCore Runtime entrypoint for `agentcore configure` / `agentcore launch`.

The AgentCore starter toolkit hosts a module that exposes a `BedrockAgentCoreApp` at module
scope with a `@app.entrypoint` handler. `runtime.build_app()` builds exactly that (wiring the
environment-selected backends and the two policy gates); this module just exposes it as `app`
so the CLI can find it:

    cd server
    agentcore configure --entrypoint agent/agentcore_app.py
    agentcore launch

Importing this module constructs the real Strands agent and requires `bedrock_agentcore` +
`strands`, so it is NEVER imported by the package `__init__` or the tests — it is only imported
inside the AgentCore container. The offline request logic lives in `runtime.handle`, which is
tested with a fake model and no AWS.
"""
from .runtime import build_app

app = build_app()

if __name__ == "__main__":  # pragma: no cover - runs only inside the AgentCore container
    app.run()
