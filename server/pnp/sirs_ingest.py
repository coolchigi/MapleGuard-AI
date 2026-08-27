"""Research/ingestion for the BC PNP SIRS points grid — fetch, parse, and RECONCILE.

The SIRS band tables in `pnp/bc.py` are marked `verified=False`: their structure and maxes are
confirmed, but the exact point bands are a best-effort transcription of the BC PNP Program
Guide. An unverified band is a "wrong number on stage" risk. This module is the deterministic
path that closes it, mirroring `ingest/rounds.py`:

  1. FETCH the published grid text (thin, injectable, separated from parsing so tests never
     touch the network). The autonomous research agent's fetcher is the AgentCore Browser tool
     (`BcPnpBrowserFetcher`); dev injects a fixture reader.
  2. PARSE the extracted grid text into cited band records. Pure and deterministic. A value it
     cannot parse is flagged `needs_manual_check`, never guessed.
  3. RECONCILE the parsed official grid against the in-code bands. This is the honest closer:
     a band is treated as verified ONLY when the source exactly matches what the engine scores
     against. Any disagreement is surfaced as a mismatch for a human to resolve — the source is
     never silently read into the engine, and the engine's number is never silently trusted
     over the source.

THE BRIGHT LINE (same as the KB and the draw ingest): the deterministic parser owns the
numbers; nothing the Browser or the model "reads" becomes a score without this parse + the
reconcile check. Reconciliation reports; it does not mutate `pnp/bc.py`. Flipping a band's
`verified` flag stays a human step taken once a live fetch confirms it (see the runbook), so
this module makes verification possible and auditable without ever fabricating the confirmation.

What is import-verified vs docs-derived (bedrock-agentcore 1.22.0):
  - verified: `BrowserClient.start/stop/generate_ws_headers/generate_live_view_url`,
    `browser_session`. The Browser primitive is wired authentically.
  - docs-derived (needs a live browser to confirm): the CDP/WebSocket navigation and grid
    extraction that turns the live page into normalized grid text. That step is an injected
    `page_reader` callable (a Playwright-over-CDP driver at deploy), NOT faked here. The parser
    and reconcile run offline against a structural fixture instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Optional

from . import bc as B

# The official source to confirm the bands against. The SIRS points criteria live in the BC
# PNP Program Guide / WelcomeBC SIRS pages. Marked as the target URL; confirm the exact live
# location during provisioning (the fetcher takes a url, so this is a default, not a hardcode).
BC_PNP_SIRS_URL = "https://www.welcomebc.ca/immigrate-to-b-c/skills-immigration-registration-system-sirs"

# The in-code tables this module reconciles against, by section name. Sections mirror
# `pnp.bc.FACTOR_MAX`. Two sections use string keys (education, area); the rest use int keys.
_INT_KEY_SECTIONS = {"work_experience", "language", "wage"}
_SECTION_TABLES: dict[str, B.Table] = {
    "work_experience": B.WORK_EXPERIENCE,
    "education": B.EDUCATION,
    "language": B.LANGUAGE,
    "wage": B.WAGE,
    "area": B.AREA,
}


# ------------------------------------------------------------------- cited record model
@dataclass(frozen=True)
class SirsGridCitation:
    """Provenance for a parsed SIRS grid: where the grid text came from and when."""
    source_url: str
    fetched: date

    def as_dict(self) -> dict:
        return {"source_url": self.source_url, "fetched": self.fetched.isoformat()}


@dataclass(frozen=True)
class SirsBandRecord:
    """One parsed SIRS factor's band table, cited, with a manual-check flag.

    `bands` is {key -> points} as parsed from the source (keys are ints for
    work_experience/language/wage, strings for education/area). `needs_manual_check` is set
    when a row could not be parsed; the offending rows are named in `notes` and the record is
    kept out of any verification verdict rather than guessed.
    """
    factor: str
    bands: dict
    citation: SirsGridCitation
    needs_manual_check: bool = False
    notes: str = ""

    def as_dict(self) -> dict:
        return {"factor": self.factor, "bands": self.bands,
                "needs_manual_check": self.needs_manual_check, "notes": self.notes,
                "citation": self.citation.as_dict()}


@dataclass(frozen=True)
class BandReconciliation:
    """The reconcile verdict for one factor: does the parsed source match the in-code band?"""
    factor: str
    matches: bool                 # parsed source == in-code Table.values exactly
    verified: bool                # matches AND the source parsed cleanly (no manual check)
    source_only: dict = field(default_factory=dict)   # keys/points only in the source
    code_only: dict = field(default_factory=dict)      # keys/points only in the code
    differing: dict = field(default_factory=dict)      # key -> {"source":.., "code":..}
    notes: str = ""

    def as_dict(self) -> dict:
        return {"factor": self.factor, "matches": self.matches, "verified": self.verified,
                "source_only": self.source_only, "code_only": self.code_only,
                "differing": self.differing, "notes": self.notes}


@dataclass(frozen=True)
class SirsVerification:
    """The full reconcile of a fetched grid against the engine's bands, fully cited.

    `all_verified` is the claim that would justify flipping `pnp/bc.py` bands to
    `verified=True` (a human step). `mismatches` is the "wrong number on stage" catch: any
    factor where the source and the engine disagree, or the source did not parse cleanly.
    """
    citation: SirsGridCitation
    reconciliations: list[BandReconciliation]
    records: list[SirsBandRecord]

    @property
    def all_verified(self) -> bool:
        return bool(self.reconciliations) and all(r.verified for r in self.reconciliations)

    @property
    def mismatches(self) -> list[BandReconciliation]:
        return [r for r in self.reconciliations if not r.verified]

    def as_dict(self) -> dict:
        return {"citation": self.citation.as_dict(), "all_verified": self.all_verified,
                "reconciliations": [r.as_dict() for r in self.reconciliations],
                "records": [rec.as_dict() for rec in self.records],
                "mismatches": [r.factor for r in self.mismatches]}


# ----------------------------------------------------------------------- deterministic parse
_SECTION_RE = re.compile(r"^\s*\[([a-z_]+)\]\s*$")
_ROW_RE = re.compile(r"^\s*(.+?)\s*=\s*(-?\d+)\s*$")


def _parse_key(section: str, raw_key: str) -> Optional[Any]:
    """A band key parsed to the type the in-code table uses. int for the numeric sections,
    the trimmed string otherwise. None if a numeric section's key is not an integer."""
    key = raw_key.strip()
    if section in _INT_KEY_SECTIONS:
        return int(key) if re.fullmatch(r"-?\d+", key) else None
    return key


def parse_sirs_grid(text: str, source_url: str = BC_PNP_SIRS_URL,
                    fetched: Optional[date] = None) -> list[SirsBandRecord]:
    """Parse normalized SIRS grid text into cited band records.

    Expected shape (what the Browser extraction step must produce from the live page — an
    INI-like block per factor):

        [work_experience]
        0 = 0
        1 = 8
        ...
        [education]
        bachelors-or-three-year = 27
        ...

    Deterministic and total: an unknown section is noted and skipped; a row that does not
    parse (or a numeric section key that is not an integer) flags that factor
    `needs_manual_check` rather than dropping a guess into a verified band.
    """
    day = fetched or date.today()
    citation = SirsGridCitation(source_url=source_url, fetched=day)

    sections: dict[str, dict] = {}
    problems: dict[str, list[str]] = {}
    unknown: list[str] = []
    current: Optional[str] = None

    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _SECTION_RE.match(line)
        if m:
            current = m.group(1)
            if current not in _SECTION_TABLES:
                unknown.append(current)
                current = None
            else:
                sections.setdefault(current, {})
            continue
        if current is None:
            continue
        row = _ROW_RE.match(line)
        if not row:
            problems.setdefault(current, []).append(f"line {lineno}: unparseable row {stripped!r}")
            continue
        key = _parse_key(current, row.group(1))
        if key is None:
            problems.setdefault(current, []).append(
                f"line {lineno}: non-integer key {row.group(1)!r} in numeric section")
            continue
        sections[current][key] = int(row.group(2))

    records: list[SirsBandRecord] = []
    for factor in _SECTION_TABLES:
        if factor not in sections:
            records.append(SirsBandRecord(
                factor=factor, bands={}, citation=citation, needs_manual_check=True,
                notes="section missing from the extracted grid"))
            continue
        notes = "; ".join(problems.get(factor, []))
        records.append(SirsBandRecord(
            factor=factor, bands=sections[factor], citation=citation,
            needs_manual_check=bool(problems.get(factor)), notes=notes))
    if unknown:
        # Attach the unknown-section note to the last record so it is not lost.
        records[-1] = SirsBandRecord(
            factor=records[-1].factor, bands=records[-1].bands, citation=citation,
            needs_manual_check=records[-1].needs_manual_check,
            notes="; ".join(filter(None, [records[-1].notes,
                                          f"unknown sections ignored: {sorted(set(unknown))}"])))
    return records


# ----------------------------------------------------------------------------- reconcile
def reconcile_band(record: SirsBandRecord) -> BandReconciliation:
    """Compare one parsed factor against the in-code band. A factor is `verified` only when the
    source parsed cleanly AND equals the engine's table exactly."""
    table = _SECTION_TABLES[record.factor]
    code = dict(table.values)
    source = dict(record.bands)

    source_only = {k: source[k] for k in source if k not in code}
    code_only = {k: code[k] for k in code if k not in source}
    differing = {k: {"source": source[k], "code": code[k]}
                 for k in source if k in code and source[k] != code[k]}
    matches = not (source_only or code_only or differing)
    verified = matches and not record.needs_manual_check
    note = record.notes
    if not matches and not note:
        note = "source disagrees with the in-code band; needs manual resolution"
    return BandReconciliation(factor=record.factor, matches=matches, verified=verified,
                              source_only=source_only, code_only=code_only,
                              differing=differing, notes=note)


def reconcile_grid(records: list[SirsBandRecord]) -> list[BandReconciliation]:
    return [reconcile_band(r) for r in records]


# --------------------------------------------------------------------------- fetch seam
def fetch_bc_pnp_sirs_text(fetcher: Optional[Callable[[], str]] = None,
                           url: str = BC_PNP_SIRS_URL, timeout: float = 30.0) -> str:
    """Return the extracted SIRS grid text. `fetcher` is injected (a fixture reader in tests, a
    `BcPnpBrowserFetcher` in deploy). With no fetcher, a thin urllib GET of `url` is the
    fallback — kept separate from parsing so tests never hit the network."""
    if fetcher is not None:
        return fetcher()
    from urllib.request import Request, urlopen  # local import keeps module import-light
    req = Request(url, headers={"User-Agent": "MapleGuard/sirs-ingest (+https://mapleguard)"})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed welcomebc.ca https URL
        return resp.read().decode("utf-8")


def verify_sirs_grid(fetcher: Optional[Callable[[], str]] = None,
                     url: str = BC_PNP_SIRS_URL,
                     fetched: Optional[date] = None) -> SirsVerification:
    """The research-agent entrypoint: fetch the official grid, parse it, and reconcile it
    against the engine's bands. Returns a fully cited `SirsVerification`. Reports only — it
    never mutates `pnp/bc.py`. `all_verified` True is what justifies a human flipping the
    `verified` flags; `mismatches` is the list to resolve first."""
    text = fetch_bc_pnp_sirs_text(fetcher=fetcher, url=url)
    records = parse_sirs_grid(text, source_url=url, fetched=fetched)
    citation = records[0].citation if records else SirsGridCitation(url, fetched or date.today())
    return SirsVerification(citation=citation, reconciliations=reconcile_grid(records),
                            records=records)


# ----------------------------------------------------- AgentCore Browser fetcher (deploy seam)
class BcPnpBrowserFetcher:
    """Fetch the SIRS grid text through the Amazon Bedrock AgentCore Browser tool.

    The Browser primitive gives a managed, isolated headless browser reachable over a
    CDP/WebSocket endpoint. Import-verified surface (bedrock-agentcore 1.22.0): the
    `BrowserClient` is started, hands out `generate_ws_headers()` (the CDP endpoint + SigV4
    headers) and a `generate_live_view_url()` for the demo, and is stopped.

    Navigation + grid extraction is done by a `page_reader(client, url) -> str` callable driving
    that CDP endpoint (a Playwright-over-CDP driver at deploy). That step is docs-derived — it
    needs a live browser to confirm — so it is injected, not faked here. `fetch()` returns the
    normalized grid text `parse_sirs_grid` consumes; the deterministic parse + reconcile then
    own the numbers, so a bad extraction is caught by the reconcile check, never trusted.
    """
    def __init__(self, client: Any, page_reader: Callable[[Any, str], str],
                 url: str = BC_PNP_SIRS_URL):
        self.client = client
        self.page_reader = page_reader
        self.url = url

    def fetch(self) -> str:
        return self.page_reader(self.client, self.url)

    def __call__(self) -> str:
        return self.fetch()


def build_bc_pnp_browser_fetcher(region: str, page_reader: Callable[[Any, str], str],
                                 url: str = BC_PNP_SIRS_URL, identifier: Optional[str] = None,
                                 **client_kwargs: Any) -> BcPnpBrowserFetcher:
    """Start an AgentCore Browser session and wrap it as a `BcPnpBrowserFetcher`.

    Requires `bedrock-agentcore` and live AWS (imported lazily so this module needs neither to
    import). `page_reader` is the CDP driver that navigates and extracts the grid text (see the
    runbook). `identifier` selects the browser (default `aws.browser.v1`).
    """
    from bedrock_agentcore.tools.browser_client import BrowserClient

    client = BrowserClient(region=region, **client_kwargs)
    client.start(**({"identifier": identifier} if identifier else {}))
    return BcPnpBrowserFetcher(client, page_reader=page_reader, url=url)
