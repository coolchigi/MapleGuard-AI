"""Tests for the dashboard view model (api/dashboard.py) and the POST /dashboard endpoint.

Two layers, deliberately split:

  * The builder is pure, so it is tested directly with no FastAPI import — those tests run on
    the bare-core environment.
  * The endpoint tests go through the TestClient and are skipped when FastAPI is absent, the
    same posture as test_api.py.

The load-bearing property here is *agreement*: every number the dashboard reports must be the
number `crs`/`trajectory`/`deadlines` already returned. The view model is allowed to add labels
and grouping; it is not allowed to add arithmetic. Several tests below assert exactly that by
recomputing from the engine and comparing.
"""
from datetime import date

import pytest

from api.dashboard import build_dashboard, dashboard_from_dict
from crs import LanguageScores, Profile, crs, deadlines, trajectory

AS_OF = date(2026, 8, 22)
HORIZON = date(2029, 12, 31)


def L(clb: int) -> LanguageScores:
    return LanguageScores(clb, clb, clb, clb)


def _profile(**overrides) -> Profile:
    base = dict(
        education="bachelors-or-three-year",
        first_language=L(9),
        date_of_birth=date(1994, 11, 3),
        canadian_work_years=2,
        foreign_work_years=3,
        first_language_test_date=date(2025, 3, 1),
    )
    base.update(overrides)
    return Profile(**base)


PROFILE_DICT = {
    "education": "bachelors-or-three-year",
    "first_language": {"speaking": 9, "listening": 9, "reading": 9, "writing": 9},
    "date_of_birth": "1994-11-03",
    "canadian_work_years": 2,
    "foreign_work_years": 3,
    "first_language_test_date": "2025-03-01",
}


def _by_code(doc: dict) -> dict:
    return {c["code"]: c for c in doc["position"]["categories"]}


# --- the builder agrees with the engine ------------------------------------------------
def test_totals_are_the_engines_totals():
    p = _profile()
    score = crs(p, AS_OF)
    pos = build_dashboard(p, as_of=AS_OF, horizon=HORIZON)["position"]

    assert pos["total"] == score.total
    assert pos["core"] == score.core
    assert pos["spouse"] == score.spouse
    assert pos["skillTransfer"] == score.skill_transfer
    assert pos["additional"] == score.additional


def test_category_subtotals_and_caps_come_from_the_engine():
    from crs import tables as T

    score = crs(_profile(), AS_OF)
    cats = _by_code(build_dashboard(_profile(), as_of=AS_OF, horizon=HORIZON))

    assert (cats["A"]["subtotal"], cats["A"]["cap"]) == (score.core, T.CORE_MAX_SINGLE)
    assert (cats["B"]["subtotal"], cats["B"]["cap"]) == (score.skill_transfer,
                                                         T.SKILL_TRANSFER_MAX)
    assert (cats["C"]["subtotal"], cats["C"]["cap"]) == (score.additional, T.ADDITIONAL_MAX)


def test_core_line_items_sum_to_the_uncapped_core_breakdown():
    """The view model must not invent or drop a line: the core items are exactly the engine's
    core breakdown, factor for factor."""
    p = _profile()
    engine_core = {li.factor: li.points for li in crs(p, AS_OF).breakdown
                   if li.factor in ("age", "education", "first_language",
                                    "second_language", "canadian_work")}
    items = _by_code(build_dashboard(p, as_of=AS_OF, horizon=HORIZON))["A"]["items"]

    assert len(items) == len(engine_core)
    assert sum(i["points"] for i in items) == sum(engine_core.values())


def test_trajectory_points_and_cliffs_match_the_timeline():
    p = _profile()
    traj = trajectory(p, AS_OF, HORIZON)
    doc = build_dashboard(p, as_of=AS_OF, horizon=HORIZON)["trajectory"]

    assert [pt["date"] for pt in doc["points"]] == [pt.date.isoformat() for pt in traj.points]
    assert [pt["total"] for pt in doc["points"]] == [pt.total for pt in traj.points]
    assert [c["delta"] for c in doc["cliffs"]] == [c.delta for c in traj.cliffs]
    assert doc["endTotal"] == traj.points[-1].total


def test_test_expiry_matches_deadlines():
    p = _profile()
    dl = deadlines(p, as_of=AS_OF)
    doc = build_dashboard(p, as_of=AS_OF, horizon=HORIZON)["trajectory"]

    assert doc["testExpiry"] == dl.test_expiry.isoformat()
    assert doc["testExpiryDelta"] == dl.test_expiry_cliff.delta
    assert doc["daysToExpiry"] == (dl.test_expiry - AS_OF).days


def test_no_language_test_date_leaves_the_expiry_fields_null():
    doc = build_dashboard(_profile(first_language_test_date=None),
                          as_of=AS_OF, horizon=HORIZON)["trajectory"]
    assert doc["testExpiry"] is None
    assert doc["testExpiryHuman"] is None
    assert doc["testExpiryDelta"] is None
    assert doc["daysToExpiry"] is None
    assert doc["points"]  # the age trajectory still runs


def test_last_draw_delta_is_total_minus_cutoff():
    doc = build_dashboard(_profile(), as_of=AS_OF, horizon=HORIZON,
                          last_draw_score=500, last_draw_date="2026-08-06")
    assert doc["lastDraw"]["score"] == 500
    assert doc["lastDraw"]["delta"] == doc["position"]["total"] - 500


# --- shape rules the client depends on -------------------------------------------------
def test_single_applicant_has_no_spouse_category():
    assert "S" not in _by_code(build_dashboard(_profile(), as_of=AS_OF, horizon=HORIZON))


def test_accompanying_spouse_adds_a_scored_category():
    p = _profile(marital_status="married", spouse_accompanying=True,
                 spouse_education="bachelors-or-three-year", spouse_first_language=L(7),
                 spouse_canadian_work_years=1)
    doc = build_dashboard(p, as_of=AS_OF, horizon=HORIZON)
    cats = _by_code(doc)

    assert "S" in cats
    assert cats["S"]["subtotal"] == crs(p, AS_OF).spouse > 0
    # the core grid switches to the spouse column, which caps lower
    assert cats["A"]["cap"] == 460
    assert [c["code"] for c in doc["position"]["categories"]] == ["A", "S", "B", "C"]


def test_spouse_who_is_already_pr_is_not_scored():
    p = _profile(marital_status="married", spouse_accompanying=True, spouse_is_pr_or_citizen=True,
                 spouse_first_language=L(9))
    assert "S" not in _by_code(build_dashboard(p, as_of=AS_OF, horizon=HORIZON))


def test_unclaimed_additional_factors_are_levers_claimed_ones_are_items():
    doc = build_dashboard(_profile(has_provincial_nomination=True, has_sibling_in_canada=True),
                          as_of=AS_OF, horizon=HORIZON)
    add = _by_code(doc)["C"]

    claimed = {i["label"] for i in add["items"]}
    assert claimed == {"Provincial nomination", "Sibling in Canada"}
    assert {lv["label"] for lv in add["levers"]} == {"Canadian study", "French-language bonus"}
    # 600 + 15, clamped by the engine to the 600 category cap: the view model reports the
    # capped subtotal, not the sum of its own line items.
    assert sum(i["points"] for i in add["items"]) == 615
    assert add["subtotal"] == 600


def test_no_additional_factors_means_levers_only():
    add = _by_code(build_dashboard(_profile(), as_of=AS_OF, horizon=HORIZON))["C"]
    assert "items" not in add
    assert len(add["levers"]) == 4


def test_certificate_of_qualification_adds_its_transfer_line():
    doc = build_dashboard(_profile(has_certificate_of_qualification=True),
                          as_of=AS_OF, horizon=HORIZON)
    labels = [i["label"] for i in _by_code(doc)["B"]["items"]]
    assert any("Certificate of qualification" in lb for lb in labels)


def test_uneven_language_abilities_are_labelled_per_ability():
    p = _profile(first_language=LanguageScores(speaking=9, listening=8, reading=10, writing=7))
    items = _by_code(build_dashboard(p, as_of=AS_OF, horizon=HORIZON))["A"]["items"]
    first = next(i for i in items if i["label"].startswith("First language"))
    assert first["label"] == "First language · CLB 9/8/10/7"
    assert "meta" not in first  # no "x 4 abilities" claim when they are not equal


def test_second_language_in_french_is_named_and_scored():
    p = _profile(second_language=L(7), second_language_is_french=True)
    doc = build_dashboard(p, as_of=AS_OF, horizon=HORIZON)
    second = next(i for i in _by_code(doc)["A"]["items"] if i["label"].startswith("Second"))
    assert "French" in second["label"] and "CLB 7" in second["label"]
    assert second["points"] > 0
    assert any(i["label"] == "French-language bonus" for i in _by_code(doc)["C"]["items"])


def test_every_category_carries_a_note_and_a_citation():
    doc = build_dashboard(_profile(marital_status="common-law", spouse_accompanying=True,
                                   spouse_first_language=L(8)), as_of=AS_OF, horizon=HORIZON)
    for cat in doc["position"]["categories"]:
        assert cat["note"] and cat["cite"]


def test_human_dates_are_rendered_without_platform_specific_strftime():
    doc = build_dashboard(_profile(), as_of=AS_OF, horizon=HORIZON)
    assert doc["asOfHuman"] == "Aug 22, 2026"          # no zero padding on the day
    assert doc["trajectory"]["testExpiryHuman"] == "Mar 1, 2027"


# --- refusals --------------------------------------------------------------------------
def test_a_profile_without_a_birthdate_is_refused():
    p = Profile(education="secondary", first_language=L(7), age=30)
    with pytest.raises(ValueError, match="date_of_birth"):
        build_dashboard(p, as_of=AS_OF, horizon=HORIZON)


def test_horizon_must_be_after_as_of():
    with pytest.raises(ValueError, match="horizon"):
        build_dashboard(_profile(), as_of=AS_OF, horizon=date(2026, 1, 1))


def test_horizon_years_defaults_to_three_years_forward():
    doc = build_dashboard(_profile(), as_of=AS_OF)
    assert doc["trajectory"]["points"][-1]["date"] == "2029-08-22"


# --- the dict boundary (what the HTTP layer calls) --------------------------------------
def test_dashboard_from_dict_matches_the_typed_builder():
    from_dict = dashboard_from_dict(PROFILE_DICT, as_of="2026-08-22", horizon_years=3)
    typed = build_dashboard(_profile(), as_of=AS_OF, horizon_years=3)
    assert from_dict == typed


def test_dashboard_from_dict_rejects_a_malformed_profile():
    with pytest.raises((KeyError, ValueError, TypeError)):
        dashboard_from_dict({"first_language": {"speaking": 9}})  # no education


def test_the_precomputed_demo_file_is_what_the_builder_produces():
    """web/src/data/demo.json is the client's offline fallback. If this fails, the engine moved
    and the file is stale: re-run `PYTHONPATH=server python3 web/scripts/precompute.py`."""
    import json
    import pathlib

    demo = pathlib.Path(__file__).resolve().parents[2] / "web" / "src" / "data" / "demo.json"
    if not demo.exists():
        pytest.skip("web/src/data/demo.json not present")
    on_disk = json.loads(demo.read_text(encoding="utf-8"))

    fresh = build_dashboard(_profile(), as_of=AS_OF, horizon=HORIZON,
                            generated_by=on_disk["generatedBy"])
    assert fresh == on_disk


# --- the endpoint ----------------------------------------------------------------------
fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from api import create_app  # noqa: E402
from api.model_config import NocModel  # noqa: E402


def _client():
    """The dashboard is purely deterministic, so an unconfigured NOC model is fine here — it
    only gates /audit and /draft."""
    return TestClient(create_app(noc_model=NocModel(matcher=None, corrector=None,
                                                    configured=False, backend="none",
                                                    model="", detail="not needed")))


def test_endpoint_returns_the_same_document_as_the_builder():
    r = _client().post("/dashboard", json={"profile": PROFILE_DICT, "as_of": "2026-08-22"})
    assert r.status_code == 200
    assert r.json() == build_dashboard(_profile(), as_of=AS_OF, horizon_years=3)


def test_endpoint_agrees_with_position_and_trajectory_endpoints():
    """/dashboard is a composite; it must not disagree with its parts."""
    c = _client()
    doc = c.post("/dashboard", json={"profile": PROFILE_DICT, "as_of": "2026-08-22"}).json()
    pos = c.post("/position", json={"profile": PROFILE_DICT, "as_of": "2026-08-22"}).json()
    traj = c.post("/trajectory", json={"profile": PROFILE_DICT, "start": "2026-08-22",
                                       "end": "2029-08-22"}).json()

    assert doc["position"]["total"] == pos["total"]
    assert doc["position"]["core"] == pos["core"]
    assert [p["total"] for p in doc["trajectory"]["points"]] == [p["total"] for p in
                                                                 traj["points"]]


def test_endpoint_accepts_a_last_draw_override():
    r = _client().post("/dashboard", json={"profile": PROFILE_DICT, "as_of": "2026-08-22",
                                           "last_draw_score": 470,
                                           "last_draw_date": "2026-08-20"})
    body = r.json()
    assert body["lastDraw"] == {"score": 470, "delta": body["position"]["total"] - 470,
                                "cite": "canada.ca/rounds-of-invitations", "date": "2026-08-20"}


def test_endpoint_defaults_as_of_to_today():
    from datetime import date as _date
    r = _client().post("/dashboard", json={"profile": PROFILE_DICT})
    assert r.status_code == 200
    assert r.json()["asOf"] == _date.today().isoformat()


def test_endpoint_422s_on_a_static_age_profile():
    r = _client().post("/dashboard", json={"profile": {**{k: v for k, v in PROFILE_DICT.items()
                                                          if k != "date_of_birth"}, "age": 31}})
    assert r.status_code == 422
    assert "date_of_birth" in r.json()["detail"]


def test_endpoint_422s_on_a_malformed_profile():
    r = _client().post("/dashboard", json={"profile": {"first_language": {"speaking": 9}}})
    assert r.status_code == 422


def test_endpoint_rejects_an_out_of_range_horizon():
    r = _client().post("/dashboard", json={"profile": PROFILE_DICT, "horizon_years": 0})
    assert r.status_code == 422  # pydantic ge=1 on the envelope
