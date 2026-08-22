# MapleGuard — build status (cross-session tracker)

Single source of truth for what is done and what is outstanding. Update as you go.
Spec: `../concept-spec-mapleguard.md` · Why/value: `../why-mapleguard.md`.
Run tests: `cd agents-for-humans/mapleguard && PYTHONPATH=. python3 -m pytest -q`

**Status 2026-08-22:** 40 tests green + 1 xfail (CRS + timeline + SIRS + NOC + reachable-paths). CRS engine validated against IRCC's official tool (golden oracle 474). Deterministic core now complete end to end: `crs` → `trajectory`/`deadlines` → `sirs_bc` → `reachable_paths` (the interpretation layer). NOC audit core done bar the LLM matcher. Nothing deployed yet.

> Note: the CRS `engine.py`/`tables.py` were rebuilt on 2026-08-21 after an accidental overwrite; the rebuild passes every prior test including the 474 oracle and the skill-transfer anchors, so it is functionally the restored engine.

---

## Feature 3 — Deterministic position engine (the heart)
- [x] **CRS core human capital** — age (date-independent int for now), education, first/second language, Canadian work. Single + spouse tables.
- [x] **Skill transferability** — 3 groups, each two components capped 50, overall 100, graduated 13/25/50 by tier + CLB7/CLB9 threshold. Lone-bachelor over-count trap handled. Anchored by tests.
- [x] **Additional points** — PNP +600, sibling +15, Canadian study +15/+30, French bonus +25/+50, arranged-employment pinned 0 (removed 2025-03-25).
- [x] **Provenance gate** — every table `verified=True`; `test_table_provenance` green.
- [x] **Golden oracle** — owner's real profile confirmed 474 on the official IRCC tool.
- [ ] **More oracle cases** — reconstruct the ImmiPilot 444 profile, get its official number, lock it as a test (find which factor incumbents break). [needs inputs]
- [x] **Date-parameterize** — `crs(profile, as_of)` derives age from DOB; static `age` still works.
- [x] **`trajectory` + `deadlines`** (`crs/timeline.py`) — age-bracket drops + test expiry (2-yr validity, language points and their transfer drop to 0 on lapse), with dated cliffs and deltas. TODO later: upward Canadian-work anniversaries (needs a work-start date).
- [x] **`reachable_paths(profile, draws, as_of, bc_offer)`** (`paths/reach.py`) — classifies each live draw into reachable / within-reach / blocked / needs-NOC-check, with a ranked single-move catalog (language→CLB9/10, add French NCLC7, +1 Canadian year, +600 nomination) recomputed via the CRS engine. French-category eligibility derived; occupation categories honest-unknown unless caller-asserted; BC PNP scored via `sirs_bc` with the job-offer flag + 600 bonus surfaced. 8 tests.
- [x] **`sirs_bc(profile, offer)`** (`pnp/bc.py`) — BC SIRS 200-pt structure (work 40, edu 40, language 40, wage 55, area 25 = 120 human + 80 economic), +600-CRS nomination constant, `job_offer_required` + `eligible_to_register` flags, Tech-exempt handling. Structure/caps/flags tested.
  - [ ] **Verify SIRS bands** against the official BC PNP Program Guide (currently `verified=False`, xfail marker in place). Exact sub-scores not trustworthy until done.

## Feature 2 — NOC reference-letter pre-audit (the moat) — `noc/`
- [x] **NOC data model** — 2021 lead statement + main duties, seeded verbatim with source/version (NOC 21234 done, verified). `"May..."` duties optional.
- [x] **Mandatory-elements check** — deterministic PRESENT/MISSING/NEEDS_MANUAL_CHECK, conservative (MISSING only on confirmed absence).
- [x] **Duty-match scorer** — coverage vs required duties, 80% pass/fail, each gap cited; alignment validated so coverage can't be fabricated.
- [ ] **LLM duty matcher** — the real `DutyMatcher` producing the alignment (interface defined + stub-tested). Wire to a model, keep output validated.
- [ ] **Correction draft** — generate a revised letter matching the lead statement for the employer to sign. Never asserts eligibility.
- [ ] **Add target NOCs** — seed the codes relevant to BC Tech candidates (dev/software NOCs) the same verbatim way.

## Feature 1 — Research / ingestion agent
- [ ] **Draw + rule ingestion** — Open-Gov "rounds of invitations" XLSX primary, canada.ca table via Browser fallback. Every value stamped source URL + date.
- [ ] **Category rules** — the 10 2026 categories + eligibility (NOC lists / CLB7 French).
- [ ] **BC PNP watch** — BC PNP draw pages (Skilled Worker, Tech, sector) via Browser.
- [ ] **NOC text ingestion** — pull official NOC lead statements/duties on demand for B1.

## Feature 4 — Alerting engine (outbound email)
- [ ] **Snapshot + diff worker** — scheduled fetch, diff rules vs last snapshot, store snapshots in DynamoDB.
- [ ] **Profile correlation** — query which profiles a change/draw/deadline affects.
- [ ] **`deadlines()`-driven staleness alerts** — email before the test-expiry / age cliff.
- [ ] **SES send** — targeted email: the change, the impact, the reachable alternatives.

## Feature 5 — BC PNP window radar
- [ ] Scheduled BC PNP draw watch → `sirs_bc` score → cutoff match + job-offer flag → alert. (Lean on Tech pathway job-offer-exempt occupations.)

## Frontend (dashboard = proof surface) — Next.js on Vercel
- [ ] Position panel (CRS + "why this number" breakdown).
- [ ] **Time machine** (scrubbable trajectory, cliffs/windows) — the novelty spark.
- [ ] What-if sliders (deterministic recompute).
- [ ] NOC audit view (duty-by-duty diff + drafted correction).
- [ ] Cited change-log / inbox.
- [ ] Real-time updates (upload → live dashboard push).

## Safety + wiring
- [ ] **Strands agent** — single orchestrator + tools (engine, audit, ingestion). Not a swarm.
- [ ] **AgentCore** — deploy on Runtime; Code Interpreter (math), Memory (profile), Policy/Cedar (two gates: never submit / never assert eligibility), Observability (proof surface).
- [ ] **Bedrock Guardrails** — PII masking (UCI, passport, DOB) on all inbound/outbound + denied-topic "never assert eligibility."
- [ ] **DynamoDB** profile + snapshot store.

## Nice-to-haves (after the core is excellent — priority order)
- [ ] Email onboarding + intake (SES → Lambda PDF extract → Guardrails → profile → live update).
- [ ] Nova Sonic voice mode (talk to the agent / ask the dashboard).
- [ ] Browser Live-View last mile (human performs the submit).
- [ ] Multi-channel alerts (SMS / WhatsApp).
- [ ] Scenario saving/sharing for what-if; two specialist sub-agents if the orchestrator prompt bloats.

## Pre-commit gate (do before deep-investing in the lane)
- [ ] Novelty check: confirm no incumbent (Evola, ImmiPilot, Aïa, ImmiTrack, Visto AI) already ships the NOC-audit + reachable-path + eligibility-time-machine combination.
