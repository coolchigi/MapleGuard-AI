# MapleGuard

An AI agent for Canadian immigration that **computes your position deterministically and refuses to guess.**

Canadian permanent-residence scoring is a moving, date-sensitive system. Draw cutoffs shift every round, points values change on short notice (IRCC zeroed all arranged-employment points on 2025-03-25), language tests expire and take your pool spot with them, and reference letters get refused when they do not match the published NOC text. Most tools in this space are "AI copilots trained on immigration law" that answer legal questions in prose, which is exactly the posture that produces confident, wrong, unaccountable answers about someone's life.

MapleGuard takes the opposite posture.

## The thesis: determinism below the model

Every number MapleGuard reports is produced by deterministic Python over the published government grids, not by a language model. The LLM never computes a CRS score, never decides pass or fail, and never asserts eligibility. It does one narrow job (reading a reference letter and proposing which sentence covers which duty), and even that output is validated against the source text before it counts.

We call this **compute-and-refuse**:

- **Compute.** CRS, PNP scores, trajectories, and duty coverage are pure functions. The CRS engine is validated against IRCC's official "Check your score" tool.
- **Cite.** Every point value carries a source and an effective date, guarded by a provenance test. Every flagged NOC gap cites the official duty text. Reference text that has not been line-checked is stamped `needs_verification` so no result can be mistaken for a verified one.
- **Refuse.** The agent computes facts and shows its work. It does not tell you whether you are eligible, and it does not file anything. That call is yours, and getting it wrong is your life. This is not left to the prompt. Two deterministic gates sit below the model in `agent/gates.py`: a never-submit gate that cancels any tool call that looks like filing an application, and a never-assert-eligibility gate that screens the model's own text for an eligibility verdict. A prompt is a request, so the gates make it a guarantee.

## Features

**Position engine (`crs/`)**: a full deterministic CRS calculator. Core human capital, skill transferability (the graduated 13/25/50 tiers where cheaper calculators over-count a lone bachelor's degree), and additional points, for single and spouse-accompanied profiles. `crs(profile, as_of)` is a pure function of the profile and the date.

**Time machine (`crs/timeline.py`)**: CRS is a deterministic function of dates, so your future score is computable. `trajectory()` plots your score across a date range and `deadlines()` returns the dated cliffs that move it: age-bracket drops on your birthday, and language-test expiry (results are valid two years, and on lapse your language points and their skill-transfer contribution both drop to zero, which invalidates a profile in the pool). It surfaces the cliff and the window to act before you hit it.

**Reachable paths (`paths/reach.py`)**: the interpretation layer over the raw number. Given the live draw cutoffs, it classifies each draw as reachable now, within reach via a single move, blocked, or eligibility-unknown, and for the ones you do not clear it ranks the shortest feasible move (raise language to CLB 9/10, add French at NCLC 7, one more year of Canadian work, a +600 nomination), each recomputed through the CRS engine. Where eligibility depends on an occupation list it does not yet have, it says so rather than guessing.

**BC PNP scorer (`pnp/bc.py`)**: the BC Skills Immigration SIRS grid (200 points), with the +600-CRS nomination effect and the job-offer requirement surfaced honestly, including the Tech occupations that are exempt from the offer requirement for registration.

**NOC reference-letter pre-audit (`noc/`)**: the officer-grade document work. It checks the mandatory elements of a reference letter, scores its duties against the published NOC 2021 lead statement and main duties at the 80% coverage bar, cites every gap to the official text, and drafts a corrected letter for the employer to sign. The draft never invents work: it covers a duty only from the original letter or caller-supplied facts, and otherwise leaves an explicit `[employer to confirm: ...]` placeholder. The draft is re-auditable, so you can run the audit again and watch supported gaps close while unsupported ones stay cited.

**Orchestration layer (`agent/`)**: a single Strands agent that wraps the deterministic core as typed tools. Each tool deserializes the model's arguments, calls a pure function, and returns the number and its citation unchanged, so the model reads results but never computes them. The two policy gates run below it, an optional auditor/strategist specialist split is available via `agent/team.py` for the rare case where separating the paperwork and position domains simplifies, and NOC gap citations can be re-sourced from a retrieval corpus (a local store in dev, a Bedrock Knowledge Base in deploy) without ever feeding a number into the engine. The Strands and AWS dependencies are behind seams, so the whole stack imports, runs, and tests offline with injected fakes.

## Not just an automation

Anyone can wire a scraper to a diff and an email. The alert is a commodity, and that is why monitoring sits at the edge of this product, not the center.

What a scraper cannot do is tell you what a change means for *you*. "The page changed" is a diff. "This change moves you from 474 to 469, drops you below the last three category cutoffs, and here is the shortest move that reopens one" requires a correct, oracle-matched model of your position scored against the published grids. The per-profile correlation, the forward-looking cliffs, and the drafted correction letter are all downstream of that model. The deterministic model of your position is the moat. The alert is just how it reaches you.

## Architecture at a glance

```
crs/          deterministic CRS engine (the heart)
  models.py     Profile + LanguageScores (pure data)
  tables.py     every point value, stamped source + effective-date + verified flag
  engine.py     crs(profile, as_of) -> Score(total, subtotals, line-item breakdown)
  timeline.py   trajectory() + deadlines(), the time machine
  cases/        golden oracle vs IRCC's official tool
pnp/bc.py     BC SIRS scorer (province module, pluggable)
paths/reach.py  reachable-path classification + ranked shortest moves
noc/          reference-letter pre-audit
  data.py       NOC 2021 lead statements + duties, seeded verbatim with source + version
  mandatory.py  deterministic mandatory-element check (conservative)
  audit.py      deterministic duty-coverage scorer + NEEDS_VERIFICATION guard
  matcher.py    LLM duty matcher (proposes alignment, output validated, never trusted)
  draft.py      correction-draft generator (never asserts eligibility, never invents work)
ingest/       IRCC "rounds of invitations" feed parser (deterministic, fixture-tested)
agent/        Strands orchestrator over the core (the model reads tools, never computes)
  tools.py      the deterministic core wrapped as typed, cited tools
  gates.py      never-submit + never-assert-eligibility, deterministic, below the model
  orchestrator.py  the single agent, its system prompt, and gate wiring
  team.py       optional auditor/strategist agent-as-tool split (same tools, same gates)
  citations.py  re-source NOC gap citations from a retrieval corpus (text only, never a number)
  config.py     the seam that swaps offline-dev backends for Bedrock / S3 at deploy
```

The layering is deliberate. The model sits *above* the deterministic core and can only feed it validated, cited claims. It can never reach down and change a number, and the gates below it block the two actions it must never take even if the prompt fails.

## Run the tests

```bash
cd agents-for-humans/mapleguard
PYTHONPATH=. python3 -m pytest -q
```

Current: **100 passed, 16 skipped, 1 xfailed**. The skips are integration tests that need something the offline suite deliberately does without: the Strands SDK installed, a Claude API key, live AWS Bedrock, or the real canada.ca feed. The xfail marks the BC SIRS point bands as not yet line-verified. Everything else, including the whole agent layer, runs offline against injected fakes. The CRS engine passes its golden-oracle case against IRCC's official tool, and the provenance test keeps every published point value stamped with a source.

## Honest status

Done and tested:

- The deterministic core end to end: `crs` → `trajectory`/`deadlines` → `sirs_bc` → `reachable_paths`.
- The NOC pre-audit end to end: mandatory-element check, deterministic duty scorer, LLM duty matcher with output validation, correction-draft generator, and the `NEEDS_VERIFICATION` guard.
- The IRCC "rounds of invitations" feed parser, tested against a saved fixture.
- The `agent/` orchestration layer: the core wrapped as typed tools, the two deterministic policy gates, the single orchestrator and the optional specialist split, corpus-sourced NOC citations, and the offline-dev / AWS config seam. All of it tested offline against injected fakes.

Outstanding:

- **Live ingestion.** The rounds parser exists and is a tool, but the scheduled research loop that keeps rules, draws, NOC text, and PNP windows current is not built. The parser still needs its document fetched and passed in.
- **Alerting engine.** The `deadlines()`-driven staleness alerts, the policy-diff worker, and the outbound email are not built.
- **Verification debt.** The BC SIRS point bands and the first three BC Tech NOC texts are seeded but not yet line-checked against the official source (structure and flags are safe to use, exact sub-scores are not, and the guards say so).
- **Deploy.** The agent runs offline against fakes and is wired to swap in Bedrock and S3 through the config seam, but nothing has been deployed to AgentCore, and Bedrock Guardrails and the DynamoDB profile store are not stood up.
- **Frontend.** The dashboard is designed but not built.

The core is real and correct. The product around it is in progress, and this README will not claim otherwise.

## What MapleGuard will never do

It will not tell you that you are eligible, and it will not submit a government application. It computes, it cites, and it stops at the button. You decide.
