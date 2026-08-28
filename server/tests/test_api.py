"""Tests for the FastAPI layer.

Offline and deterministic. `importorskip("fastapi")` skips the whole module when FastAPI is not
installed, so `cd server && PYTHONPATH=. python3 -m pytest -q` stays green on the pure-core
environment; with FastAPI present, the endpoints are driven end to end through the SDK's
TestClient with fake model clients and an injected draws fetcher, so no network is touched.
"""
import json
import pathlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # required by fastapi.testclient

from fastapi.testclient import TestClient  # noqa: E402

from api import create_app  # noqa: E402
from api.model_config import NocModel  # noqa: E402

PROFILE = {
    "education": "bachelors-or-three-year",
    "first_language": {"speaking": 9, "listening": 9, "reading": 9, "writing": 9},
    "date_of_birth": "1996-07-01",
    "canadian_work_years": 1,
    "first_language_test_date": "2025-09-30",
}

AUDIT_LETTER = ("This confirms Jane Doe worked as a Web Developer. She works 37.5 hours per "
                "week at $85,000 per year. Monitor and maintain website functionality. "
                "Develop and implement procedures for ongoing website revision. Sincerely.")


def _fake_matcher(letter_text, occupation):
    return ({"21234.4": "Monitor and maintain website functionality.",
             "21234.3": "Develop and implement procedures for ongoing website revision."},
            "worked as a Web Developer")


class _FakeCorrector:
    def __call__(self, letter_text, occupation, coverage, supporting_facts=None):
        from noc import CorrectionDraft
        return CorrectionDraft(letter_text="Revised letter. [employer to confirm: something]",
                               placeholders=["[employer to confirm: something]"])


def _model(configured=True):
    return NocModel(matcher=_fake_matcher if configured else None,
                    corrector=_FakeCorrector() if configured else None,
                    configured=configured, backend="fake", model="fake-model",
                    detail="" if configured else "no key")


def _client(configured=True, draws_fetcher=None):
    return TestClient(create_app(noc_model=_model(configured), draws_fetcher=draws_fetcher))


# --- health + model status -----------------------------------------------------------
def test_health_reports_model_status():
    r = _client().get("/health")
    assert r.status_code == 200
    assert r.json()["noc_model"]["configured"] is True


# --- deterministic compute endpoints -------------------------------------------------
def test_position_matches_the_engine():
    from crs import LanguageScores, Profile, crs
    from datetime import date
    r = _client().post("/position", json={"profile": PROFILE, "as_of": "2026-08-25"})
    assert r.status_code == 200
    body = r.json()
    expected = crs(Profile(education="bachelors-or-three-year",
                           first_language=LanguageScores(9, 9, 9, 9),
                           date_of_birth=date(1996, 7, 1), canadian_work_years=1),
                   date(2026, 8, 25))
    assert body["total"] == expected.total
    assert body["core"] + body["spouse"] + body["skill_transfer"] + body["additional"] \
        == body["total"]


def test_trajectory_and_sirs_and_deadlines():
    c = _client()
    traj = c.post("/trajectory", json={"profile": PROFILE, "start": "2026-08-25",
                                       "end": "2028-01-01"})
    assert traj.status_code == 200 and traj.json()["points"][0]["date"] == "2026-08-25"
    sirs = c.post("/sirs", json={"profile": PROFILE})
    assert sirs.status_code == 200 and sirs.json()["job_offer_required"] is True
    dl = c.post("/deadlines", json={"profile": PROFILE, "as_of": "2026-08-25"})
    assert dl.status_code == 200 and dl.json()["test_expiry"] == "2027-09-30"


def test_reachable_paths_classifies_and_keeps_citations():
    total = _client().post("/position", json={"profile": PROFILE,
                                              "as_of": "2026-08-25"}).json()["total"]
    draws = [{"kind": "general", "name": "EE #340", "cutoff": total - 10, "date": "2026-08-06",
              "source": "https://www.canada.ca/x"}]
    r = _client().post("/reachable-paths", json={"profile": PROFILE, "draws": draws,
                                                 "as_of": "2026-08-25"})
    assert r.status_code == 200
    assert len(r.json()["reachable"]) == 1 and r.json()["reachable"][0]["clears"] is True


def test_malformed_profile_is_422_not_500():
    r = _client().post("/position", json={"profile": {"education": "bachelors-or-three-year"}})
    assert r.status_code == 422  # missing first_language -> serde raises -> mapped, not a crash


def test_uncited_draw_is_422():
    draws = [{"kind": "general", "name": "mystery", "cutoff": 400, "date": "2026-08-06"}]
    r = _client().post("/reachable-paths", json={"profile": PROFILE, "draws": draws})
    assert r.status_code == 422 and "source" in r.json()["detail"]


# --- NOC model-backed endpoints ------------------------------------------------------
def test_audit_endpoint_runs_with_a_fake_model():
    r = _client().post("/audit", json={"letter_text": AUDIT_LETTER, "noc_code": "21234"})
    assert r.status_code == 200
    body = r.json()
    assert body["noc_code"] == "21234" and body["duties"]["required"] == 4
    assert all(g["noc_code"] == "21234" and g["source"] for g in body["duties"]["gaps"])


def test_draft_endpoint_keeps_placeholders():
    r = _client().post("/draft", json={"letter_text": AUDIT_LETTER, "noc_code": "21234",
                                       "supporting_facts": ["She also tested the code."]})
    assert r.status_code == 200
    body = r.json()
    assert body["has_open_gaps"] is True and body["placeholders"]


def test_unknown_noc_is_404():
    r = _client().post("/audit", json={"letter_text": AUDIT_LETTER, "noc_code": "00000"})
    assert r.status_code == 404


def test_audit_returns_503_when_model_unconfigured():
    r = _client(configured=False).post("/audit",
                                       json={"letter_text": AUDIT_LETTER, "noc_code": "21234"})
    assert r.status_code == 503 and "not configured" in r.json()["detail"]


# --- live data endpoint (injected fetcher, no network) -------------------------------
def test_draws_endpoint_uses_injected_fetcher():
    doc = (pathlib.Path(__file__).parent.parent / "ingest" / "fixtures"
           / "ee_rounds_sample.json").read_text()
    r = _client(draws_fetcher=lambda: doc).get("/draws")
    assert r.status_code == 200
    assert r.json()["draws"] and all(d["source"] for d in r.json()["draws"])


def test_draws_endpoint_502_on_fetch_failure():
    def boom():
        raise ConnectionError("feed down")
    r = _client(draws_fetcher=boom).get("/draws")
    assert r.status_code == 502


# --- Optional live test: only with a real Claude model configured --------------------
import os  # noqa: E402


@pytest.mark.skipif(
    not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("MAPLEGUARD_NOC_BACKEND")),
    reason="set ANTHROPIC_API_KEY (or MAPLEGUARD_NOC_BACKEND=bedrock + AWS) to run the real model",
)
def test_audit_and_draft_live_model():
    from api.model_config import build_noc_model
    model = build_noc_model()
    if not model.configured:
        pytest.skip(f"model not configured: {model.detail}")
    c = TestClient(create_app(noc_model=model))
    a = c.post("/audit", json={"letter_text": AUDIT_LETTER, "noc_code": "21234"})
    assert a.status_code == 200 and a.json()["duties"]["required"] == 4
    d = c.post("/draft", json={"letter_text": AUDIT_LETTER, "noc_code": "21234"})
    assert d.status_code == 200 and "letter_text" in d.json()
    # The model must never assert eligibility in the drafted letter.
    from agent.orchestrator import screen_response
    assert screen_response(d.json()["letter_text"]).allowed
