"""Reachable-path engine — the interpretation layer over the position engine.

Given a profile and the live draw cutoffs, answer the two questions the raw CRS
number cannot: *which* draws this profile clears right now, and for the ones it
doesn't, the shortest feasible move that would open them. This is what feeds the
dashboard and the alerting engine; it turns a score into a decision.

Scope of honesty:
  - General draws: everyone in the pool is eligible; compare CRS to the cutoff.
  - Category draws: French-language eligibility is derivable here (NCLC7 across
    abilities). Occupation-category eligibility needs IRCC's NOC list (Feature 1,
    not yet ingested), so it is either caller-asserted or reported as unknown —
    never guessed.
  - BC PNP: score SIRS, compare to the cutoff, surface the job-offer requirement,
    and note the +600 CRS a nomination adds (the guaranteed federal lever).

The "shortest move" catalog recomputes CRS deterministically under each single
lever; nothing here is estimated by a model. Pure functions, no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Callable, Optional

from crs import LanguageScores, Profile, crs
from pnp import PROVINCIAL_NOMINATION_CRS_BONUS, BCJobOffer, sirs_bc

EFFORT_ORDER = {"small": 0, "medium": 1, "large": 2}


# ------------------------------------------------------------------- data model
@dataclass(frozen=True)
class Draw:
    """One live draw a profile can be measured against. Cutoff is CRS for
    general/category draws, SIRS for pnp_bc. `source` is the citation (required
    by the trust posture — no uncited cutoff)."""
    kind: str                              # "general" | "category" | "pnp_bc"
    name: str
    cutoff: int
    date: date
    source: str                            # citation URL / doc id
    category: Optional[str] = None         # for kind=="category": "french" | occupation slug
    eligible_override: Optional[bool] = None  # caller-asserted eligibility (occupation categories)


@dataclass(frozen=True)
class MoveResult:
    move: str
    effort: str                            # "small" | "medium" | "large"
    new_score: int
    closes_gap: bool


@dataclass(frozen=True)
class PathResult:
    draw: Draw
    score_kind: str                        # "CRS" | "SIRS"
    your_score: int
    cutoff: int
    eligible: Optional[bool]               # None = eligibility not derivable (needs NOC list)
    eligibility_reason: str
    clears: bool
    gap: int                               # max(0, cutoff - your_score)
    closing_moves: list[MoveResult] = field(default_factory=list)
    # pnp_bc only:
    job_offer_required: Optional[bool] = None
    crs_bonus_if_nominated: Optional[int] = None


@dataclass(frozen=True)
class Reachability:
    as_of: date
    reachable: list[PathResult]            # eligible and clears now
    within_reach: list[PathResult]         # eligible, doesn't clear, but a move closes it
    blocked: list[PathResult]              # eligible, doesn't clear, no single move closes it
    needs_eligibility_check: list[PathResult]  # eligibility not derivable (occupation category)


# ---------------------------------------------------------------- move catalog
def _at_least(scores: LanguageScores, n: int) -> LanguageScores:
    return LanguageScores(
        max(scores.speaking, n), max(scores.listening, n),
        max(scores.reading, n), max(scores.writing, n),
    )


@dataclass(frozen=True)
class _Move:
    name: str
    effort: str
    applicable: Callable[[Profile], bool]
    apply: Callable[[Profile], Profile]


MOVES: list[_Move] = [
    _Move(
        "raise first language to CLB 9", "medium",
        lambda p: p.first_language.min_clb() < 9,
        lambda p: replace(p, first_language=_at_least(p.first_language, 9)),
    ),
    _Move(
        "raise first language to CLB 10", "large",
        lambda p: p.first_language.min_clb() < 10,
        lambda p: replace(p, first_language=_at_least(p.first_language, 10)),
    ),
    _Move(
        "add French second language at NCLC 7", "large",
        lambda p: not (p.second_language_is_french
                       and p.second_language is not None
                       and p.second_language.min_clb() >= 7),
        lambda p: replace(p, second_language=LanguageScores(7, 7, 7, 7),
                          second_language_is_french=True),
    ),
    _Move(
        "gain one more year of Canadian work", "large",
        lambda p: p.canadian_work_years < 5,
        lambda p: replace(p, canadian_work_years=p.canadian_work_years + 1),
    ),
    _Move(
        "secure a provincial nomination (+600)", "large",
        lambda p: not p.has_provincial_nomination,
        lambda p: replace(p, has_provincial_nomination=True),
    ),
]


def _closing_moves(profile: Profile, cutoff: int, as_of: Optional[date]) -> list[MoveResult]:
    """Single levers that lift CRS to >= cutoff, cheapest effort first."""
    results: list[MoveResult] = []
    for m in MOVES:
        if not m.applicable(profile):
            continue
        new = crs(m.apply(profile), as_of).total
        if new >= cutoff:
            results.append(MoveResult(m.name, m.effort, new, True))
    results.sort(key=lambda r: (EFFORT_ORDER[r.effort], -r.new_score))
    return results


# ----------------------------------------------------------------- eligibility
def _eligibility(profile: Profile, draw: Draw) -> tuple[Optional[bool], str]:
    if draw.kind == "general":
        return True, "all pool candidates are eligible"
    if draw.eligible_override is not None:
        return draw.eligible_override, "caller-asserted eligibility"
    if draw.category == "french":
        sl = profile.second_language
        ok = bool(profile.second_language_is_french and sl and sl.min_clb() >= 7)
        return ok, "French NCLC 7 across abilities" if ok else "needs French NCLC 7 across abilities"
    return None, "needs NOC-list check (occupation category not yet ingested)"


# ---------------------------------------------------------------------- public
def _evaluate(profile: Profile, draw: Draw, as_of: date,
              bc_offer: Optional[BCJobOffer]) -> PathResult:
    if draw.kind == "pnp_bc":
        r = sirs_bc(profile, bc_offer)
        eligible = r.eligible_to_register
        score = r.score
        clears = eligible and score >= draw.cutoff
        return PathResult(
            draw=draw, score_kind="SIRS", your_score=score, cutoff=draw.cutoff,
            eligible=eligible,
            eligibility_reason="registrable" if eligible else "BC job offer required to register",
            clears=clears, gap=max(0, draw.cutoff - score),
            job_offer_required=r.job_offer_required,
            crs_bonus_if_nominated=r.crs_bonus_if_nominated,
        )

    eligible, reason = _eligibility(profile, draw)
    score = crs(profile, as_of).total
    gap = max(0, draw.cutoff - score)
    clears = bool(eligible) and score >= draw.cutoff
    moves: list[MoveResult] = []
    if eligible and not clears:
        moves = _closing_moves(profile, draw.cutoff, as_of)
    return PathResult(
        draw=draw, score_kind="CRS", your_score=score, cutoff=draw.cutoff,
        eligible=eligible, eligibility_reason=reason, clears=clears, gap=gap,
        closing_moves=moves,
    )


def reachable_paths(profile: Profile, draws: list[Draw], as_of: Optional[date] = None,
                    bc_offer: Optional[BCJobOffer] = None) -> Reachability:
    """Classify every live draw for this profile: reachable now, within reach via
    a single move, blocked, or eligibility-unknown. `bc_offer` is the candidate's
    BC job offer (if any), used to score pnp_bc draws."""
    day = as_of or date.today()
    results = [_evaluate(profile, d, day, bc_offer) for d in draws]

    reachable, within, blocked, needs_check = [], [], [], []
    for r in results:
        if r.eligible is None:
            needs_check.append(r)
        elif r.clears:
            reachable.append(r)
        elif r.eligible and r.closing_moves:
            within.append(r)
        else:
            # eligible but no single CRS move closes it, or ineligible, or a
            # registrable-but-below-cutoff BC PNP standing (lever is a stronger offer)
            blocked.append(r)

    return Reachability(
        as_of=day, reachable=reachable, within_reach=within,
        blocked=blocked, needs_eligibility_check=needs_check,
    )
