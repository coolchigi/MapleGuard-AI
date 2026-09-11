"""The Provincial Nominee Program (PNP) registry: every province and territory that nominates,
each cited, so the pathways map covers the whole country instead of BC alone.

Honesty model (the same "flag it, do not fake it" rule the rest of MapleGuard follows):
each PNP runs its own streams with its own criteria, and those criteria vary by stream and change
often. We do NOT invent a per-candidate verdict for a stream we have not modelled. What we CAN
state deterministically, from the official federal source, is the mechanism that matters most: a
nomination through an "enhanced" (Express Entry-aligned) stream adds +600 CRS, which in practice
guarantees an invitation. So every province appears with its cited program and that +600 lever, and
its stream-specific eligibility is reported as "cannot decide without the province's criteria"
(eligible=None), never guessed.

Depth today:
- British Columbia is modelled with a real score (the SIRS grid, see `pnp/bc.py`).
- Every other province/territory is modelled at the program + mechanism level, cited, with
  eligible=None until its streams are modelled. Saskatchewan and Manitoba publish EOI points grids
  that are the natural next depth to add (sourced, not invented).

Quebec and Nunavut are intentionally absent: they run no PNP (Quebec selects through its own Arrima
system). Source: canada.ca "How the Provincial Nominee Program works".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# The official federal source for the program list and the two-pathway (+600) mechanism.
PNP_SOURCE_URL = ("https://www.canada.ca/en/immigration-refugees-citizenship/services/"
                  "immigrate-canada/provincial-nominees/works.html")
PNP_SOURCE_DATE = date(2026, 9, 11)

# A nomination via an enhanced (Express Entry-aligned) stream adds this many CRS points. Sourced
# from the federal page above ("get 600 extra points"). This is the deterministic fact we can state
# for every province with an enhanced stream, regardless of the stream's own selection rules.
EE_NOMINATION_CRS_BONUS = 600


@dataclass(frozen=True)
class PNP:
    """One province/territory's nominee program, cited. `modelled` is True where pathways builds a
    dedicated, province-specific entry for it (BC SIRS score, Saskatchewan SINP score, Ontario's
    job-offer eligibility gate); the rest are shown at the program + citation level."""
    slug: str
    province: str
    program: str
    modelled: bool = False
    source_url: str = PNP_SOURCE_URL
    source_date: date = PNP_SOURCE_DATE
    verified: bool = True


# The eleven nominating provinces/territories (canada.ca). British Columbia carries its own SIRS
# score in `pnp/bc.py`; it is flagged modelled_with_score so pathways uses that entry, not a
# duplicate stub here.
PNP_PROGRAMS: dict[str, PNP] = {
    "alberta": PNP("alberta", "Alberta", "Alberta Advantage Immigration Program (AAIP)"),
    "british-columbia": PNP("british-columbia", "British Columbia",
                            "BC Provincial Nominee Program (BC PNP)", modelled=True),
    "manitoba": PNP("manitoba", "Manitoba", "Manitoba Provincial Nominee Program (MPNP)",
                    modelled=True),
    "new-brunswick": PNP("new-brunswick", "New Brunswick",
                         "New Brunswick Provincial Nominee Program (NBPNP)"),
    "newfoundland-labrador": PNP("newfoundland-labrador", "Newfoundland and Labrador",
                                 "Newfoundland and Labrador Provincial Nominee Program (NLPNP)"),
    "northwest-territories": PNP("northwest-territories", "Northwest Territories",
                                 "Northwest Territories Nominee Program (NTNP)"),
    "nova-scotia": PNP("nova-scotia", "Nova Scotia", "Nova Scotia Nominee Program (NSNP)"),
    "ontario": PNP("ontario", "Ontario", "Ontario Immigrant Nominee Program (OINP)", modelled=True),
    "prince-edward-island": PNP("prince-edward-island", "Prince Edward Island",
                                "Prince Edward Island Provincial Nominee Program (PEI PNP)"),
    "saskatchewan": PNP("saskatchewan", "Saskatchewan",
                        "Saskatchewan Immigrant Nominee Program (SINP)", modelled=True),
    "yukon": PNP("yukon", "Yukon", "Yukon Nominee Program (YNP)"),
}

# Provinces/territories that run NO PNP, so we never imply one exists.
NO_PNP = {"quebec": "Quebec (selects through its own Arrima system)", "nunavut": "Nunavut"}


def pnp_programs_eligibility_only() -> list[PNP]:
    """Every PNP that pathways shows at the program + citation level, i.e. the ones without a
    dedicated province-specific entry (BC, Saskatchewan and Ontario have one, so they are excluded
    here and added by pathways directly). Sorted by province for stable order."""
    return sorted((p for p in PNP_PROGRAMS.values() if not p.modelled),
                  key=lambda p: p.province)
