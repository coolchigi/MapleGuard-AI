"""ASGI entrypoint for `uvicorn api.asgi:app`.

Builds the app with the NOC model resolved from the environment (see api.model_config). Kept
separate from `create_app` so tests build their own app with injected fakes and never trigger
the environment-driven model construction.
"""
from .app import create_app

app = create_app()
