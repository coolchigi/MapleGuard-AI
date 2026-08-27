# MapleGuard — build status (cross-session tracker)

Single source of truth for what is done and what is outstanding. Update as you go.
Spec: `../concept-spec-mapleguard.md` · Why/value: `../why-mapleguard.md`.
Run tests: `cd agents-for-humans/mapleguard && PYTHONPATH=. python3 -m pytest -q`

**Status 2026-08-26:** 127 passed, 16 skipped (live LLM/AWS), 1 xfail. Agent layer live (genuine Strands: tools + gates + cited-corpus memory + session storage). **Autonomous monitoring loop done** (Feature 4 core: scheduled tick → re-fetch → re-score → cited alert). **Category rules done** (Feature 1: occupation-category eligibility now decides). MIT LICENSE + architecture diagram + 4 technical blogs + session-coordination protocol added. Pushed to github.com/coolchigi/MapleGuard-AI. Pre-mortem priorities: ship a deployed screen (in progress) + the autonomous loop (done) + visible AgentCore (provisioning pending). CRS engine validated against IRCC's official tool (golden oracle 474). Deterministic core complete end to end: `crs` → `trajectory`/`deadlines` → `sirs_bc` → `reachable_paths`. **NOC feature complete**: LLM duty matcher, correction-draft generator, first three BC Tech NOCs, and the NEEDS_VERIFICATION guard, all merged to main. **Frontend designed** (not built): the position panel + time machine are locked in a Claude Design canvas (editorial + passport style, cited show-your-work breakdown, −149 test-expiry cliff) — artifact https://claude.ai/code/artifact/458b1662-5d86-40d7-bd26-f33068094f29. Nothing deployed yet.

> Note: the CRS `engine.py`/`tables.py` were rebuilt on 2026-08-21 after an accidental overwrite; the rebuild passes every prior test including the 474 oracle and the skill-transfer anchors, so it is functionally the restored engine.

> **PENDING (orchestrator, user-approved 2026-08-26):** restructure to `server/` (all Python: crs pnp paths noc ingest agent tests) + `web/` + `docs/`, in ONE pass the moment the AgentCore session merges (the quiet window). `git mv` to preserve history; update all doc/path references + the `PYTHONPATH` test command; then all sessions branch from the new layout. Do NOT start it while a Python builder has an unmerged branch.

---

## Feature 3 — Deterministic position engine (the heart)
- [x] **CRS core human capital** — age (date-independent int for now), education, first/second language, Canadian work. Single + spouse tables.
- [x] **Skill transferability** — 3 groups, each two components capped 50, overall 100, graduated 13/25/50 by tier + CLB7/CLB9 threshold. Lone-bachelor over-count trap handled. Anchored by tests.
- [x] **Additional points** — PNP +600, sibling +15, Canadian study +15/+30, French bonus +25/+50, arranged-employment pinned 0 (removed 2025-03-25).
- [x] **Provenance gate** — every table `verified=True`; `test_table_provenance` green.
- [x] **Golden oracle** — a Canadian-bachelor profile confirmed 474 on the official IRCC tool.
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
- [x] **Category rules** — the 10 official 2026 categories + eligibility (`ingest/categories.py`), verified 2026-08-26 against canada.ca `category-based-selection.html` (page dated 2026-06-22). Each occupation category's NOC 2021 list transcribed + completeness-checked (`verified=True`, cited); French is the NCLC-7 rule. `category_eligibility()` gives a deterministic cited verdict (in-list / not / unknown-if-no-input, never guessed). `resolve_category()` is the canonical slug vocabulary both ingest draw slugs and rule keys map through. Wired into `reachable_paths` via a new optional `Profile.noc_code`: occupation categories now decide instead of always `needs_eligibility_check`. 13 tests. NOTE: agriculture/agri-food is NOT a 2026 category (verifying kept it out).
- [ ] **BC PNP watch** — BC PNP draw pages (Skilled Worker, Tech, sector) via Browser.
- [ ] **NOC text ingestion** — pull official NOC lead statements/duties on demand for B1.

## Feature 4 — Alerting engine (outbound email) — `agent/monitor` (autonomous loop)
- [x] **Snapshot + diff worker** — `tick(deps, as_of)` ingests latest draws, diffs vs stored snapshot (via `sort_records`), saves snapshot. `scheduled_handler` is the cron/EventBridge entrypoint (the unprompted scheduled invocation IS the autonomy). Store behind an interface: InMemory/File dev, DynamoDB marked seam.
- [x] **Profile correlation** — re-scores every stored profile (`reachable_paths` + `deadlines`) and emits a cited alert per affected profile. Relevance filter: only a self-actionable move triggers (not the universal +600), so silence is a feature.
- [x] **`deadlines()`-driven staleness alerts** — test-expiry / age cliffs carried as cited context in the alert.
- [~] **SES send** — `CollectingAlertSink` produces + logs the alert; SES send is a marked seam, the final send stays gated (compute-and-refuse on the button). No email leaves the module yet.
- Note: the Strands agent attaches as an optional narrator that phrases the finished payload; the diff + alert DECISION is pure Python (LLM not in the decision path).

## Feature 5 — BC PNP window radar
- [ ] Scheduled BC PNP draw watch → `sirs_bc` score → cutoff match + job-offer flag → alert. (Lean on Tech pathway job-offer-exempt occupations.)

## Frontend (dashboard = proof surface) — Next.js on Vercel
> Design locked in Claude Design (editorial + passport style, on real engine output): position panel + time machine. Working files in `../design/` (`Main.dc.html`, `TimeMachine.dc.html`, `canvas.json`). Artifact: https://claude.ai/code/artifact/458b1662-5d86-40d7-bd26-f33068094f29. The Next.js build below is still outstanding.
- [x] Position panel — BUILT (`web/`, Next.js): cited CRS breakdown + COMPUTED/NOT ADJUDICATED stamp, static.
- [x] **Time machine — BUILT and interactive** (`web/`): drag the scrubber across dates (mouse/touch/keyboard) and the CRS number falls at each REAL cliff (496→491→342 test-expiry −149→336→331→325). Hero number, step-line dot, "−N from today", and cliff row all track live. Numbers precomputed from the real engine (`web/scripts/precompute.py` → `demo.json`); nothing Python runs at serve. Static build passes, desktop + mobile verified.
- [ ] **Deploy to Vercel** — needs the user's Vercel account: `cd web && vercel` (set Root Directory = web), then `vercel --prod`. No env vars. Steps in `web/README.md`.
- [ ] **What-if scrub (live recompute)** — client-side deterministic engine (Pyodide per ARCHITECTURE.md), so sliders recompute CRS in-browser with no latency. Fast-follow after deploy.
- [ ] What-if sliders (deterministic recompute).
- [ ] NOC audit view (duty-by-duty diff + drafted correction).
- [ ] Cited change-log / inbox.
- [ ] Real-time updates (upload → live dashboard push).

## Safety + wiring — `agent/`
- [x] **Strands agent** — genuine, idiomatic Strands (verified vs SDK 1.53.0), NOT a wrapper. Real `@tool` tools with richly-typed TypedDict schemas over the deterministic core, a real Agent + agentic loop (model chooses/chains, no hardcoded pipeline), never-submit (BeforeToolCall hook) + never-assert gates as real guards. Optional auditor+strategist agent-as-tool team (`agent/team.py`); flat orchestrator is the default.
- [x] **Cited-corpus memory (dev mirror)** — `MemoryManager` over `TestMemoryStore` (offline), seeded from `noc.OCCUPATIONS` so a retrieved passage carries its real source URL. NOC audit now re-sources each flagged gap's citation from the retrieved passage (`cited_via="corpus_retrieval"`), a live retrieval end to end. Bright line held: reference TEXT only, never a cutoff number into `crs()`/`reachable_paths()`. `BedrockKnowledgeBaseStore` is the real, config-swappable deploy seam.
- [x] **Session/state storage (dev mirror)** — `FileSessionManager` + profile in `agent.state`, restores a conversation by session id. `S3SessionManager` is the one-line deploy swap. Config flips memory (dev|bedrock_kb) + sessions (file|s3) by env var; defaults fully offline.
- [x] **Draw-cutoff provenance** — `ingest_draws` emits full provenance (round number, per-round page URL, fetch date) and `reachable_paths` echoes it onto each reported draw (`serde.attach_draw_provenance`), so a reported cutoff travels with where the number came from. Moves a citation, not a number; the cutoff still comes only from deterministic ingest.
- [~] **AgentCore** — authentic, clearly-marked `BedrockAgentCoreApp` entrypoint (`agent/runtime.py`); Code Interpreter (math as visible proof surface), Memory, Observability NOT wired yet. Docs-only surfaces (`bedrock_agentcore` clients, `strands_tools.retrieve`) must be API-verified before wiring. **Provisioning is a pre-demo step** (needs live AWS): see `docs/strands-plan.md` "what the user must provision".
- [ ] **Bedrock Guardrails** — PII masking (UCI, passport, DOB) on all inbound/outbound + denied-topic "never assert eligibility."
- [ ] **DynamoDB** profile + snapshot store (or S3/KB per the storage plan).

## Nice-to-haves (after the core is excellent — priority order)
- [ ] Email onboarding + intake (SES → Lambda PDF extract → Guardrails → profile → live update).
- [ ] Nova Sonic voice mode (talk to the agent / ask the dashboard).
- [ ] Browser Live-View last mile (human performs the submit).
- [ ] Multi-channel alerts (SMS / WhatsApp).
- [ ] Scenario saving/sharing for what-if; two specialist sub-agents if the orchestrator prompt bloats.

## Pre-commit gate (do before deep-investing in the lane)
- [ ] Novelty check: confirm no incumbent (Evola, ImmiPilot, Aïa, ImmiTrack, Visto AI) already ships the NOC-audit + reachable-path + eligibility-time-machine combination.
