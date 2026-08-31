"""Wire the NOC matcher/corrector to a real Claude model at the API entrypoint, keyed by env.

The deterministic scoring in `noc/audit.py` is pure and always runs. The two model-backed
steps (duty->sentence matching, and drafting the corrected letter) call Claude. `noc/matcher.py`
and `noc/draft.py` create the Anthropic client lazily and accept an injected client, so importing
them needs no key and tests inject fakes. This module is the one place the API decides which
real client to build, from the environment, so nothing else in the server hardcodes a backend.

Backends (env `MAPLEGUARD_NOC_BACKEND`, default auto):
  - `anthropic` : `anthropic.Anthropic()` (needs `ANTHROPIC_API_KEY`).
  - `bedrock`   : `anthropic.AnthropicBedrock()` (needs AWS creds + Bedrock model access).
  - `auto`      : bedrock if `MAPLEGUARD_NOC_BACKEND` unset and AWS creds look present and no
                  `ANTHROPIC_API_KEY`; otherwise anthropic if `ANTHROPIC_API_KEY` is set;
                  otherwise unconfigured (the model endpoints return 503 until a key is set).

The bright line is unchanged: the model matches and drafts; it never computes a score or
asserts eligibility. The deterministic scorer and the `validate_alignment` guard still run over
whatever the model returns, and unsupported duties stay `[employer to confirm: ...]` gaps.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from noc import DEFAULT_MODEL, LetterCorrector, LLMDutyMatcher

# Env override for the model id (defaults per backend, see below).
MODEL_ENV = "MAPLEGUARD_NOC_MODEL"
BACKEND_ENV = "MAPLEGUARD_NOC_BACKEND"

# The default backend and model. We default to Bedrock (one AWS credential covers the agent
# runtime and this model call) with Sonnet 4.5 — the low-cost choice for this per-letter
# extraction, deliberately not an Opus-tier model. DEFAULT_BEDROCK_MODEL is the cross-region
# inference-profile id: it must match the one enabled on your Bedrock model-access page, so
# adjust the date stamp or region prefix (or set MAPLEGUARD_NOC_MODEL) if yours differs.
DEFAULT_BACKEND = "bedrock"
DEFAULT_BEDROCK_MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


@dataclass(frozen=True)
class NocModel:
    """The NOC model clients plus a status the /health endpoint can report."""
    matcher: Optional[Any]
    corrector: Optional[Any]
    configured: bool
    backend: str
    model: str
    detail: str = ""


def _looks_like_bedrock(env: dict) -> bool:
    return bool(env.get("AWS_ACCESS_KEY_ID") or env.get("AWS_PROFILE")
               or env.get("AWS_ROLE_ARN") or env.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"))


def _build_client(backend: str):
    """Construct the Anthropic client for `backend`. Imported lazily so the server imports with
    no `anthropic` package installed (the model endpoints then report unconfigured)."""
    import anthropic  # raises ImportError if absent -> caller maps to unconfigured
    if backend == "bedrock":
        return anthropic.AnthropicBedrock()
    return anthropic.Anthropic()


def build_noc_model(env: Optional[dict] = None) -> NocModel:
    """Decide the backend from the environment and build the matcher + corrector, sharing one
    client. Never raises: if no backend is configured (or `anthropic` is missing), returns a
    NocModel with `configured=False` and a reason, so the API can answer 503 with a clear
    message instead of crashing at startup."""
    e = os.environ if env is None else env
    override = e.get(MODEL_ENV)
    backend = e.get(BACKEND_ENV, DEFAULT_BACKEND).lower()

    if backend == "auto":
        if e.get("ANTHROPIC_API_KEY"):
            backend = "anthropic"
        elif _looks_like_bedrock(e):
            backend = "bedrock"
        else:
            return NocModel(None, None, False, "auto", override or DEFAULT_BEDROCK_MODEL,
                            "no ANTHROPIC_API_KEY and no AWS credentials detected")

    # Model default depends on the resolved backend: Bedrock needs the inference-profile id,
    # the Anthropic API needs the plain id (noc's DEFAULT_MODEL, also Sonnet 4.5).
    model = override or (DEFAULT_BEDROCK_MODEL if backend == "bedrock" else DEFAULT_MODEL)

    if backend == "anthropic" and not e.get("ANTHROPIC_API_KEY"):
        return NocModel(None, None, False, backend, model, "ANTHROPIC_API_KEY is not set")

    try:
        client = _build_client(backend)
    except ImportError:
        return NocModel(None, None, False, backend, model,
                        "the 'anthropic' package is not installed")
    except Exception as exc:  # pragma: no cover - client construction is env-dependent
        return NocModel(None, None, False, backend, model, f"client init failed: {exc}")

    return NocModel(
        matcher=LLMDutyMatcher(model=model, client=client),
        corrector=LetterCorrector(model=model, client=client),
        configured=True, backend=backend, model=model,
    )
