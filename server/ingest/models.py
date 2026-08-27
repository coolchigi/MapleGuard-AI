"""Typed, cited records for ingested Express Entry draw data.

Every record carries a citation (where the value came from, when it was fetched, which
round it is) because the trust posture forbids an uncited cutoff anywhere in the system. A
round whose cutoff, date, or number cannot be parsed is not guessed: it is flagged
``needs_manual_check`` and refused entry into the engine until a human resolves it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from paths import Draw


@dataclass(frozen=True)
class DrawCitation:
    """Provenance for one ingested draw value."""
    source_url: str          # the dataset the value was actually read from
    fetched: date            # when we fetched it
    round_number: str        # official round id (usually numeric, but e.g. "91a"/"91b" exist)
    round_url: str = ""      # human-verifiable per-round page, when derivable

    def as_dict(self) -> dict:
        return {"source_url": self.source_url, "fetched": self.fetched.isoformat(),
                "round_number": self.round_number, "round_url": self.round_url}


@dataclass(frozen=True)
class DrawRecord:
    """One parsed round of invitations, mapped toward ``paths.Draw`` and fully cited.

    ``kind`` is best-effort from the official draw name: "general" for all-program /
    no-program-specified pool draws, "category" for everything narrower (French, a named
    occupation category, or a program/PNP-restricted draw). This federal feed never yields
    "pnp_bc" -- BC SIRS draws come from the provincial source, not here.
    """
    round_number: str
    date: date
    kind: str                       # "general" | "category"
    name: str                       # the official draw name, verbatim
    category: Optional[str]         # normalized slug for category draws; None for general
    cutoff: Optional[int]           # CRS cutoff; None when unparseable (then needs_manual_check)
    invitations: Optional[int]      # invitations issued; None when unparseable
    citation: DrawCitation
    needs_manual_check: bool = False
    notes: str = ""                 # why flagged, and any classification caveats

    def to_draw(self) -> Draw:
        """Convert to the engine's ``paths.Draw``.

        Refuses (raises) when the record is flagged: a record with an unparsed cutoff must
        never enter the engine wearing a guessed number. Filter with ``needs_manual_check``
        or use ``ingest.to_draws`` first.
        """
        if self.needs_manual_check or self.cutoff is None:
            raise ValueError(
                f"round {self.round_number} needs manual check, refusing to build a Draw: "
                f"{self.notes or 'unparsed field'}")
        return Draw(kind=self.kind, name=self.name, cutoff=self.cutoff, date=self.date,
                    source=self.citation.source_url, category=self.category)

    def as_dict(self) -> dict:
        return {
            "round_number": self.round_number, "date": self.date.isoformat(),
            "kind": self.kind, "name": self.name, "category": self.category,
            "cutoff": self.cutoff, "invitations": self.invitations,
            "needs_manual_check": self.needs_manual_check, "notes": self.notes,
            "citation": self.citation.as_dict(),
        }
