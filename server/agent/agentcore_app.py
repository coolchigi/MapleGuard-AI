"""Module-level AgentCore Runtime entrypoint for `agentcore configure` / `agentcore deploy`.

AgentCore Runtime executes this file as a TOP-LEVEL SCRIPT (its `__package__` is empty), so a
relative import like `from .runtime import build_app` fails with "attempted relative import with no
known parent package" and the container crashes at startup (surfaced by the runtime as a generic
"initialization time exceeded"). To avoid that, put the server root (the parent of this `agent/`
directory) on `sys.path` and import `agent.runtime` ABSOLUTELY. That makes `agent` a real package,
so `runtime.py` and everything it pulls in can use their normal relative imports.

`runtime.build_app()` is import-cheap: creating the app and registering the handler does no network
I/O. The pinned Bedrock model, NOC clients, cited corpus, and tracing build once on the first
invocation and are cached, so the HTTP server answers AgentCore Runtime's /ping health check inside
the 30-second init window.

    cd server
    agentcore configure --entrypoint agent/agentcore_app.py
    agentcore deploy
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.runtime import build_app  # noqa: E402  (must follow the sys.path insert above)

app = build_app()

if __name__ == "__main__":  # pragma: no cover - runs only inside the AgentCore container
    app.run()
