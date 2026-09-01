"""The MapleGuard HTTP API — a thin FastAPI layer over the deterministic core + NOC model.

This is the backend the Next.js dashboard calls. It is deliberately thin: every endpoint
deserializes JSON, calls a pure function (or the model-backed NOC audit/draft), and returns the
typed result with its citations intact. No arithmetic lives here; `serde` + the `agent.tools`
wrappers are the single, already-tested path, so the API cannot drift from the engine.

The 0-latency split (per ARCHITECTURE.md): the web app runs the deterministic math client-side
(Pyodide) for the instant position panel and the what-if / time-machine scrubber, so those need
no round trip. The server exists for what the browser cannot do: the model-backed NOC audit and
correction draft (`/audit`, `/draft`), and live data (`/draws`). The compute endpoints
(`/position`, `/trajectory`, `/reachable-paths`, `/sirs`) are here too as the server-side source
of truth (and for any non-Pyodide client), taking the profile in the POST body since they
require input. `/dashboard` is the composite of those the Next.js app actually calls: one POST
of a profile in, the whole rendered document out.

Everything is injectable so the whole API tests offline with fakes and no network:
`create_app(noc_model=..., draws_fetcher=...)`. With nothing injected it builds the real NOC
model from the environment (see `model_config`); when that is unconfigured, `/audit` and
`/draft` answer 503 with the reason rather than crashing.
"""
from __future__ import annotations

from typing import Any, Optional

from agent import serde
from agent.tools import (audit_reference_letter, compute_crs, configure_deps, crs_deadlines,
                         crs_trajectory, ingest_draws, reachable_paths, sirs_bc)
from noc import get_occupation

from .dashboard import dashboard_from_dict
from .model_config import NocModel, build_noc_model
from .schemas import (AuditRequest, BriefRequest, DashboardRequest, DeadlinesRequest, DraftRequest,
                      DrawsResponse, PositionRequest, ProfileSaveRequest, ReachableRequest,
                      ReferenceLetter, SirsRequest, TrajectoryRequest)


def create_app(noc_model: Optional[NocModel] = None,
               draws_fetcher: Optional[Any] = None,
               corpus: Any = None,
               profile_store: Any = None,
               brief_narrator: Any = None):
    """Build the FastAPI app. `noc_model` injects matcher+corrector (a fake in tests); if None,
    it is built from the environment. `draws_fetcher` is a callable returning the raw IRCC
    rounds JSON for `/draws` (injected in tests; defaults to the live fetch). `corpus` is an
    optional memory store to re-source NOC audit citations from live retrieval. `profile_store`
    is the monitored-profile store `/profiles` writes (injected in tests; defaults to the
    env-selected store — file locally, DynamoDB in deploy — the SAME store the monitor lists)."""
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware

    model = noc_model if noc_model is not None else build_noc_model()
    if profile_store is None:
        from agent.config import Deployment, build_profile_store
        profile_store = build_profile_store(Deployment.from_env())
    # Point the model-backed tools at these clients (and the optional citation corpus). Set once
    # at startup; the deterministic tools ignore it.
    configure_deps(matcher=model.matcher, corrector=model.corrector, corpus=corpus)

    app = FastAPI(title="MapleGuard API", version="1.0.0",
                  description="Deterministic Canadian-immigration position + cited NOC audit.")
    # The dashboard is a separate origin; allow browser calls. No credentials, so wildcard is safe.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])

    def _compute(fn, *args, **kwargs):
        """Run a deterministic tool, mapping a bad profile/draw (serde raises) to HTTP 422."""
        try:
            return fn(*args, **kwargs)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    def _require_model():
        if not model.configured:
            raise HTTPException(status_code=503,
                                detail=f"NOC model not configured: {model.detail}")

    def _occupation_or_404(noc_code: str):
        try:
            return get_occupation(noc_code)
        except (KeyError, ValueError):
            raise HTTPException(status_code=404, detail=f"unknown NOC code {noc_code!r}")

    # ---------------------------------------------------------------- health / meta
    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "noc_model": {"configured": model.configured,
                "backend": model.backend, "model": model.model, "detail": model.detail}}

    # ---------------------------------------------------------------- NOC (model-backed)
    @app.post("/audit")
    def audit(req: AuditRequest) -> dict:
        _require_model()
        _occupation_or_404(req.noc_code)
        return _compute(audit_reference_letter, req.letter_text, req.noc_code)

    @app.post("/draft")
    def draft(req: DraftRequest) -> dict:
        _require_model()
        _occupation_or_404(req.noc_code)
        return _compute(draft_from_tool, req.letter_text, req.noc_code, req.supporting_facts)

    @app.post("/brief")
    def brief(req: BriefRequest) -> dict:
        """The consultant brief: CRS position, dated cliffs, ranked next moves, and (when a letter
        is supplied) the cited NOC gaps + the drafted correction — one document to hand a consultant.
        Every number/citation is from the deterministic core; the cover prose (if a narrator is
        configured) is screened for eligibility verdicts. Never asserts eligibility, never submits."""
        from .brief import assemble_brief
        if req.noc_code and req.letter_text:
            _require_model()                 # the letter audit/draft need the model
            _occupation_or_404(req.noc_code)
        return _compute(assemble_brief, req.profile, noc_code=req.noc_code,
                        letter_text=req.letter_text, draws=req.draws,
                        supporting_facts=req.supporting_facts, as_of=req.as_of,
                        narrator=brief_narrator)

    # ---------------------------------------------------------------- intake (monitored set)
    @app.post("/profiles")
    def save_profile(req: ProfileSaveRequest) -> dict:
        """Persist a profile into the monitored set — this is the intake that puts a candidate in
        front of the autonomous monitor. The profile is validated through the SAME serde path as
        /position and /dashboard (a malformed profile answers 422), then stored under a stable id
        (generated if omitted). The monitor lists this exact store, so a saved profile is watched
        with no hand-seeding."""
        import uuid

        from agent.monitor import StoredProfile
        _compute(serde.profile_from_dict, req.profile)  # validate; raises -> 422
        profile_id = req.id or uuid.uuid4().hex
        letter = req.reference_letter.model_dump() if req.reference_letter is not None else None
        profile_store.put(StoredProfile(id=profile_id, profile=req.profile, bc_offer=req.bc_offer,
                                        reference_letter=letter))
        return {"id": profile_id, "monitored": True}

    @app.put("/profiles/{profile_id}/letter")
    def attach_letter(profile_id: str, req: ReferenceLetter) -> dict:
        """Store an employer reference letter on an existing profile, so a NOC-type policy change
        (e.g. the NOC 2016->TEER 2021 reclassification) can re-audit it. PII note: the letter is
        stored unscrubbed until Guardrails PII redaction is provisioned (flagged, not faked)."""
        from agent.monitor import StoredProfile
        sp = profile_store.get(profile_id)
        if sp is None:
            raise HTTPException(status_code=404, detail=f"no monitored profile {profile_id!r}")
        profile_store.put(StoredProfile(id=sp.id, profile=sp.profile, bc_offer=sp.bc_offer,
                                        reference_letter=req.model_dump()))
        return {"id": profile_id, "letter_stored": True, "noc_code": req.noc_code}

    @app.get("/profiles")
    def list_profiles() -> dict:
        """The ids in the monitored set (ids only — the profiles carry personal data; fetch one by
        id). This is what the monitor scans each tick."""
        return {"profiles": [{"id": p.id} for p in profile_store.list_profiles()]}

    @app.get("/profiles/{profile_id}")
    def get_profile(profile_id: str) -> dict:
        sp = profile_store.get(profile_id)
        if sp is None:
            raise HTTPException(status_code=404, detail=f"no monitored profile {profile_id!r}")
        return sp.to_dict()

    # ---------------------------------------------------------------- deterministic compute
    @app.post("/position")
    def position(req: PositionRequest) -> dict:
        return _compute(compute_crs, req.profile, as_of=req.as_of)

    @app.post("/trajectory")
    def trajectory(req: TrajectoryRequest) -> dict:
        return _compute(crs_trajectory, req.profile, start=req.start, end=req.end)

    @app.post("/deadlines")
    def deadlines(req: DeadlinesRequest) -> dict:
        return _compute(crs_deadlines, req.profile, as_of=req.as_of)

    @app.post("/dashboard")
    def dashboard(req: DashboardRequest) -> dict:
        """Everything the web dashboard renders, in one round trip: the position categories
        (with their IRCC caps and per-factor line items) and the time-machine trajectory with
        its dated cliffs. Equivalent to /position + /trajectory + /deadlines, grouped and
        labelled — and shape-identical to the precomputed web/src/data/demo.json, so the client
        can fall back to that file with the same type when the server is unreachable.

        Needs a date_of_birth on the profile; a static `age` cannot be run forward over dates
        and answers 422."""
        return _compute(dashboard_from_dict, req.profile, as_of=req.as_of,
                        horizon_years=req.horizon_years,
                        last_draw_score=req.last_draw_score,
                        last_draw_date=req.last_draw_date)

    @app.post("/sirs")
    def sirs(req: SirsRequest) -> dict:
        return _compute(sirs_bc, req.profile, offer=req.offer)

    @app.post("/reachable-paths")
    def reachable(req: ReachableRequest) -> dict:
        return _compute(reachable_paths, req.profile, req.draws, as_of=req.as_of,
                        bc_offer=req.bc_offer)

    # ---------------------------------------------------------------- live data
    @app.get("/draws", response_model=None)
    def draws() -> dict:
        """Ingest the current IRCC rounds feed into cited draws. Live I/O: uses the injected
        fetcher, or `ingest.fetch_rounds_json` by default. Returns usable draws + any records
        flagged needs_manual_check."""
        from ingest import ROUNDS_JSON_URL
        fetch = draws_fetcher or _default_draws_fetcher
        try:
            raw = fetch()
        except Exception as exc:  # network/parse failure is a 502, not a crash
            raise HTTPException(status_code=502, detail=f"could not fetch draws feed: {exc}")
        return _compute(ingest_draws, raw, source_url=ROUNDS_JSON_URL)

    return app


def draft_from_tool(letter_text: str, noc_code: str, supporting_facts):
    """Adapter so the /draft endpoint passes supporting_facts positionally the way the tool
    wrapper expects (keeps create_app readable)."""
    from agent.tools import draft_corrected_letter
    return draft_corrected_letter(letter_text, noc_code, supporting_facts or None)


def _default_draws_fetcher() -> str:
    from ingest import fetch_rounds_json
    return fetch_rounds_json()
