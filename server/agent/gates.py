"""Policy gates — deterministic guards that sit BELOW the model.

MapleGuard's trust posture has two non-negotiable rules. The system prompt tells the
model to obey them, but a prompt is a request, not a guarantee. These functions make the
guarantee: they are pure, deterministic checks that run in code, so a rule violation is
blocked whether or not the model cooperated. This is the Cedar/Policy layer, expressed as
plain Python so it runs and is testable with no AWS and no network.

  never-submit             No tool may file, submit, or lodge a government application.
                           The human submits, always. We prepare up to the button.
  never-assert-eligibility No message may state an immigration eligibility verdict
                           ("you are eligible / you qualify for PR"). We compute cited
                           facts and comparisons; the officer decides eligibility.

Scope note on never-assert: the engine legitimately computes derivable, cited facts such
as "you clear this cutoff" or "French NCLC 7 met". Those are comparisons against published
numbers, not legal conclusions, and are allowed. What is refused is the model concluding
that the *person* is eligible for, qualifies for, or is guaranteed a program, visa,
nomination, or permanent residence. The distinction is the whole product.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GateDecision:
    """A gate's verdict on one proposed action. `allowed=False` must block."""
    allowed: bool
    gate: str            # "never_submit" | "never_assert_eligibility"
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


# --------------------------------------------------------------- never-submit
# Any tool whose name signals filing an application to a government system is forbidden.
# We deliberately register no such tool; this gate ensures that if one were ever added
# (by mistake or by a compromised prompt), the call is refused before it runs.
# Lowercase-letter lookarounds (not \b) so snake_case tool names like "submit_application"
# and "file_ee" are matched — an underscore is a word char, so \b would not split them.
_L = r"(?<![a-z])"   # no lowercase letter before
_R = r"(?![a-z])"    # no lowercase letter after
_SUBMISSION_INTENT = re.compile(
    _L + r"(?:submit|efile|e-file|lodge|transmit)" + _R
    + r"|" + _L + r"file" + _R
    + r"|" + _L + r"apply" + _R
    + r"|" + _L + r"send_application" + _R
    + r"|" + _L + r"upload_to_ircc" + _R
    + r"|" + _L + r"create_application" + _R,
    re.IGNORECASE,
)


def never_submit(tool_name: str) -> GateDecision:
    """Gate a tool call by name. Refuses anything that would submit/file an application."""
    if _SUBMISSION_INTENT.search(tool_name or ""):
        return GateDecision(
            allowed=False,
            gate="never_submit",
            reason=(f"tool {tool_name!r} looks like it files or submits a government "
                    "application; MapleGuard prepares artifacts, the human submits"),
        )
    return GateDecision(True, "never_submit", "tool does not submit an application")


def forbidden_tools(tool_names) -> list[str]:
    """Return the names in `tool_names` that the never-submit gate would block. Used at
    agent-build time to refuse constructing an orchestrator that carries a submit tool."""
    return [n for n in tool_names if not never_submit(n).allowed]


# ------------------------------------------------------ never-assert-eligibility
# Coarse, deterministic backstop over model text. The prompt is the primary control and a
# production deployment layers Bedrock Guardrails on top; this catches the blunt verdicts.
# It targets a conclusion about THE PERSON's eligibility/qualification for a program, not
# the engine's cited comparisons ("you clear the cutoff", "CRS is 470").
_SUBJECT = r"(?:you|you're|you are|the applicant|the candidate|they)"
_PROGRAM = (r"(?:express entry|permanent residence|pr\b|a nomination|the nomination|"
            r"this draw|the draw|this category|the program|a visa|citizenship|cec|pnp)")

_ELIGIBILITY_VERDICT = re.compile(
    r"\b" + _SUBJECT + r"\s+(?:are|is|'re)?\s*(?:not\s+)?(?:definitely|certainly|clearly)?\s*"
    r"(?:eligible|ineligible|qualified)\b"
    r"|" + _SUBJECT + r"\s+(?:do|does)\s+(?:not\s+)?qualif(?:y|ies)\b"
    r"|" + _SUBJECT + r"\s+qualif(?:y|ies)\s+for\s+" + _PROGRAM +
    r"|" + _SUBJECT + r"\s+(?:will|are\s+guaranteed\s+to)\s+(?:be\s+)?(?:invited|selected|approved|nominated)\b"
    r"|\bguarantee(?:d|s)?\s+(?:you|your)\s+(?:an?\s+)?(?:invitation|ita|nomination|approval|pr)\b",
    re.IGNORECASE,
)


def never_assert_eligibility(text: str) -> GateDecision:
    """Gate a piece of model-authored text. Refuses an immigration eligibility verdict."""
    match = _ELIGIBILITY_VERDICT.search(text or "")
    if match:
        return GateDecision(
            allowed=False,
            gate="never_assert_eligibility",
            reason=(f"text states an eligibility verdict ({match.group(0).strip()!r}); "
                    "MapleGuard reports cited facts and refuses eligibility conclusions"),
        )
    return GateDecision(True, "never_assert_eligibility", "no eligibility verdict asserted")
