"""NOC 2021 ingestion: fetch, parse, and source-verify official occupation profiles.

This turns the hand-transcribed occupation dict into records whose trust is EARNED
deterministically, not asserted. The posture, in order:

  1. Deterministic parse of the ESDC profile HTML into code, title, TEER, lead statement, and
     main duties, each extracted verbatim from the page. Duties phrased "May ..." are optional.
  2. A DETERMINISTIC source-match: every extracted field, normalized, must appear verbatim in
     the normalized page text. Only then is verified=True conferred, stamped with a content hash
     of the extracted record and the fetch date. A parse that is incomplete, or whose text is not
     found on the page, is verified=False -- never guessed into trust.
  3. An OPTIONAL LLM judge, VETO-ONLY: it may DOWNGRADE a source-verified record to needs-review
     (with a reason) but can NEVER confer verified=True. The model catches errors; it never
     certifies ground truth. Injected; absent by default so the pipeline runs offline.
  4. A human spot-check on a sample (`records_for_spotcheck`) closes the loop.

Fetch is thin and separable (`fetch_noc_profile`), so parsing and verification run offline
against a saved page fixture with no network -- the same seam pattern as ingest.rounds.
"""
from __future__ import annotations

import hashlib
import html as _html
import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

from .models import Duty, NocOccupation

NOC_PROFILE_BASE = "https://noc.esdc.gc.ca/Structure/NOCProfile"
NOC_VERSION = "NOC 2021 Version 1.0"


def noc_profile_url(code: str, version: str = "2021.0") -> str:
    """The official ESDC profile URL for a NOC code (the citation stored on each record)."""
    return f"{NOC_PROFILE_BASE}?GocTemplateCulture=en-CA&code={code}&version={version}"


def _text(fragment: str) -> str:
    """Strip HTML tags and unescape entities, preserving the page's verbatim characters
    (e.g. the right single quote U+2019), then collapse runs of whitespace to one space."""
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def _normalize(s: str) -> str:
    """Fold to a comparison form for the source-match: unescape, drop tags, lowercase, and
    collapse whitespace. Used only to confirm extracted text is literally present on the page."""
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", s))).strip().lower()


def content_hash(title: str, lead_statement: str, duties: List[Duty]) -> str:
    """A stable sha256 over the extracted verbatim content, so a later re-fetch can tell whether
    the substantive occupation text changed (independent of page chrome, ads, or session ids)."""
    canonical = "\n".join([title.strip(), lead_statement.strip(),
                           *[d.text.strip() for d in duties]])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ParsedProfile:
    """The deterministic parse of one profile page, before verification is decided."""
    code: str
    title: str
    teer: Optional[int]
    lead_statement: str
    main_duties: List[Duty]
    problems: List[str]


def parse_noc_profile(html: str, code: str) -> ParsedProfile:
    """Parse an ESDC NOC profile page into its verbatim fields. Pure and deterministic; records
    every field it could not extract in `problems` rather than guessing a value."""
    problems: List[str] = []

    h2 = re.search(r"<h2[^>]*>(.*?)</h2>", html, re.S | re.I)
    parsed_code, title = "", ""
    if h2:
        head = _text(h2.group(1))
        # The heading is "<code> - <title>" joined by an en dash (or hyphen).
        parts = re.split(r"\s[–\-]\s", head, maxsplit=1)
        parsed_code = re.sub(r"\D", "", parts[0])
        title = parts[1].strip() if len(parts) > 1 else ""
    if not title:
        problems.append("missing title")
    if parsed_code and parsed_code != code:
        problems.append(f"page code {parsed_code!r} does not match requested {code!r}")

    # TEER is the NOC 2021 code's second digit, by definition of the classification.
    teer = int(code[1]) if len(code) == 5 and code.isdigit() else None
    if teer is None:
        problems.append(f"cannot derive TEER from code {code!r}")

    # Lead statement: the first paragraph after the code/title heading, before the first h4.
    lead = ""
    if h2:
        after = html[h2.end():]
        first_h4 = re.search(r"<h4", after, re.I)
        region = after[:first_h4.start()] if first_h4 else after
        for p in re.findall(r"<p[^>]*>(.*?)</p>", region, re.S | re.I):
            t = _text(p)
            if t:
                lead = t
                break
    if not lead:
        problems.append("missing lead statement")

    # Main duties: the list items under the "Main duties" h4, up to the next h4/h3.
    duties: List[Duty] = []
    md = re.search(r"<h4[^>]*>\s*Main duties\s*</h4>(.*?)(?:<h4|<h3)", html, re.S | re.I)
    if md:
        for i, li in enumerate(re.findall(r"<li[^>]*>(.*?)</li>", md.group(1), re.S | re.I), 1):
            t = _text(li)
            if t:
                duties.append(Duty(id=f"{code}.{i}", text=t, optional=t.startswith("May ")))
    if not duties:
        problems.append("no main duties found")

    return ParsedProfile(code=code, title=title, teer=teer, lead_statement=lead,
                         main_duties=duties, problems=problems)


def _source_match_fields(title: str, lead_statement: str, duties: List[Duty],
                         html: str) -> Tuple[bool, str]:
    """Deterministic verification: confirm each field appears verbatim in the page text. Returns
    (matched, note). This is what earns verified=True -- it proves the stored text is literally on
    the page, not paraphrased. It also detects drift: re-checking a stored record against a page
    that has since changed (or the wrong page) fails. A single field not found fails the match."""
    page = _normalize(html)
    missing: List[str] = []
    if _normalize(title) not in page:
        missing.append("title")
    if _normalize(lead_statement) not in page:
        missing.append("lead statement")
    for d in duties:
        if _normalize(d.text) not in page:
            missing.append(f"duty {d.id}")
    if missing:
        return False, "source-match failed for: " + ", ".join(missing)
    return True, "deterministic source-match against the fetched page"


def verify_against_html(occ: NocOccupation, html: str) -> Tuple[bool, str]:
    """Re-check an existing record's stored text against a page. Use it to re-verify a corpus
    record after a re-fetch (a page whose NOC text changed, or the wrong page, fails the match)."""
    return _source_match_fields(occ.title, occ.lead_statement, occ.main_duties, html)


# A veto-only judge: given the parsed record and the page text, it may object with a reason.
# It returns (ok, reason). ok=False downgrades a source-verified record to needs-review; it can
# never set verified=True. Absent by default (offline). A real implementation calls a model.
Judge = Callable[[ParsedProfile, str], Tuple[bool, str]]


def ingest_profile(html: str, code: str, fetched: Optional[date] = None,
                   judge: Optional[Judge] = None) -> NocOccupation:
    """Parse one profile page and decide verified deterministically, then let an optional judge
    veto it. Returns a NocOccupation stamped with TEER, content hash, fetch date, and a note.

    verified=True requires BOTH a clean parse and a source-match. The judge can only downgrade.
    """
    fetched = fetched or date.today()
    parsed = parse_noc_profile(html, code)
    source_url = noc_profile_url(code)
    chash = content_hash(parsed.title, parsed.lead_statement, parsed.main_duties)

    if parsed.problems:
        note = "parse incomplete: " + "; ".join(parsed.problems)
        verified = False
    else:
        matched, note = _source_match_fields(parsed.title, parsed.lead_statement,
                                             parsed.main_duties, html)
        verified = matched

    # Veto-only judge: may downgrade a source-verified record, never certify one.
    if verified and judge is not None:
        try:
            ok, reason = judge(parsed, html)
        except Exception as exc:  # a judge failure must never silently certify
            ok, reason = False, f"judge error: {exc}"
        if not ok:
            verified = False
            note = f"needs-review (judge veto: {reason})"

    return NocOccupation(
        code=code, title=parsed.title, lead_statement=parsed.lead_statement,
        main_duties=parsed.main_duties, source=source_url, version=NOC_VERSION,
        verified=verified, teer=parsed.teer, content_hash=chash,
        fetched=fetched.isoformat(), verification_note=note,
    )


def fetch_noc_profile(code: str, timeout: float = 30.0) -> str:
    """Thin network fetch: the raw HTML of a NOC profile page. Separated from parsing so tests
    never touch the network (they parse a saved fixture). Not called by any test."""
    from urllib.request import Request, urlopen  # local import keeps the module import-light

    req = Request(noc_profile_url(code),
                  headers={"User-Agent": "MapleGuard/noc-ingest (+https://mapleguard)"})
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed noc.esdc.gc.ca https URL
        return resp.read().decode("utf-8")


def ingest_batch(codes: List[str], fetcher: Optional[Callable[[str], str]] = None,
                 fetched: Optional[date] = None,
                 judge: Optional[Judge] = None) -> Dict[str, NocOccupation]:
    """Ingest a batch of NOC codes into verified records. `fetcher(code) -> html` defaults to the
    live fetch; inject a fixture reader to run offline. Start with the 21xxx tech batch."""
    fetch = fetcher or fetch_noc_profile
    out: Dict[str, NocOccupation] = {}
    for code in codes:
        out[code] = ingest_profile(fetch(code), code, fetched=fetched, judge=judge)
    return out


# --------------------------------------------------------------- corpus persistence
def occupation_to_dict(occ: NocOccupation) -> dict:
    return {
        "code": occ.code, "title": occ.title, "lead_statement": occ.lead_statement,
        "main_duties": [{"id": d.id, "text": d.text, "optional": d.optional}
                        for d in occ.main_duties],
        "source": occ.source, "version": occ.version, "verified": occ.verified,
        "teer": occ.teer, "content_hash": occ.content_hash, "fetched": occ.fetched,
        "verification_note": occ.verification_note,
    }


def occupation_from_dict(d: dict) -> NocOccupation:
    return NocOccupation(
        code=d["code"], title=d["title"], lead_statement=d["lead_statement"],
        main_duties=[Duty(id=x["id"], text=x["text"], optional=x.get("optional", False))
                     for x in d["main_duties"]],
        source=d["source"], version=d.get("version", NOC_VERSION),
        verified=d.get("verified", False), teer=d.get("teer"),
        content_hash=d.get("content_hash", ""), fetched=d.get("fetched", ""),
        verification_note=d.get("verification_note", ""),
    )


def records_for_spotcheck(occs: Dict[str, NocOccupation], every: int = 3) -> List[str]:
    """A deterministic sample of codes for a human to eyeball against the source (every Nth code,
    by sorted code order). The human spot-check is the final gate the model never replaces."""
    ordered = sorted(occs)
    return ordered[::max(1, every)]
