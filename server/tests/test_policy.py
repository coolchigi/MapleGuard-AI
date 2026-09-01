"""Policy-change classifier + letter re-audit bridge, and the consultant brief.

The headline demo: a NOC 2016->TEER 2021 reclassification is classified (model extracts, code
validates and drops bad output), routed to a stored profile whose reference letter claims an
affected NOC code, and re-audited so the alert carries the letter gaps cited to the (new) NOC
duty text. Plus the brief assembler, whose numbers all come from the deterministic core.

Offline and deterministic: fake classifier/matcher, no network, no AWS.
"""
import pytest

from ingest import PolicyChange, validate_policy_change

STRONG_PROFILE = {
    "education": "bachelors-or-three-year",
    "first_language": {"speaking": 10, "listening": 10, "reading": 10, "writing": 10},
    "date_of_birth": "1996-07-01", "canadian_work_years": 3,
    "first_language_test_date": "2025-09-30",
}
LETTER = ("This confirms Jane Doe worked as a Web Developer, 37.5 hours per week at $85,000. "
          "She wrote some HTML. Sincerely, Employer.")
SRC = "https://www.canada.ca/noc-2021-teer-update"


# --- 1. Deterministic validation DROPS bad LLM output ---------------------------------
def test_validate_policy_change_accepts_a_well_formed_noc_change():
    change = validate_policy_change(
        {"change_type": "noc", "affected_noc_codes": ["21234", "not-a-code"],
         "affected_components": ["teer_duties"], "effective_date": "2022-11-16",
         "summary": "NOC 2016 -> TEER 2021 reclassification"}, SRC)
    assert isinstance(change, PolicyChange)
    assert change.affected_noc_codes == ("21234",)  # the malformed code is dropped
    assert change.effective_date.isoformat() == "2022-11-16" and change.source == SRC


def test_validate_policy_change_drops_bad_output():
    # unknown change_type -> dropped
    assert validate_policy_change({"change_type": "bogus", "affected_noc_codes": ["21234"]}, SRC) is None
    # a NOC change naming no valid 5-digit code -> unactionable -> dropped
    assert validate_policy_change({"change_type": "noc", "affected_noc_codes": ["21", "abc"]}, SRC) is None
    # a present-but-unparseable effective_date -> dropped (no guessed dates)
    assert validate_policy_change(
        {"change_type": "noc", "affected_noc_codes": ["21234"], "effective_date": "not-a-date"}, SRC) is None
    # missing source -> no uncited change
    assert validate_policy_change({"change_type": "crs_weight"}, "") is None
    # not a dict -> dropped
    assert validate_policy_change("noc", SRC) is None


# --- 2. The classify TOOL validates and drops the model's output ----------------------
def test_classify_tool_validates_and_drops_bad_model_output():
    from agent.tools import classify_policy_change, configure_deps
    # A model that returns an invalid extraction -> the tool DROPS it.
    configure_deps(classifier=lambda text: {"change_type": "totally-made-up",
                                            "affected_noc_codes": ["21234"]})
    out = classify_policy_change("some IRCC update", SRC)
    assert out["validated"] is False and out["change"] is None

    # A model that returns a valid extraction -> the tool keeps the validated change.
    configure_deps(classifier=lambda text: {"change_type": "noc",
                                            "affected_noc_codes": ["21234"],
                                            "effective_date": "2022-11-16"})
    out = classify_policy_change("IRCC reclassifies NOC 21234", SRC)
    assert out["validated"] is True
    assert out["change"]["change_type"] == "noc" and out["change"]["affected_noc_codes"] == ["21234"]
    configure_deps()  # reset module deps


# --- 3. THE BRIDGE: a NOC change triggers a re-audit of the stored letter --------------
def _empty_matcher(letter_text, occupation):
    return ({}, "")  # covers nothing -> the letter now has gaps against the (new) NOC text


def test_noc_change_triggers_reaudit_of_stored_letter():
    from agent.monitor import (Alert, CollectingAlertSink, InMemoryProfileStore,
                               InMemorySnapshotStore, MonitorDeps, StoredProfile, tick)

    change = validate_policy_change(
        {"change_type": "noc", "affected_noc_codes": ["21234"], "effective_date": "2022-11-16",
         "summary": "NOC 2016 -> TEER 2021"}, SRC).to_dict()

    sp = StoredProfile(id="u1", profile=STRONG_PROFILE,
                       reference_letter={"noc_code": "21234", "letter_text": LETTER})
    sink = CollectingAlertSink()
    # No new draws (a stale rounds feed): the ONLY trigger here is the policy change.
    deps = MonitorDeps(
        fetch_rounds=lambda: '{"rounds": []}', source_url="https://x",
        profiles=InMemoryProfileStore([sp]), snapshots=InMemorySnapshotStore(), sink=sink,
        fetch_policy_update=lambda: "IRCC reclassifies NOC 21234 to TEER 2021",
        classify_update=lambda text: change, matcher=_empty_matcher)

    result = tick(deps, as_of="2026-08-25")
    policy_alerts = [a for a in result.alerts if a.policy_change is not None]
    assert len(policy_alerts) == 1
    a = policy_alerts[0]
    assert a.profile_id == "u1"
    assert a.policy_change["change_type"] == "noc"
    assert a.letter_gaps and all("text" in g and g.get("source") for g in a.letter_gaps)  # cited
    assert a.crs and a.crs["delta"] == 0 and a.crs["after"] > 0                             # from core
    assert SRC in a.citations                                                               # change cited


def test_a_profile_with_no_stored_letter_is_not_reaudited():
    from agent.monitor import (CollectingAlertSink, InMemoryProfileStore, InMemorySnapshotStore,
                               MonitorDeps, StoredProfile, tick)
    change = validate_policy_change(
        {"change_type": "noc", "affected_noc_codes": ["21234"]}, SRC).to_dict()
    sp = StoredProfile(id="no-letter", profile=STRONG_PROFILE)  # relevant code, but no letter stored
    deps = MonitorDeps(
        fetch_rounds=lambda: '{"rounds": []}', profiles=InMemoryProfileStore([sp]),
        snapshots=InMemorySnapshotStore(), sink=CollectingAlertSink(),
        fetch_policy_update=lambda: "update", classify_update=lambda t: change, matcher=_empty_matcher)
    result = tick(deps, as_of="2026-08-25")
    assert [a for a in result.alerts if a.policy_change is not None] == []  # nothing to re-audit


def test_policy_watch_is_off_when_not_wired():
    from agent.monitor import (CollectingAlertSink, InMemoryProfileStore, InMemorySnapshotStore,
                               MonitorDeps, StoredProfile, tick)
    sp = StoredProfile(id="u1", profile=STRONG_PROFILE,
                       reference_letter={"noc_code": "21234", "letter_text": LETTER})
    deps = MonitorDeps(fetch_rounds=lambda: '{"rounds": []}', profiles=InMemoryProfileStore([sp]),
                       snapshots=InMemorySnapshotStore(), sink=CollectingAlertSink())  # no policy wiring
    assert tick(deps, as_of="2026-08-25").alerts == []


# --- 4. The consultant brief: numbers come from the core ------------------------------
def _partial_matcher(letter_text, occupation):
    return ({}, "")  # gaps -> the brief carries cited letter gaps


class _FakeCorrector:
    def __call__(self, letter_text, occupation, coverage, supporting_facts=None):
        from noc import CorrectionDraft
        return CorrectionDraft(letter_text="Revised. [employer to confirm: something]",
                               placeholders=["[employer to confirm: something]"])


def _brief_inputs():
    from agent.tools import configure_deps
    configure_deps(matcher=_partial_matcher, corrector=_FakeCorrector())  # audit + draft need clients
    draws = [{"kind": "general", "name": "General round", "cutoff": 400, "date": "2026-08-01",
              "source": "https://www.canada.ca/rounds"}]
    return draws


def test_brief_numbers_and_citations_come_from_the_core_not_the_prose():
    from api.brief import assemble_brief
    from agent.tools import compute_crs, configure_deps
    draws = _brief_inputs()

    # A lying narrator: its prose states a WRONG number. The structured brief must ignore it.
    def liar(prompt):
        class R:
            message = "Your CRS is 9999 and you are eligible for PR."
        return R()

    brief = assemble_brief(STRONG_PROFILE, noc_code="21234", letter_text=LETTER, draws=draws,
                           as_of="2026-08-25", narrator=liar)
    core_total = compute_crs(STRONG_PROFILE, as_of="2026-08-25")["total"]
    assert brief["crs"]["total"] == core_total                 # number is the core's, not "9999"
    assert brief["profile_summary"]["crs_total"] == core_total
    assert brief["next_moves"] and brief["next_moves"][0]["date"] == "2026-08-01"  # ranked, dated
    assert brief["letter_audit"]["duties"]["gaps"], "cited NOC gaps present"
    assert all(g.get("source") for g in brief["letter_audit"]["duties"]["gaps"])   # cited
    # The prose asserted eligibility ("you are eligible for PR") -> screened out entirely.
    assert brief["prose"] == ""
    assert "does not assert eligibility" in brief["disclaimer"]
    configure_deps()  # reset


def test_brief_keeps_prose_that_does_not_assert_eligibility():
    from api.brief import assemble_brief
    from agent.tools import configure_deps
    _brief_inputs()

    def ok(prompt):
        class R:
            message = "Your computed CRS is attached with citations; review the ranked moves."
        return R()

    brief = assemble_brief(STRONG_PROFILE, as_of="2026-08-25", narrator=ok)
    assert "review the ranked moves" in brief["prose"]  # benign prose survives the screen
    configure_deps()


# --- 5. API: letter intake + the brief endpoint ---------------------------------------
def _client(configured=True, brief_narrator=None):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from agent.monitor import InMemoryProfileStore
    from api import create_app
    from api.model_config import NocModel
    noc = NocModel(matcher=_partial_matcher, corrector=_FakeCorrector(), configured=configured,
                   backend="fake", model="fake", detail="" if configured else "no key")
    return TestClient(create_app(noc_model=noc, profile_store=InMemoryProfileStore(),
                                 brief_narrator=brief_narrator))


def test_post_profiles_stores_a_reference_letter():
    client = _client()
    resp = client.post("/profiles", json={
        "profile": STRONG_PROFILE, "id": "u1",
        "reference_letter": {"noc_code": "21234", "letter_text": LETTER}})
    assert resp.status_code == 200
    got = client.get("/profiles/u1").json()
    assert got["reference_letter"]["noc_code"] == "21234"


def test_put_letter_attaches_to_an_existing_profile():
    client = _client()
    client.post("/profiles", json={"profile": STRONG_PROFILE, "id": "u2"})
    resp = client.put("/profiles/u2/letter", json={"noc_code": "21234", "letter_text": LETTER})
    assert resp.status_code == 200 and resp.json()["letter_stored"] is True
    assert client.get("/profiles/u2").json()["reference_letter"]["letter_text"] == LETTER
    # attaching to a missing profile -> 404
    assert client.put("/profiles/nope/letter",
                      json={"noc_code": "21234", "letter_text": LETTER}).status_code == 404


def test_brief_endpoint_numbers_come_from_core():
    from agent.tools import compute_crs
    client = _client()
    draws = [{"kind": "general", "name": "General round", "cutoff": 400, "date": "2026-08-01",
              "source": "https://www.canada.ca/rounds"}]
    resp = client.post("/brief", json={"profile": STRONG_PROFILE, "noc_code": "21234",
                                       "letter_text": LETTER, "draws": draws, "as_of": "2026-08-25"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["crs"]["total"] == compute_crs(STRONG_PROFILE, as_of="2026-08-25")["total"]
    assert body["letter_audit"]["duties"]["gaps"] and body["correction_draft"] is not None
    assert body["next_moves"][0]["date"] == "2026-08-01"
