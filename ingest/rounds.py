"""Fetch and parse IRCC's official Express Entry "rounds of invitations" feed.

IRCC publishes every round as a single JSON file on canada.ca. This module keeps the
network fetch thin and separate from the parsing, so the parser can be tested against a
saved fixture with no network, and a Browser/agent layer can swap in as the fetcher later.

Parsing is pure and deterministic. It never guesses: a field it cannot parse (a
non-numeric CRS cutoff, a malformed date, a missing round number) produces a record flagged
``needs_manual_check`` rather than a fabricated value.

Source (chosen for this build):
    https://www.canada.ca/content/dam/ircc/documents/json/ee_rounds_123_en.json
This is the machine-readable feed behind IRCC's public "rounds of invitations" page. Each
round is cited back to its human-verifiable page at .../express-entry-rounds/invitations.html?q=<round>.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import List, Optional, Tuple

from .models import DrawCitation, DrawRecord

# The machine-readable feed and the human-facing per-round page.
ROUNDS_JSON_URL = "https://www.canada.ca/content/dam/ircc/documents/json/ee_rounds_123_en.json"
ROUND_PAGE_BASE = ("https://www.canada.ca/en/immigration-refugees-citizenship/corporate/mandate/"
                   "policies-operational-instructions-agreements/ministerial-instructions/"
                   "express-entry-rounds/invitations.html?q=")

# Draw-name buckets. "general" = anyone in the pool is measured on CRS; everything else is
# narrower ("category") and its eligibility is not decided here.
_GENERAL_NAMES = {"general", "no program specified"}


def _clean_int(raw: Optional[str]) -> Optional[int]:
    """Parse an integer that may carry thousands separators. None if not a clean number."""
    if raw is None:
        return None
    digits = re.sub(r"[,\s]", "", str(raw))
    return int(digits) if re.fullmatch(r"\d+", digits) else None


def _parse_date(raw: Optional[str]) -> Optional[date]:
    if raw and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw.strip()):
        try:
            return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _slugify(name: str) -> str:
    # Drop the trailing version / year qualifier, then slugify what names the category.
    head = re.split(r"[,(]", name, maxsplit=1)[0]
    head = re.sub(r"\b\d{4}\b|version\s*\d+|-\s*version", "", head, flags=re.IGNORECASE)
    slug = re.sub(r"[^a-z0-9]+", "-", head.strip().lower()).strip("-")
    return slug


def classify(name: str) -> Tuple[str, Optional[str], str]:
    """Map an official draw name to (kind, category, note).

    - general / no-program-specified pool draws -> ("general", None)
    - French proficiency draws                  -> ("category", "french")
    - federal Provincial Nominee Program draws  -> ("category", "provincial-nominee") + caveat
    - program-specific draws (CEC / FSW / FST)   -> ("category", <slug>) + caveat
    - named occupation categories               -> ("category", <slug>)
    """
    n = " ".join(name.split()).lower()
    if n in _GENERAL_NAMES:
        return "general", None, ""
    if "french" in n:
        return "category", "french", ""
    if "provincial nominee" in n:
        return ("category", "provincial-nominee",
                "federal PNP-restricted draw: eligibility is holding a nomination, not decided here")
    if "canadian experience" in n or "federal skilled" in n:
        return ("category", _slugify(name),
                "program-restricted draw: eligibility is narrower than all-program general")
    return "category", _slugify(name), ""


def parse_round(raw: dict, source_url: str, fetched: date) -> DrawRecord:
    """Parse one round dict into a cited DrawRecord, flagging anything unparseable."""
    number = str(raw.get("drawNumber", "")).strip()
    name = " ".join(str(raw.get("drawName", "")).split())
    dt = _parse_date(raw.get("drawDate"))
    cutoff = _clean_int(raw.get("drawCRS"))
    invitations = _clean_int(raw.get("drawSize"))

    problems: List[str] = []
    if not number:
        problems.append("missing round number")
    if not name:
        problems.append("missing draw name")
    if dt is None:
        problems.append(f"unparseable date {raw.get('drawDate')!r}")
    if cutoff is None:
        problems.append(f"unparseable CRS cutoff {raw.get('drawCRS')!r}")
    if invitations is None:
        problems.append(f"unparseable invitations {raw.get('drawSize')!r}")

    kind, category, caveat = classify(name) if name else ("category", None, "")
    notes = "; ".join(problems + ([caveat] if caveat else []))

    citation = DrawCitation(
        source_url=source_url, fetched=fetched, round_number=number or "(unknown)",
        round_url=(ROUND_PAGE_BASE + number) if number else "",
    )
    return DrawRecord(
        round_number=number or "(unknown)",
        date=dt or date.min,
        kind=kind, name=name, category=category,
        cutoff=cutoff, invitations=invitations, citation=citation,
        needs_manual_check=bool(problems), notes=notes,
    )


def parse_rounds(payload: dict, source_url: str = ROUNDS_JSON_URL,
                 fetched: Optional[date] = None) -> List[DrawRecord]:
    """Parse a full feed payload ({"rounds": [...]}) into cited DrawRecords."""
    day = fetched or date.today()
    rounds = payload.get("rounds", []) if isinstance(payload, dict) else []
    return [parse_round(r, source_url, day) for r in rounds]


def parse_rounds_json(text: str, source_url: str = ROUNDS_JSON_URL,
                      fetched: Optional[date] = None) -> List[DrawRecord]:
    """Parse a raw JSON string (as fetched) into cited DrawRecords."""
    return parse_rounds(json.loads(text), source_url, fetched)


def to_draws(records: List[DrawRecord]):
    """The engine-ready ``paths.Draw`` list, skipping any record flagged for manual check.

    Flagged records are dropped here rather than coerced -- a guessed cutoff must never
    reach the engine. Inspect the dropped ones via their ``needs_manual_check`` flag.
    """
    return [r.to_draw() for r in records if not r.needs_manual_check]


def fetch_rounds_json(url: str = ROUNDS_JSON_URL, timeout: float = 30.0) -> str:
    """Thin network fetch: return the raw JSON text of the rounds feed.

    Deliberately separate from parsing so tests never touch the network and a Browser/agent
    fetcher can replace this later. Not called by any test.
    """
    from urllib.request import Request, urlopen  # local import keeps the module import-light

    req = Request(url, headers={"User-Agent": "MapleGuard/ingest (+https://mapleguard)"} )
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed canada.ca https URL
        return resp.read().decode("utf-8")
