"""The deterministic core, registered as orchestrator TOOLS.

Each function here is a thin wrapper: it deserializes the model's JSON arguments, calls a
pure function from the deterministic layer, and serializes the typed result back to a
JSON-safe dict that keeps every number and every citation the core produced. The model
NEVER computes any of these values; it calls the tool and reads the result. That is the
compute-and-refuse posture made mechanical.

The `@tool` decorator comes from the Strands SDK. It is imported behind a fallback so this
module (and the tests over it) import and run with or without Strands installed: without
Strands, `@tool` is an identity decorator and each wrapper is a plain callable; with
Strands, each is a registerable `DecoratedFunctionTool` that is still directly callable and
returns the same dict. Either way the wrappers are the single source of tool behaviour.

The two model-backed tools (letter audit and correction draft) take their model client
through an injected, module-level `ToolDeps`, so tests run offline with a fake and the
deterministic scoring/validation is exercised for real.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

try:  # Strands is the deploy-time dependency; absence must not break import or tests.
    from strands import tool
except ImportError:  # pragma: no cover - exercised only when Strands is not installed
    def tool(func=None, **_kwargs):  # type: ignore[misc]
        """Identity fallback for `strands.tool` so wrappers stay directly callable."""
        if func is None:
            return lambda f: f
        return func

from crs import crs
from crs.timeline import deadlines as _deadlines, trajectory as _trajectory
from ingest import parse_rounds_json, to_draws
from noc import LetterCorrector, LLMDutyMatcher, audit_letter, get_occupation
from pnp import sirs_bc as _sirs_bc

from . import serde
from .schemas import BCJobOfferInput, DrawInput, ProfileInput


# --------------------------------------------------------- injected model clients
@dataclass
class ToolDeps:
    """Model-backed dependencies for the two generative tools, plus the optional cited
    corpus. Defaults construct the real Claude-backed clients lazily (no key or network until
    first call); tests inject fakes. `corpus` is a memory store (TestMemoryStore in dev, a
    Bedrock KB in deploy); when set, audit citations are re-sourced from live retrieval."""
    matcher: Any = None       # noc.audit.DutyMatcher — proposes duty->sentence alignment
    corrector: Any = None     # noc.draft.LetterCorrector — drafts the corrected letter
    corpus: Any = None        # memory store for citation retrieval; None = seed citations
    classifier: Any = None    # ingest.PolicyChangeClassifier — extracts an IRCC policy change

    def get_matcher(self):
        if self.matcher is None:
            self.matcher = LLMDutyMatcher()
        return self.matcher

    def get_corrector(self):
        if self.corrector is None:
            self.corrector = LetterCorrector()
        return self.corrector

    def get_classifier(self):
        if self.classifier is None:
            from ingest import PolicyChangeClassifier
            self.classifier = PolicyChangeClassifier()
        return self.classifier


# Module-level deps the tools read. `configure_deps` swaps them (the orchestrator injects a
# shared instance; tests inject fakes). Kept as a singleton so the `@tool` wrappers, whose
# signatures the model sees, stay argument-free of infrastructure.
_DEPS = ToolDeps()


def configure_deps(matcher: Any = None, corrector: Any = None, corpus: Any = None,
                   classifier: Any = None) -> ToolDeps:
    """Point the model-backed tools at specific clients and the citation corpus (orchestrator
    wiring / tests)."""
    global _DEPS
    _DEPS = ToolDeps(matcher=matcher, corrector=corrector, corpus=corpus, classifier=classifier)
    return _DEPS


# --------------------------------------------------------------- deterministic tools
@tool
def compute_crs(profile: ProfileInput, as_of: Optional[str] = None) -> dict:
    """Compute a candidate's Comprehensive Ranking System (CRS) score from the published
    IRCC grid. Returns the total, the four block subtotals, and a per-factor breakdown.

    Args:
        profile: The candidate profile (education, first_language CLB per ability, age or
            date_of_birth, work years, nomination flags, and so on).
        as_of: Optional ISO date 'YYYY-MM-DD' to score as of (age is date-dependent).

    Returns:
        A dict with total, core, spouse, skill_transfer, additional, and breakdown[].
    """
    p = serde.profile_from_dict(profile)
    return serde.score_to_dict(crs(p, serde._parse_date(as_of)))


@tool
def crs_trajectory(profile: ProfileInput, start: str, end: str) -> dict:
    """Plot a candidate's CRS over a date range, with each dated cliff labelled (an
    age-bracket drop, a language-test expiry). The 'time machine' data. Needs a
    date_of_birth on the profile.

    Args:
        profile: The candidate profile (must include date_of_birth).
        start: ISO start date 'YYYY-MM-DD'.
        end: ISO end date 'YYYY-MM-DD'.

    Returns:
        A dict with points[] (date, total) and cliffs[] (date, kind, label, delta).
    """
    p = serde.profile_from_dict(profile)
    return serde.trajectory_to_dict(_trajectory(p, serde._parse_date(start), serde._parse_date(end)))


@tool
def crs_deadlines(profile: ProfileInput, as_of: Optional[str] = None) -> dict:
    """Return the dated events that move a candidate's CRS: upcoming age-bracket cliffs and
    the language-test expiry (after which in-pool language points drop to zero). Needs a
    date_of_birth on the profile.

    Args:
        profile: The candidate profile (must include date_of_birth).
        as_of: Optional ISO 'YYYY-MM-DD' to compute deadlines from (default today).

    Returns:
        A dict with age_cliffs[], test_expiry, and test_expiry_cliff.
    """
    p = serde.profile_from_dict(profile)
    return serde.deadlines_to_dict(_deadlines(p, serde._parse_date(as_of)))


@tool
def sirs_bc(profile: ProfileInput, offer: Optional[BCJobOfferInput] = None) -> dict:
    """Compute a candidate's BC PNP Skills Immigration Registration System (SIRS) score,
    out of 200, from the BC grid. Flags whether a BC job offer is required to register and
    notes the +600 CRS a provincial nomination adds.

    Args:
        profile: The candidate profile.
        offer: Optional BC job offer {hourly_wage, area, is_tech_exempt}.

    Returns:
        A dict with score, breakdown[], job_offer_required, eligible_to_register,
        crs_bonus_if_nominated.
    """
    p = serde.profile_from_dict(profile)
    return serde.sirs_to_dict(_sirs_bc(p, serde.bc_offer_from_dict(offer)))


@tool
def reachable_paths(profile: ProfileInput, draws: list[DrawInput], as_of: Optional[str] = None,
                    bc_offer: Optional[BCJobOfferInput] = None) -> dict:
    """Classify every live draw for this profile against its published cutoff: reachable
    now, within reach via a single ranked move, blocked, or eligibility-unknown (an
    occupation category that needs IRCC's NOC list). Each draw must carry a source citation.

    Args:
        profile: The candidate profile.
        draws: Live draws, each {kind, name, cutoff, date, source, category?, provenance?}.
            kind is 'general' | 'category' | 'pnp_bc'. Pass the draws straight from ingest_draws
            to carry each cutoff's full provenance (round number, per-round page, fetch date)
            through to the result. Any `eligible_override` in a draw is ignored here: the model
            may not assert a candidate's eligibility for a category draw; the engine decides that
            deterministically or reports it as needs_eligibility_check.
        as_of: Optional ISO 'YYYY-MM-DD' to evaluate as of.
        bc_offer: Optional BC job offer used to score pnp_bc draws.

    Returns:
        A dict with reachable[], within_reach[], blocked[], needs_eligibility_check[]. Each
        reported draw echoes its `provenance` when the input draw carried one.
    """
    from paths import reachable_paths as _reachable_paths
    p = serde.profile_from_dict(profile)
    # Trust posture: the model must never assert eligibility. `eligible_override` lets a caller
    # force a category draw's eligibility, so it is stripped from model-supplied draws here — the
    # engine determines eligibility or flags it needs_eligibility_check. (The pure `paths` API
    # still honours it for the deterministic ingest path, which the model does not author.)
    typed_draws = [serde.draw_from_dict({k: v for k, v in d.items() if k != "eligible_override"})
                   for d in draws]
    result = _reachable_paths(p, typed_draws, serde._parse_date(as_of),
                              serde.bc_offer_from_dict(bc_offer))
    out = serde.reachability_to_dict(result)
    return serde.attach_draw_provenance(out, draws)


@tool
def ingest_draws(rounds_json: str, source_url: Optional[str] = None) -> dict:
    """Parse an already-fetched IRCC 'rounds of invitations' JSON document into cited draw
    records. Every value is stamped with its source and round; a round whose cutoff or date
    cannot be parsed is flagged needs_manual_check and refused entry into the engine rather
    than guessed. This tool does no network I/O — pass the fetched document text in.

    Args:
        rounds_json: The raw JSON text of the IRCC rounds document.
        source_url: Optional citation URL the document was fetched from.

    Returns:
        A dict with draws[] (usable, cited draws ready for reachable_paths) and
        needs_manual_check[] (records refused because a field could not be parsed). Each usable
        draw carries `provenance` (source_url, round_number, per-round page, fetch date), which
        reachable_paths echoes onto the reported cutoff.
    """
    kwargs = {"source_url": source_url} if source_url else {}
    records = parse_rounds_json(rounds_json, **kwargs)
    to_draws(records)  # revalidate: raises if a usable record would build an uncited Draw
    draws = []
    for r in records:
        if r.needs_manual_check or r.cutoff is None:
            continue
        draws.append({
            "kind": r.kind, "name": r.name, "cutoff": r.cutoff,
            "date": r.date.isoformat(), "source": r.citation.source_url,
            "category": r.category, "round_number": r.round_number,
            "invitations": r.invitations,
            "provenance": r.citation.as_dict(),
        })
    flagged = [r.as_dict() for r in records if r.needs_manual_check]
    return {"draws": draws, "needs_manual_check": flagged}


# --------------------------------------------------------------- model-backed tools
@tool
def audit_reference_letter(letter_text: str, noc_code: str) -> dict:
    """Audit an employer reference letter against the published NOC 2021 occupation the
    candidate claims: check the mandatory elements of a valid letter, and score each of the
    letter's duties against the occupation's lead statement and main duties (the 80% bar an
    officer applies). Every flagged gap cites the exact NOC text. If the seeded NOC text is
    not yet line-verified, the report is stamped needs_verification. This reports cited
    evidence; it does not decide the case.

    Args:
        letter_text: The reference letter's full text.
        noc_code: The claimed NOC 2021 code, e.g. '21234'.

    Returns:
        The audit report dict (elements, duty coverage, cited gaps, verification flag).
    """
    occupation = get_occupation(noc_code)
    report = audit_letter(letter_text, occupation, _DEPS.get_matcher())
    out = report.to_dict()
    if _DEPS.corpus is not None:
        from .citations import cite_gaps_from_corpus
        out = cite_gaps_from_corpus(out, _DEPS.corpus)
    return out


@tool
def draft_corrected_letter(letter_text: str, noc_code: str,
                           supporting_facts: Optional[list] = None) -> dict:
    """Draft a corrected reference letter that aligns with the claimed NOC occupation, for
    the employer to review and sign. It only describes work supported by the original letter
    or the caller's attested supporting facts; any duty with no support is left as an
    explicit '[employer to confirm: ...]' gap rather than fabricated. It never states or
    implies eligibility. Run audit_reference_letter first to find the gaps.

    Args:
        letter_text: The original reference letter text.
        noc_code: The claimed NOC 2021 code.
        supporting_facts: Optional list of facts the caller attests the drafter may rely on.

    Returns:
        A dict with letter_text (the draft), placeholders[] (open gaps), and has_open_gaps.
    """
    occupation = get_occupation(noc_code)
    coverage = audit_letter(letter_text, occupation, _DEPS.get_matcher()).duties
    draft = _DEPS.get_corrector()(letter_text, occupation, coverage, supporting_facts or [])
    return {
        "letter_text": draft.letter_text,
        "placeholders": list(draft.placeholders),
        "has_open_gaps": draft.has_open_gaps,
    }


@tool
def classify_policy_change(update_text: str, source_url: str) -> dict:
    """Classify a single IRCC policy update into a validated, cited change record — the trigger the
    monitor routes on (e.g. a NOC 2016->TEER 2021 reclassification, or a CRS-weight change).

    Hybrid, determinism below the model: a model EXTRACTS {change_type, affected_noc_codes,
    affected_components, effective_date} from the update text, then a deterministic validator checks
    it against a strict schema and DROPS the extraction if anything is malformed (unknown type, a
    NOC change naming no valid 5-digit code, an unparseable date, a missing source). The model never
    computes a number; an unvalidated extraction is dropped, never patched.

    Args:
        update_text: The IRCC policy-update text (already fetched; this tool does no network I/O).
        source_url: The citation URL the update was fetched from (required; no uncited change).

    Returns:
        {"change": <validated change dict> | None, "validated": bool}. When `validated` is False the
        model's extraction did not pass the schema and was dropped.
    """
    from ingest import validate_policy_change
    raw = _DEPS.get_classifier()(update_text)
    change = validate_policy_change(raw, source_url)
    return {"change": change.to_dict() if change else None, "validated": change is not None}


# Tool groupings. POSITION_TOOLS is the deterministic position engine (the strategist's
# kit); NOC_TOOLS is the reference-letter work (the document auditor's kit). The flat
# MAPLEGUARD_TOOLS is their union, handed to the single orchestrator. The two subsets exist
# so an optional agent-as-tool split (agent/team.py) can give each specialist its own kit
# without changing tool behaviour. Order is stable and documented.
POSITION_TOOLS = [
    compute_crs,
    crs_trajectory,
    crs_deadlines,
    sirs_bc,
    reachable_paths,
    ingest_draws,
]
NOC_TOOLS = [
    audit_reference_letter,
    draft_corrected_letter,
]
# Policy-watch tools: classify an IRCC update into a validated, routable change.
POLICY_TOOLS = [
    classify_policy_change,
]
MAPLEGUARD_TOOLS = POSITION_TOOLS + NOC_TOOLS + POLICY_TOOLS
