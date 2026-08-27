"""Tests for the model-backed duty matcher.

These never touch the network: a fake client stands in for the Anthropic SDK, so we
control exactly what the "model" returns and assert on how the matcher and the
deterministic validator handle it.

Run:  cd agents-for-humans/mapleguard && PYTHONPATH=. python3 -m pytest -q
"""
import json
import os

import pytest

from noc import (audit_letter, get_occupation, validate_alignment, LLMDutyMatcher)

OCC = get_occupation("21234")

LETTER = """\
To Whom It May Concern:

This confirms Jane Doe was employed as a Web Developer at Acme Corp. She works 37.5
hours per week at $85,000 per year.

Her duties include the following:
- Develop, write, modify and test website code and web application interfaces.
- Conduct tests and analyze data to monitor quality, security and user experience.
- Develop and implement procedures for ongoing website revision.
- Monitor and maintain website functionality.

Sincerely, John Manager
"""


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class _FakeClient:
    """Stands in for anthropic.Anthropic — returns a canned reply, records the call."""

    def __init__(self, reply_text):
        self._reply_text = reply_text
        self.calls = []

        class _Messages:
            def create(_self, **kwargs):
                self.calls.append(kwargs)
                return _FakeResponse(self._reply_text)

        self.messages = _Messages()


def _reply(duties, lead_evidence=""):
    return json.dumps({"lead_evidence": lead_evidence, "duties": duties})


# --- Output shape -------------------------------------------------------------------
def test_matcher_returns_alignment_and_lead_evidence():
    reply = _reply(
        {
            "21234.1": "Develop, write, modify and test website code and web application interfaces.",
            "21234.4": "Monitor and maintain website functionality.",
        },
        lead_evidence="employed as a Web Developer at Acme Corp",
    )
    matcher = LLMDutyMatcher(client=_FakeClient(reply))
    alignment, lead = matcher(LETTER, OCC)

    assert set(alignment) == {"21234.1", "21234.4"}
    assert alignment["21234.1"].startswith("Develop, write, modify")
    assert lead == "employed as a Web Developer at Acme Corp"


def test_matcher_call_uses_configured_model():
    fake = _FakeClient(_reply({}))
    LLMDutyMatcher(client=fake, model="claude-test-model")(LETTER, OCC)
    assert fake.calls[0]["model"] == "claude-test-model"


# --- Anti-hallucination: paraphrase/fabrication is stripped downstream ---------------
def test_paraphrased_and_fabricated_evidence_dropped_by_validation():
    # Two verbatim quotes (kept), one paraphrase (not a substring), one invented duty.
    reply = _reply(
        {
            "21234.3": "Develop and implement procedures for ongoing website revision.",  # verbatim
            "21234.4": "Monitor and maintain website functionality.",                     # verbatim
            "21234.1": "Wrote and tested a bunch of web code",                            # paraphrase
            "21234.2": "Led a team of forty engineers across three continents",           # fabricated
        },
        lead_evidence="employed as a Web Developer at Acme Corp",
    )
    matcher = LLMDutyMatcher(client=_FakeClient(reply))
    raw_alignment, lead_evidence = matcher(LETTER, OCC)

    validated, lead_covered = validate_alignment(LETTER, raw_alignment, lead_evidence)
    assert set(validated) == {"21234.3", "21234.4"}   # only verbatim quotes survive
    assert "21234.1" not in validated                 # paraphrase can't be found -> dropped
    assert "21234.2" not in validated                 # fabrication can't be found -> dropped
    assert lead_covered is True


# --- Defensive parsing --------------------------------------------------------------
def test_parses_json_wrapped_in_fences_and_prose():
    inner = _reply({"21234.4": "Monitor and maintain website functionality."}, "Web Developer")
    reply = f"Here is the alignment you asked for:\n```json\n{inner}\n```\nHope that helps."
    alignment, lead = LLMDutyMatcher(client=_FakeClient(reply))(LETTER, OCC)
    assert alignment == {"21234.4": "Monitor and maintain website functionality."}
    assert lead == "Web Developer"


def test_malformed_reply_degrades_to_no_coverage():
    alignment, lead = LLMDutyMatcher(client=_FakeClient("not json at all"))(LETTER, OCC)
    assert alignment == {} and lead == ""


def test_unknown_duty_ids_are_ignored():
    reply = _reply({"99999.9": "Some unrelated sentence.", "21234.4": "Monitor and maintain website functionality."})
    alignment, _ = LLMDutyMatcher(client=_FakeClient(reply))(LETTER, OCC)
    assert set(alignment) == {"21234.4"}  # id not in the occupation is dropped


# --- End to end through audit_letter with the fake-backed matcher -------------------
def test_audit_letter_with_llm_matcher_passes_on_full_coverage():
    reply = _reply(
        {
            "21234.1": "Develop, write, modify and test website code and web application interfaces.",
            "21234.2": "Conduct tests and analyze data to monitor quality, security and user experience.",
            "21234.3": "Develop and implement procedures for ongoing website revision.",
            "21234.4": "Monitor and maintain website functionality.",
        },
        lead_evidence="employed as a Web Developer at Acme Corp",
    )
    matcher = LLMDutyMatcher(client=_FakeClient(reply))
    report = audit_letter(LETTER, OCC, matcher)
    assert report.duties.passed
    assert report.duties.coverage == 1.0


def test_audit_letter_with_llm_matcher_fails_and_cites_gaps_when_model_paraphrases():
    # Model paraphrases everything -> nothing validates -> audit fails with cited gaps.
    reply = _reply(
        {f"21234.{i}": f"paraphrased duty {i} not present in the letter" for i in range(1, 5)},
        lead_evidence="Jane is a great employee",  # also not in the letter
    )
    matcher = LLMDutyMatcher(client=_FakeClient(reply))
    report = audit_letter(LETTER, OCC, matcher)
    assert not report.duties.passed
    assert report.duties.coverage == 0.0
    assert len(report.duties.gaps) == 4
    assert all(g.noc_code == "21234" for g in report.duties.gaps)


# --- Optional integration test (real network), only when a key is present -----------
@pytest.mark.skipif(
    not os.environ.get("MAPLEGUARD_LLM_INTEGRATION") or not os.environ.get("ANTHROPIC_API_KEY"),
    reason="set MAPLEGUARD_LLM_INTEGRATION=1 and ANTHROPIC_API_KEY to run the live matcher",
)
def test_llm_matcher_live():
    matcher = LLMDutyMatcher()
    report = audit_letter(LETTER, OCC, matcher)
    # We don't assert an exact score against a live model, only that the pipeline runs and
    # that any claimed coverage is genuinely a substring of the letter (validated).
    for match in report.duties.matches:
        if match.covered:
            assert " ".join(match.evidence.split()).lower() in " ".join(LETTER.split()).lower()
