"""Tests for the correction draft.

No network: a fake client returns a canned revised letter, and a substring-based fake
matcher stands in for the LLM matcher so the draft -> re-audit round-trip is real (the
matcher genuinely responds to what the draft contains).

Run:  cd agents-for-humans/mapleguard && PYTHONPATH=. python3 -m pytest -q
"""
import os

import pytest

from noc import (audit_letter, get_occupation, score_duties, validate_alignment,
                 LetterCorrector, CorrectionDraft)

OCC = get_occupation("21234")

# A letter that covers only duties 3 and 4 -> duties 1 and 2 are gaps.
DEFICIENT_LETTER = """\
To Whom It May Concern:

Jane Doe was employed as a Web Developer from June 2025 to present. She works 37.5 hours
per week and earns $85,000 per year. Her responsibilities included developing and
implementing procedures for ongoing website revision, and monitoring and maintaining
website functionality.

Regards, John Manager, Acme Corp, hr@acme.com
"""

_NORM = lambda s: " ".join(s.split()).lower()
_TARGETS = {d.id: d.text for d in OCC.required_duties()}


def _content_matcher(letter_text, occupation):
    """Real substring matcher: maps a duty iff the letter contains its NOC text verbatim.

    An "[employer to confirm: ...]" placeholder is not performed work, so those lines are
    dropped before matching -- a real matcher wouldn't cite an unconfirmed bracket either.
    """
    without_placeholders = "\n".join(
        ln for ln in letter_text.splitlines() if "employer to confirm" not in ln.lower())
    hay = _NORM(without_placeholders)
    alignment = {i: t for i, t in _TARGETS.items() if _NORM(t) in hay}
    lead = occupation.lead_statement if _NORM(occupation.lead_statement) in hay else ""
    return alignment, lead


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeClient:
    def __init__(self, reply_text):
        self._reply_text = reply_text
        self.calls = []

        class _Messages:
            def create(_self, **kwargs):
                self.calls.append(kwargs)
                return _FakeResponse(self._reply_text)

        self.messages = _Messages()


def _coverage(letter_text):
    alignment, lead = _content_matcher(letter_text, OCC)
    validated, lead_covered = validate_alignment(letter_text, alignment, lead)
    return score_duties(OCC, validated, lead_covered)


# --- Output shape -------------------------------------------------------------------
def test_draft_returns_corrected_letter_text():
    corrector = LetterCorrector(client=_FakeClient("Revised letter body."))
    draft = corrector(DEFICIENT_LETTER, OCC, _coverage(DEFICIENT_LETTER))
    assert isinstance(draft, CorrectionDraft)
    assert draft.letter_text == "Revised letter body."
    assert draft.placeholders == [] and draft.has_open_gaps is False


def test_draft_uses_configured_model():
    fake = _FakeClient("x")
    LetterCorrector(client=fake, model="claude-test-model")(
        DEFICIENT_LETTER, OCC, _coverage(DEFICIENT_LETTER))
    assert fake.calls[0]["model"] == "claude-test-model"


# --- Honest gaps: unsupported duties become placeholders, never fabrication ---------
def test_unsupported_duty_left_as_placeholder():
    reply = (
        "Jane Doe was employed as a Web Developer.\n"
        "[employer to confirm: Conduct tests and analyze data to monitor quality]\n"
        "Regards, John Manager"
    )
    draft = LetterCorrector(client=_FakeClient(reply))(
        DEFICIENT_LETTER, OCC, _coverage(DEFICIENT_LETTER))
    assert len(draft.placeholders) == 1
    assert "employer to confirm" in draft.placeholders[0].lower()
    assert draft.has_open_gaps is True


def test_fenced_output_is_unwrapped():
    reply = "```\nRevised letter body only.\n```"
    draft = LetterCorrector(client=_FakeClient(reply))(
        DEFICIENT_LETTER, OCC, _coverage(DEFICIENT_LETTER))
    assert draft.letter_text == "Revised letter body only."


# --- Round-trip: draft closes the gaps it can support -------------------------------
def _revised_letter(cover_duties, placeholder_duties):
    """Build a draft that states the verbatim NOC text for covered duties and leaves
    placeholders for the rest -- exactly what a faithful corrector would produce."""
    body = [
        "To Whom It May Concern:",
        "",
        OCC.lead_statement,  # opening now reflects the lead statement
        "",
        "Jane Doe was employed as a Web Developer from June 2025 to present. She works 37.5 "
        "hours per week and earns $85,000 per year.",
        "",
    ]
    for d in OCC.required_duties():
        if d.id in cover_duties:
            body.append(f"- {d.text}.")
        elif d.id in placeholder_duties:
            body.append(f"- [employer to confirm: {d.text}]")
    body += ["", "Regards, John Manager, Acme Corp, hr@acme.com"]
    return "\n".join(body)


def test_round_trip_gaps_close_when_supported():
    # Caller attests the missing work, so the corrector can cover all four duties.
    supported = _revised_letter(cover_duties={"21234.1", "21234.2", "21234.3", "21234.4"},
                                placeholder_duties=set())
    corrector = LetterCorrector(client=_FakeClient(supported))
    supporting_facts = [
        "Jane wrote and tested website code and web application interfaces.",
        "Jane conducted tests and analyzed data to monitor quality and security.",
    ]
    draft = corrector(DEFICIENT_LETTER, OCC, _coverage(DEFICIENT_LETTER), supporting_facts)

    # Re-audit the DRAFT with the same real matcher: the gaps should now be closed.
    report = audit_letter(draft.letter_text, OCC, _content_matcher)
    assert report.duties.passed
    assert report.duties.coverage == 1.0
    assert report.duties.gaps == []
    assert draft.placeholders == []


def test_round_trip_leaves_unsupported_duty_as_a_cited_gap():
    # Only duty 1 gets support; duty 2 stays an honest placeholder and stays a cited gap.
    partial = _revised_letter(cover_duties={"21234.1", "21234.3", "21234.4"},
                              placeholder_duties={"21234.2"})
    corrector = LetterCorrector(client=_FakeClient(partial))
    draft = corrector(DEFICIENT_LETTER, OCC, _coverage(DEFICIENT_LETTER),
                      supporting_facts=["Jane wrote and tested website code and interfaces."])

    report = audit_letter(draft.letter_text, OCC, _content_matcher)
    # Duty 1 closed (now 3 of 4), but duty 2 is unsupported -> still a gap, not fabricated.
    assert report.duties.coverage == 0.75 and not report.duties.passed
    gap_texts = [g.text for g in report.duties.gaps]
    assert any("Conduct tests" in t for t in gap_texts)
    assert draft.has_open_gaps and len(draft.placeholders) == 1


# --- Optional live integration test -------------------------------------------------
@pytest.mark.skipif(
    not os.environ.get("MAPLEGUARD_LLM_INTEGRATION") or not os.environ.get("ANTHROPIC_API_KEY"),
    reason="set MAPLEGUARD_LLM_INTEGRATION=1 and ANTHROPIC_API_KEY to run the live corrector",
)
def test_corrector_live():
    from noc import LLMDutyMatcher
    coverage = audit_letter(DEFICIENT_LETTER, OCC, LLMDutyMatcher()).duties
    draft = LetterCorrector()(DEFICIENT_LETTER, OCC, coverage,
                              supporting_facts=["Jane wrote and tested website code and interfaces."])
    assert draft.letter_text.strip()
    # The draft must not fabricate: re-auditing must not raise, and any covered duty must
    # be genuinely present in the draft (validated inside audit_letter).
    report = audit_letter(draft.letter_text, OCC, LLMDutyMatcher())
    for match in report.duties.matches:
        if match.covered:
            assert _NORM(match.evidence) in _NORM(draft.letter_text)
