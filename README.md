# MapleGuard — build

Two features, done correctly: a **CRS engine** that is provably right and shows its math, and a **NOC reference-letter pre-audit**. Everything else is cut until these are solid. Rationale and full spec in `../concept-spec-mapleguard.md` and `../concept-shortlist_v2.md`.

## Run
```bash
cd agents-for-humans/mapleguard
PYTHONPATH=. python3 -m pytest -q
```
Expected today: invariants + regression pass, oracle cases skip (need real numbers), `test_table_provenance` FAILS naming the unverified tables. That failure is the to-do list.

## Layout
```
crs/
  models.py    Profile + LanguageScores (pure data)
  tables.py    every point value, with source + effective-date + verified flag
  engine.py    pure crs(profile) -> Score(total, components, breakdown lines)
  cases/golden.json   oracle cases (your 474, the ImmiPilot 444)
tests/test_crs.py     the 5-tier validation suite
```
Design rule: the engine holds no magic numbers. Rules live in `tables.py` so a policy change is a data edit the provenance test polices.

## Subtasks (MVP = Feature A + Feature B)

### Feature A — CRS engine (correctness is the headline; do this first)
- **A1. Verify the sub-tables. [DONE 2026-08-21]** All 17 tables filled from the official "Points breakdown of ..." tables (read from the live DOM) and marked `verified=True`. Provenance test is green. Also fixed two scaffold bugs found in the process: spouse factors now use the spouse-specific tables, and Canadian-work/education tiers are correct.
- **A2. Nail skill transferability. [DONE 2026-08-21]** Resolved against the official grid: each of the three groups sums its two components then caps at 50, overall caps at 100, and the values are graduated (13/25/50) by education tier and the CLB7-vs-CLB9 threshold. A lone bachelor's sits in the 13/25 tier (the classic over-count trap). Anchored by `test_anchor_*`. This is the most likely ImmiPilot error site.
- **A3. Oracle cases. [TODO — needs your inputs]** Enter your real profile + its official IRCC-tool number as `owner-real-profile-474`. Reconstruct the ImmiPilot 444 profile, get the official number, and binary-search which factor they broke. Both become locked tests.
- **A4. Reachable-path engine.** `reachable_paths(profile, live_cutoffs)` — which category/PNP draws this profile clears now + the ranked shortest feasible point-move. Feeds off the same engine. (This is the useful interpretation layer, not a new subsystem.)
- **A5. (cheap Creativity add) eligibility timeline.** Since CRS is a function of dates, project age-bracket drops, test-expiry, and Canadian-work anniversaries forward and surface the cliffs/windows. Reuses the engine, adds no data source.

### Feature B — NOC reference-letter pre-audit (the moat) — in `noc/`
- **B1. NOC data. [STARTED]** NOC 2021 lead statement + main duties modelled in `data.py`, seeded verbatim from the official ESDC profile with source + version (NOC 21234 done, `verified=True`). Add the codes relevant to the target user the same way. `"May ..."` duties are marked optional.
- **B2. Mandatory-elements check. [DONE]** `mandatory.py` deterministically checks the required elements. Text-detectable ones (period, hours, salary, signatory, contact, title, duties section) return PRESENT/MISSING; letterhead is visual and returns NEEDS_MANUAL_CHECK. Detection is conservative: MISSING only on a confirmed absence.
- **B3. Duty match. [CORE DONE]** `audit.py` holds the deterministic scorer: coverage against required duties, pass/fail at the 80% threshold, every gap cited to the official NOC. Alignment is validated first — evidence not present in the letter is dropped, so coverage cannot be fabricated. **Remaining:** the LLM matcher that produces the alignment (interface `DutyMatcher` defined and injected; tested with a stub).
- **B4. Correction draft. [TODO]** Generate a revised letter matching the lead statement, for the employer to sign. Never asserts eligibility.

### Wiring (after A + B compute correctly)
- **W1. Strands agent** with the engine + audit as tools; single agent, not a swarm.
- **W2. AgentCore:** deploy on Runtime; Code Interpreter for the math, Memory for the profile, Policy for the two gates (never submit / never assert eligibility), Observability for the proof surface.
- **W3. Proof surface + zero-friction seeded demo:** CRS breakdown + reachable-path matrix + NOC audit report + cited change-log, landing on a seeded candidate mid-decision.

## Non-negotiables
- The engine must match IRCC's official tool before any "theirs is wrong, ours is right" claim ships.
- Every point value is stamped with a source + effective date. Arranged-employment stays 0 (removed 2025-03-25), regression-guarded.
- The agent never asserts an eligibility verdict and never submits. Human decides and submits.
