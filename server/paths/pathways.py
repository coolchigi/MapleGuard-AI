"""Eligibility / pathways service: what a candidate qualifies for, before they have to dig.

The motivating case is real: a CRS 474 candidate who never knew French-category draws sit far
lower, or that their occupation was in-category for a stream. The raw material to answer this
already exists in the codebase, it was just never surfaced as one view:

  - `ingest.categories` holds all ten 2026 category rules with cited NOC lists and the French
    NCLC-7 rule, and `category_eligibility()` gives a deterministic, cited verdict per category.
  - `crs` computes the score; `paths.reach` holds the single-lever move catalog.

`eligible_pathways` composes those into ONE cited pathways map across every Express Entry pathway
(the general pool, the ten category-based selections, and BC PNP), DECOUPLED from whether a draw is
running right now. That decoupling is the point: "you are in-category for French" is useful even in a
week with no French draw.

Honesty boundary (inherited from `ingest.categories`): a positive verdict is the NARROW official
test (occupation is in-category, or NCLC 7 is met), never a claim of overall PR eligibility, which
is IRCC's call. Each category also carries official conditions this layer does not verify (the
`additional_requirements` string), so they travel with every verdict. Missing input gives
eligible=None ("cannot decide"), never a guess.

Pure and deterministic: no I/O, no model. The optional `draws` enrich each pathway with the standing
against its latest cited cutoff; without them the map is eligibility-only, still useful.

This one service is the single relevance engine: a person's relevant pathways are exactly the ones
it reports them eligible for (or one move from), so the user surface, the monitor, and the consultant
view all read relevance from cited rules rather than any hand-written table.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from crs import Profile, crs
from pnp import BCJobOffer, mpnp_points, oinp_standing, sinp_points, sirs_bc

from .reach import Draw, closing_moves


@dataclass(frozen=True)
class PathwayStanding:
    """One pathway's cited verdict for a candidate, plus their standing against its latest draw.

    `eligible` is the narrow official test: True (in-category / meets the language rule), False
    (not in the published list / below NCLC 7), or None (cannot decide without more input). It is
    never a claim of overall PR eligibility. `latest_*` and the score fields are populated only when
    a recent cited draw for this pathway was supplied.
    """
    slug: str
    title: str
    rule_kind: str                       # "language" | "noc_list" | "general" | "pnp"
    eligible: Optional[bool]
    eligibility_reason: str
    source_url: str
    source_date: str                     # ISO date of the cited rule
    additional_requirements: str = ""    # official conditions this layer does NOT verify
    score_kind: str = "CRS"              # "CRS" | "SIRS"
    your_score: Optional[int] = None
    latest_cutoff: Optional[int] = None
    latest_draw_date: Optional[str] = None
    latest_draw_source: Optional[str] = None
    clears: Optional[bool] = None        # eligible AND score >= latest cutoff
    gap: Optional[int] = None            # max(0, cutoff - score) when a cutoff is known
    closing_moves: tuple = ()            # single levers that would close the gap, cheapest first
    note: str = ""                       # pathway-specific caveat (e.g. BC PNP job-offer lever)

    def to_dict(self) -> dict:
        return {
            "slug": self.slug, "title": self.title, "rule_kind": self.rule_kind,
            "eligible": self.eligible, "eligibility_reason": self.eligibility_reason,
            "source_url": self.source_url, "source_date": self.source_date,
            "additional_requirements": self.additional_requirements,
            "score_kind": self.score_kind, "your_score": self.your_score,
            "latest_cutoff": self.latest_cutoff, "latest_draw_date": self.latest_draw_date,
            "latest_draw_source": self.latest_draw_source, "clears": self.clears, "gap": self.gap,
            "closing_moves": list(self.closing_moves), "note": self.note,
        }


@dataclass(frozen=True)
class PathwaysMap:
    """Every pathway's standing for one candidate, plus the shortlist they qualify for."""
    as_of: str
    crs_total: int
    pathways: tuple = ()

    def qualifying(self) -> list[str]:
        """Slugs whose narrow official test the candidate currently meets (eligible is True)."""
        return [p.slug for p in self.pathways if p.eligible is True]

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of, "crs_total": self.crs_total,
            "qualifying": self.qualifying(),
            "pathways": [p.to_dict() for p in self.pathways],
        }


def _french_nclc(profile: Profile) -> int:
    """The candidate's French level as a second language (min across abilities), or 0 when they
    have no French second-language result. The profile fully describes ability, so 'no French' is a
    determinate 0 (below NCLC 7), never 'unknown'."""
    sl = profile.second_language
    return sl.min_clb() if (profile.second_language_is_french and sl) else 0


def _latest_draw_for(draws: list, *, category_slug: Optional[str] = None,
                     kind: Optional[str] = None):
    """The most recent supplied Draw matching a category slug (via the canonical resolver) or a
    draw kind. Returns the Draw or None. Newest by date."""
    from ingest.categories import resolve_category
    matches = []
    for d in draws or []:
        if kind is not None and d.kind == kind:
            matches.append(d)
        elif category_slug is not None and resolve_category(d.category or d.name) == category_slug:
            matches.append(d)
    return max(matches, key=lambda d: d.date) if matches else None


def _move_to_dict(m) -> dict:
    return {"move": m.move, "effort": m.effort, "new_score": m.new_score,
            "closes_gap": m.closes_gap}


def _standing(profile: Profile, crs_total: int, eligible: Optional[bool], draw: Optional[Draw],
              as_of: Optional[date]) -> dict:
    """Standing fields for a pathway given its latest draw (or none). Only computes closing moves
    when the candidate is eligible and below the cutoff, so we never suggest moves for a pathway
    they are not in."""
    if draw is None:
        return {"your_score": crs_total}
    clears = bool(eligible) and crs_total >= draw.cutoff
    gap = max(0, draw.cutoff - crs_total)
    moves = ()
    if eligible and not clears:
        moves = tuple(_move_to_dict(m) for m in closing_moves(profile, draw.cutoff, as_of))
    return {
        "your_score": crs_total, "latest_cutoff": draw.cutoff,
        "latest_draw_date": draw.date.isoformat(), "latest_draw_source": draw.source,
        "clears": clears, "gap": gap, "closing_moves": moves,
    }


def eligible_pathways(profile: Profile, draws: Optional[list] = None,
                      as_of: Optional[date] = None,
                      bc_offer: Optional[BCJobOffer] = None) -> PathwaysMap:
    """The cited pathways map for a candidate: the general pool, the ten category-based selections,
    and BC PNP, each with its official eligibility verdict and (when a recent draw is supplied) the
    standing against its latest cutoff and the shortest move that would close the gap.

    `draws` are typed `paths.Draw` (convert tool/API dicts via `agent.serde.draw_from_dict`); omit
    them for an eligibility-only map. Pure and deterministic.
    """
    from ingest.categories import (CATEGORY_RULES, CANONICAL_SLUGS, CATEGORY_SOURCE_URL,
                                   category_eligibility)
    day = as_of or date.today()
    crs_total = crs(profile, day).total
    french_clb = _french_nclc(profile)
    pathways: list[PathwayStanding] = []

    # 1. The general pool: everyone in Express Entry is eligible for general draws (none have run
    # since 2024, but the standing is still honest if a general draw is supplied).
    gen_draw = _latest_draw_for(draws, kind="general")
    gen_stand = _standing(profile, crs_total, True, gen_draw, day)
    pathways.append(PathwayStanding(
        slug="general", title="General Express Entry pool", rule_kind="general",
        eligible=True, eligibility_reason="all Express Entry candidates are in the general pool",
        source_url=CATEGORY_SOURCE_URL, source_date=str(day),
        your_score=gen_stand.get("your_score"), latest_cutoff=gen_stand.get("latest_cutoff"),
        latest_draw_date=gen_stand.get("latest_draw_date"),
        latest_draw_source=gen_stand.get("latest_draw_source"),
        clears=gen_stand.get("clears"), gap=gen_stand.get("gap"),
        closing_moves=gen_stand.get("closing_moves", ()),
    ))

    # 2. The ten 2026 category-based selections, each a deterministic cited verdict.
    for slug in CANONICAL_SLUGS:
        rule = CATEGORY_RULES[slug]
        if slug == "french":
            elig = category_eligibility(slug, french_nclc=french_clb)
        else:
            elig = category_eligibility(slug, noc_code=profile.noc_code)
        draw = _latest_draw_for(draws, category_slug=slug)
        stand = _standing(profile, crs_total, elig.eligible, draw, day)
        pathways.append(PathwayStanding(
            slug=slug, title=rule.title, rule_kind=rule.rule_kind,
            eligible=elig.eligible, eligibility_reason=elig.reason,
            source_url=elig.source_url, source_date=str(elig.source_date),
            additional_requirements=elig.additional_requirements,
            your_score=stand.get("your_score"), latest_cutoff=stand.get("latest_cutoff"),
            latest_draw_date=stand.get("latest_draw_date"),
            latest_draw_source=stand.get("latest_draw_source"),
            clears=stand.get("clears"), gap=stand.get("gap"),
            closing_moves=stand.get("closing_moves", ()),
        ))

    # 3. BC PNP (SIRS): a separate scoring system. Report registrability, the job-offer requirement,
    # and the +600 CRS a nomination adds (the guaranteed federal lever). A live SIRS cutoff comes
    # from the provincial source, not the federal feed, so it is only shown if a pnp_bc draw is given.
    sirs = sirs_bc(profile, bc_offer)
    pnp_draw = _latest_draw_for(draws, kind="pnp_bc")
    pnp_clears = sirs.eligible_to_register and (pnp_draw is not None
                                                and sirs.score >= pnp_draw.cutoff)
    pathways.append(PathwayStanding(
        slug="bc-pnp", title="BC Provincial Nominee Program (SIRS)", rule_kind="pnp",
        eligible=sirs.eligible_to_register,
        eligibility_reason=("registrable in the BC PNP pool" if sirs.eligible_to_register
                            else "a BC job offer is required to register in most BC PNP streams"),
        source_url=CATEGORY_SOURCE_URL, source_date=str(day),
        score_kind="SIRS", your_score=sirs.score,
        latest_cutoff=(pnp_draw.cutoff if pnp_draw else None),
        latest_draw_date=(pnp_draw.date.isoformat() if pnp_draw else None),
        latest_draw_source=(pnp_draw.source if pnp_draw else None),
        clears=(pnp_clears if pnp_draw else None),
        gap=(max(0, pnp_draw.cutoff - sirs.score) if pnp_draw else None),
        note=(f"a provincial nomination adds +{sirs.crs_bonus_if_nominated} CRS, the strongest "
              "single lever, but it is not something you can grant yourself"),
    ))

    # 4. Saskatchewan (SINP): a real computed score from the official SINP points grid, like BC.
    # We score Factor I (education, work, language, age); the Saskatchewan-connection points and the
    # occupation-demand-driven draws are not modelled, so meeting the 60 floor is entry to the pool,
    # never an invitation. `eligible` is True only when Factor I alone clears 60, else None.
    sinp = sinp_points(profile, as_of=day)
    pathways.append(PathwayStanding(
        slug="pnp-saskatchewan", title="Saskatchewan Immigrant Nominee Program (SINP)",
        rule_kind="pnp", eligible=sinp.meets_points_floor,
        eligibility_reason=(f"SINP Factor I score {sinp.factor_one} of {sinp.factor_one_max} "
                            f"(needs {sinp.minimum} total to submit an EOI)"
                            + ("; clears the floor on labour-market points alone"
                               if sinp.meets_points_floor
                               else "; a Saskatchewan connection could still reach the floor")),
        source_url=sinp.source_url, source_date=sinp.source_date.isoformat(),
        additional_requirements=("Saskatchewan-connection points (family, past SK work/study, or a "
                                 "SK job offer) are not assessed here; invitations select by "
                                 "in-demand occupation through EOI draws"),
        score_kind="SINP points", your_score=sinp.factor_one,
        note=("meeting the 60-point floor enters the EOI pool, it is not an invitation; SINP draws "
              "select on in-demand occupation and provincial need and can change at any time"),
    ))

    # 5. Ontario (OINP): rebuilt June 2026 into the single Ontario Workforce Priority Stream, which
    # requires a permanent Ontario job offer on every pathway (self-employed physicians aside). We
    # check the published skill floors from the profile and state the job-offer gate; eligibility
    # stays None because it turns on a job offer we do not collect, never faked.
    from ingest.provinces import EE_NOMINATION_CRS_BONUS, pnp_programs_eligibility_only
    oinp = oinp_standing(profile, as_of=day)
    pathways.append(PathwayStanding(
        slug="pnp-ontario", title="Ontario Immigrant Nominee Program (OINP)", rule_kind="pnp",
        eligible=None, eligibility_reason=oinp.reason,
        source_url=oinp.source_url, source_date=oinp.source_date.isoformat(),
        additional_requirements=("a full-time permanent Ontario job offer is required on every "
                                 "Workforce Priority pathway (self-employed physicians excepted)"),
        score_kind="none", your_score=None,
        note=(f"a provincial nomination adds +{EE_NOMINATION_CRS_BONUS} CRS; OINP's former Express "
              "Entry pool streams were removed in the June 2026 redesign"),
    ))

    # 6. Manitoba (MPNP): a computed score from the official self-assessment grid (Factors 1-4:
    # language, age, work, education, max 75). A Manitoba connection (Factor 5) is MANDATORY and we
    # do not collect it, so eligibility stays None regardless of the subtotal, never faked.
    mpnp = mpnp_points(profile, as_of=day)
    pathways.append(PathwayStanding(
        slug="pnp-manitoba", title="Manitoba Provincial Nominee Program (MPNP)", rule_kind="pnp",
        eligible=None,
        eligibility_reason=(f"MPNP self-assessment Factors 1-4 (language, age, work, education) = "
                            f"{mpnp.factors_1_4} of {mpnp.factors_1_4_max}; you need {mpnp.minimum} "
                            "total AND a mandatory Manitoba connection (close relative, past MB "
                            "work/study, or a recruitment invitation), which we do not assess"),
        source_url=mpnp.source_url, source_date=mpnp.source_date.isoformat(),
        additional_requirements=("a Manitoba connection is required of all applicants; without one "
                                 "you are ineligible regardless of points"),
        score_kind="MPNP points", your_score=mpnp.factors_1_4,
        note=(f"a provincial nomination adds +{EE_NOMINATION_CRS_BONUS} CRS; Manitoba's 1000-point "
              "Expression-of-Interest ranking is a separate draw pool with no published pass mark"),
    ))

    # 7a. Alberta (AAIP): a job-offer / Worker EOI gate model, like Ontario. AAIP's worker streams
    # mostly require an Alberta job offer and employer requirements, and selection through the
    # Alberta Express Entry Stream is by Alberta's own Worker Expression of Interest, so eligibility
    # stays None rather than faking a verdict.
    pathways.append(PathwayStanding(
        slug="pnp-alberta", title="Alberta Advantage Immigration Program (AAIP)", rule_kind="pnp",
        eligible=None,
        eligibility_reason=("Alberta nominates through the AAIP. Its worker streams (Tourism and "
                            "Hospitality, Alberta Opportunity, Alberta Express Entry, and Rural "
                            "Renewal) mostly require an Alberta job offer and employer requirements, "
                            "and the Alberta Express Entry Stream selects candidates from the "
                            "federal Express Entry pool through a Worker Expression of Interest. "
                            "Selection is set by Alberta, so eligibility is not decided here"),
        source_url="https://www.alberta.ca/alberta-advantage-immigration-program",
        source_date=day.isoformat(),
        additional_requirements=("most AAIP worker streams require an Alberta job offer and "
                                 "employer requirements; the Express Entry stream selects from the "
                                 "federal pool by Alberta's own criteria"),
        score_kind="none", your_score=None,
        note=(f"a provincial nomination adds +{EE_NOMINATION_CRS_BONUS} CRS; AAIP publishes no "
              "candidate self-score grid, selection is by an Alberta job offer or the Alberta "
              "Express Entry Worker EOI"),
    ))

    # 7b. Nova Scotia (NSNP): a discretionary EOI-draw gate model, like Ontario. Since February 2026
    # it runs consolidated streams selected from an Expression of Interest pool in periodic,
    # priority-based draws, not a candidate score, so eligibility stays None rather than faking a
    # verdict.
    pathways.append(PathwayStanding(
        slug="pnp-nova-scotia", title="Nova Scotia Nominee Program (NSNP)", rule_kind="pnp",
        eligible=None,
        eligibility_reason=("Nova Scotia nominates through the NSNP. Since February 2026 it runs "
                            "consolidated streams (Skilled Worker, Nova Scotia Graduate, "
                            "Entrepreneur, and Nova Scotia: Express Entry): you submit an "
                            "Expression of Interest to a stream and Nova Scotia selects from the "
                            "pool in periodic, priority-based draws. Selection is discretionary "
                            "(labour-market need, occupation and sector priorities, retention), not "
                            "a candidate score, so eligibility is not decided here"),
        source_url="https://liveinnovascotia.com/nova-scotia-nominee-program",
        source_date=day.isoformat(),
        additional_requirements=("selection is by discretionary EOI draws on provincial priorities, "
                                 "and for the Express Entry stream by a Notice of Interest in the "
                                 "federal pool; entering the pool does not guarantee selection"),
        score_kind="none", your_score=None,
        note=(f"a provincial nomination adds +{EE_NOMINATION_CRS_BONUS} CRS; NSNP publishes no "
              "candidate self-score grid, selection is by priority-based EOI draws"),
    ))

    # 7. Every other nominating province/territory, cited. Their streams have their own criteria we
    # do not model here, so eligibility is honestly undecided (None), but the one federal fact we
    # can state deterministically is the +600 CRS an enhanced (Express Entry-aligned) nomination
    # adds. This covers the whole country instead of BC alone, without inventing a verdict.
    for pnp in pnp_programs_eligibility_only():
        pathways.append(PathwayStanding(
            slug=f"pnp-{pnp.slug}", title=pnp.program, rule_kind="pnp",
            eligible=None,
            eligibility_reason=(f"{pnp.province} nominates through the {pnp.program}. Its streams set "
                                "their own criteria, so eligibility is checked on the province's "
                                "site, not decided here"),
            source_url=pnp.source_url, source_date=pnp.source_date.isoformat(),
            additional_requirements="each stream has its own eligibility rules and intake",
            score_kind="none", your_score=None,
            note=(f"a nomination through an enhanced (Express Entry-aligned) stream adds "
                  f"+{EE_NOMINATION_CRS_BONUS} CRS, effectively guaranteeing an invitation"),
        ))

    return PathwaysMap(as_of=day.isoformat(), crs_total=crs_total, pathways=tuple(pathways))
