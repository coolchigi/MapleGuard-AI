"""Optional agent-as-tool split: an advisor orchestrator over two specialists.

The default topology is the single flat orchestrator in `orchestrator.py`, and the concept
spec recommends keeping it that way unless a split genuinely simplifies. This module is the
one honest split the spec endorses: a **document auditor** (owns the NOC reference-letter
tools) and a **strategist** (owns the deterministic position engine), each a real Strands
`Agent`, exposed to the advisor orchestrator via the SDK's native `Agent.as_tool()`.

This is small, deliberate multi-agent, not a swarm and not agent-for-agent's-sake. Two
domains that read cleanly apart (paperwork vs position), one clear edge each (the advisor
calls a specialist and gets its answer back). Every specialist runs the SAME deterministic
tools and the SAME compute-and-refuse gates as the flat orchestrator, so the split adds a
separation of concerns without adding any place for the model to invent a number.

Model is injectable three ways so the team is testable offline: pass a single shared
`model` (the deploy path — a stateless Bedrock model is fine to share), or a `model_factory`
callable that mints a fresh model per agent (what the scripted-fake tests use, since a
stateful fake must not be shared across agents).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from .orchestrator import make_policy_gate
from .tools import NOC_TOOLS, POSITION_TOOLS, configure_deps

STRATEGIST_PROMPT = """\
You are MapleGuard's position strategist. You compute a candidate's Canadian immigration
position from the published government grids using your tools, and you explain it. You never
compute a number yourself, never assert eligibility, and never submit anything.

Call a tool for every value: compute_crs for the CRS, crs_trajectory / crs_deadlines for
the dated cliffs, sirs_bc for the BC PNP score, reachable_paths to classify draws, and
ingest_draws to parse an official rounds document you were given. Cite the source each tool
returns. State computed facts ("your CRS is 470", "you clear this cutoff") but never a
verdict on the person's eligibility. If a tool refuses a value or marks it unverified, say
so plainly rather than guessing.
"""

AUDITOR_PROMPT = """\
You are MapleGuard's document auditor. You audit an employer reference letter against the
published NOC 2021 occupation the candidate claims, and you draft a corrected letter for the
employer to sign. You report cited evidence; you do not decide the case.

Use audit_reference_letter to check the mandatory elements and score the duties against the
cited NOC text (show the duty-by-duty gaps), then draft_corrected_letter to produce a
revision that only describes supported work and leaves an explicit '[employer to confirm:
...]' gap for anything unsupported. Never state or imply the applicant is eligible for
anything, and never invent work. If the NOC text is not line-verified, say so.
"""

ADVISOR_PROMPT = """\
You are MapleGuard, an advisor for Canadian immigration (Express Entry and BC PNP). You do
not compute anything or read documents yourself. You route to two specialists and explain
their cited results in plain language:

- strategist: computes the candidate's position (CRS, trajectory and cliffs, BC SIRS,
  reachable paths against live cutoffs). Ask it for any number or draw classification.
- document_auditor: audits an employer reference letter against the cited NOC text and
  drafts a correction. Ask it whenever a letter or a specific occupation is involved.

Absolute rules that override everything: never assert eligibility (an officer decides; you
report cited facts only), and never draft or submit a government application. Always repeat
the citation a specialist returns. When unsure, say so rather than guessing.
"""


def _resolve_model(model: Any, model_factory: Optional[Callable[[], Any]]) -> Any:
    """A fresh model from the factory if given, else the shared model (possibly None)."""
    return model_factory() if model_factory is not None else model


def build_strategist(model: Any = None, model_factory: Optional[Callable[[], Any]] = None):
    """The position-engine specialist: a Strands Agent over POSITION_TOOLS."""
    from strands import Agent
    return Agent(
        name="strategist",
        description=("Computes a candidate's Canadian immigration position from the published "
                     "grids: CRS and its breakdown, the dated trajectory and cliffs, the BC "
                     "SIRS score, and which live draws are reachable. Never asserts eligibility."),
        model=_resolve_model(model, model_factory),
        system_prompt=STRATEGIST_PROMPT,
        tools=list(POSITION_TOOLS),
        hooks=[make_policy_gate()],
    )


def build_document_auditor(model: Any = None, matcher: Any = None, corrector: Any = None,
                           model_factory: Optional[Callable[[], Any]] = None):
    """The reference-letter specialist: a Strands Agent over NOC_TOOLS. Matcher/corrector are
    injected through the shared module-level tool deps (fakes offline, Claude clients live)."""
    from strands import Agent
    configure_deps(matcher=matcher, corrector=corrector)
    return Agent(
        name="document_auditor",
        description=("Audits an employer reference letter against the cited published NOC 2021 "
                     "text and drafts a corrected letter for the employer to sign. Reports cited "
                     "evidence; never decides eligibility."),
        model=_resolve_model(model, model_factory),
        system_prompt=AUDITOR_PROMPT,
        tools=list(NOC_TOOLS),
        hooks=[make_policy_gate()],
    )


def build_advisor_team(model: Any = None, matcher: Any = None, corrector: Any = None,
                       model_factory: Optional[Callable[[], Any]] = None):
    """Build the advisor orchestrator over the two specialists (agent-as-tool topology).

    The specialists are exposed with the SDK's native `Agent.as_tool()`, so the advisor's
    tool list is exactly two agent-tools (strategist, document_auditor). Every layer carries
    the same never-submit / never-assert gates. This is the optional split; the flat
    `orchestrator.build_orchestrator` remains the default.

    Args:
        model: A shared Strands model for all three agents (deploy path). None lets
            Strands/AgentCore supply the default at deploy.
        matcher / corrector: model-backed NOC clients (inject fakes offline).
        model_factory: If given, each agent is built from a fresh `model_factory()` instead
            of sharing `model` (needed for stateful fake models in tests).

    Returns:
        The advisor `strands.Agent`.
    """
    from strands import Agent

    strategist = build_strategist(model=model, model_factory=model_factory)
    auditor = build_document_auditor(model=model, matcher=matcher, corrector=corrector,
                                     model_factory=model_factory)
    return Agent(
        name="mapleguard_advisor",
        model=_resolve_model(model, model_factory),
        system_prompt=ADVISOR_PROMPT,
        tools=[strategist.as_tool(), auditor.as_tool()],
        hooks=[make_policy_gate()],
    )
