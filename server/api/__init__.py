"""MapleGuard HTTP API (FastAPI) over the deterministic core + model-backed NOC audit/draft.

`create_app` is the factory (everything injectable for offline tests). `build_noc_model` wires
the NOC matcher/corrector to a real Claude model from the environment. Run for real with:

    cd server && MAPLEGUARD_NOC_BACKEND=anthropic ANTHROPIC_API_KEY=... \
        uvicorn api.asgi:app --reload

`create_app` is imported lazily (via module __getattr__) so `api.model_config` — which only
needs `noc`, not FastAPI/pydantic — is usable on its own (e.g. the prove_noc_draft script).
"""
from .model_config import NocModel, build_noc_model

__all__ = ["create_app", "build_noc_model", "NocModel"]


def __getattr__(name):
    if name == "create_app":
        from .app import create_app
        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
