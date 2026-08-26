# MapleGuard — build status (cross-session tracker)

Single source of truth for what is done and what is outstanding. Update as you go.
Spec: `../concept-spec-mapleguard.md` · Why/value: `../why-mapleguard.md`.
Run tests: `cd agents-for-humans/mapleguard && PYTHONPATH=. python3 -m pytest -q`

**Status 2026-08-22:** 66 passed, 2 skipped (live LLM), 1 xfail. CRS engine validated against IRCC's official tool (golden oracle 474). Deterministic core complete end to end: `crs` → `trajectory`/`deadlines` → `sirs_bc` → `reachable_paths`. **NOC feature complete**: LLM duty matcher, correction-draft generator, first three BC Tech NOCs, and the NEEDS_VERIFICATION guard, all merged to main. **Frontend designed** (not built): the position panel + time machine are locked in a Claude Design canvas (editorial + passport style, cited show-your-work breakdown, −149 test-expiry cliff) — artifact https://claude.ai/code/artifact/458b1662-5d86-40d7-bd26-f33068094f29. Nothing deployed yet.

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
- [x] **LLM duty matcher** — `LLMDutyMatcher` (`noc/matcher.py`) wired to Claude (default `claude-opus-5`), lazy client so import/construct needs no key or network. Returns verbatim-quote alignment; paraphrase/fabrication dropped by `validate_alignment`. 8 tests with a fake client + 1 skipif live integration test.
- [x] **Correction draft** — `LetterCorrector` (`noc/draft.py`) rewrites a gapped letter to align with the lead statement + cover flagged duties, for the employer to sign. Never asserts eligibility, never invents work: covers a duty only from the original letter or caller-supplied supporting facts, else leaves an `[employer to confirm: <duty>]` placeholder. Re-auditable: round-trip test drafts then re-runs `audit_letter` and sees supported gaps close while unsupported ones stay cited. 7 tests (fake client + substring matcher) + 1 skipif live test.
- [x] **Add target NOCs (first three)** — seeded 21231 (Software engineers and designers), 21232 (Software developers and programmers), 21230 (Computer systems developers and programmers) from the official ESDC profile (raw page text, 2026-08-22). Structure/counts/optional-flag tested. `verified=False`: still owe a human line-by-line check vs source before trusting for a real audit.
- [x] **NEEDS_VERIFICATION guard** — `audit_letter` stamps the `AuditReport` with `needs_verification=True` + a reason (naming the NOC code and source URL) whenever the occupation is `verified=False`. Deterministic, so it stays below the model. The audit still computes, but no caller can mistake an unverified-text result for a line-verified one; the flag + note also travel in `to_dict()`. Tested both ways.
- [ ] **`supporting_facts` provenance** — the corrector currently trusts caller-supplied facts as free text; real attestation + PII-gating belongs to the Feature 1 intake + Guardrails layer. Until then, drafted passages must be labelled caller-attested (not fact) and keep the `[employer to confirm: …]` gaps.
- [ ] **Seed remaining BC Tech NOCs** — 21311 / 22220 / 21233, the same verbatim way, when wiring the matcher to real use.

## Feature 1 — Research / ingestion agent
- [~] **Draw + rule ingestion** — draws done (`ingest/`): fetch+parse+cite of IRCC's official rounds-of-invitations JSON feed (`canada.ca/.../json/ee_rounds_123_en.json`) into typed `DrawRecord`s that `to_draw()` onto `paths.Draw`. Every value carries source URL + fetch date + round number; unparseable cutoff/date flags `needs_manual_check` (never guessed) and is refused entry to the engine. Thin fetch separated from pure parsing; real-data fixture + 15 tests, 1 skipif live fetch. TODO: category *rules* (below) and the Browser/XLSX fallback fetcher.
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
> Design locked in Claude Design (editorial + passport style, on real engine output): position panel + time machine. Working files in `../design/` (`Main.dc.html`, `TimeMachine.dc.html`, `canvas.json`). Artifact: https://claude.ai/code/artifact/458b1662-5d86-40d7-bd26-f33068094f29. The Next.js build below is still outstanding.
- [x] Position panel — designed (CRS + cited "why this number" breakdown, IRCC category caps sourced). [ ] build in Next.js.
- [x] **Time machine** — designed (step-chart trajectory + dated cliffs, −149 test-expiry hero). [ ] build in Next.js (make the scrubber interactive).
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
