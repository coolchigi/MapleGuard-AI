# MapleGuard: read this first (shared context for every session)

You are building **one piece of one system**, not a standalone script. Know how your piece fits before you start.

## What MapleGuard is
An AI agent for Canadian immigration that **computes** a person's position deterministically and **refuses to guess**. It tells you where you stand, the cliffs ahead, and audits your paperwork the way an officer will. It never asserts eligibility and never submits a government application.

## The one rule that governs everything: determinism below the model
- Deterministic code computes every number from the published government grids. The language model **never** computes a CRS/SIRS number, **never** asserts eligibility, **never** submits.
- Every value is **cited** to its source (URL + date). If something can't be verified, flag it, never guess.
- The model only orchestrates, explains, and drafts. This "compute-and-refuse" posture is the whole product's trust story and the thing that makes us "not just an automation."

## The system shape
```
Deterministic core (pure Python, no I/O)         <- the source of truth
  crs/     CRS engine + timeline (the "time machine")
  pnp/     BC PNP SIRS scorer
  paths/   reachable_paths — turns scores into "what clears / shortest move"
  noc/     reference-letter pre-audit (deterministic scorer + model matcher + correction draft)
  ingest/  cited draw/rule ingestion (feeds paths)
        |
Agent layer (Strands orchestrator on AgentCore)  <- calls the core as TOOLS, never does the math
        |
server/  API over the tools (live data, model calls, persistence, alerting)
web/     Next.js dashboard = the proof surface; runs the deterministic math client-side
         (Pyodide) so what-if sliders + the time-machine scrubber are instant
```
Split by determinism: instant local recompute in the browser for the proof surface, and the server only does what the browser can't (live data, model, state).

## Rules for your work
- Match the codebase: typed dataclasses, pure functions where possible, docstrings that state the trust posture. Tests never hit the network (inject fakes). Keep `cd server && PYTHONPATH=. python3 -m pytest -q` green. All Python lives under `server/`, and `web/` is the Next.js app. Setup + deploy: `docs/standup-guide.md`.
- Cite every value. Mark unverified data `verified=False` / `needs_manual_check` rather than encoding a guess as fact.
- Writing (docs, comments, blogs): no em dashes, no semicolons in prose. Specific and honest. No fabricated numbers. No hype buzzwords.
- Public repo (github.com/coolchigi/MapleGuard-AI): no personal data, no internal competitor strategy.
- Commit on a branch with the Co-Authored-By trailer, and never touch `main` (protected: branch + PR). Report {branch, HEAD sha, tests, decisions}.

## Design: eligibility / pathways service

The core promise is telling a person what they qualify for BEFORE they have to dig for it (the
real case: a CRS 474 candidate who never knew French-category draws sit far lower, or that they
were in-category for a stream). Today the codebase can answer this but never surfaces it:
`ingest.categories` already holds all 10 category rules with cited NOC lists and the French NCLC-7
rule, and `category_eligibility()` returns a deterministic, cited verdict per category. `reachable_paths`
uses it, but only reactively, for a category that happens to have a draw in the current feed.

**The service** (`paths/pathways.py`, pure, no I/O): given a profile, produce a cited **pathways map**
across every Express Entry pathway (general EE, the 10 category-based selections, BC PNP), decoupled
from whether a draw is running now. Per pathway:
- The narrow official verdict from `category_eligibility` (in-category / meets-NCLC-7 / not / cannot
  decide when input is missing), carrying its `source_url`, `source_date`, and the
  `additional_requirements` caveat. "In-category" is never "eligible for PR" (IRCC decides that).
- Current standing vs the latest cited draw for that pathway (from the rounds feed): score, gap, clears.
- If they do not clear: the shortest closing move(s), reusing the `paths` MOVES catalog (no new estimation).

**One relevance engine, no hardcoding.** A person's relevant pathways are exactly the ones this service
says they are in or one move from. That single fact powers three consumers, so relevance is computed
from cited rules, never from a hand-written synonym/alias table:
1. User surface: "here is everything you qualify for and how far you are" (API `/pathways` + an agent tool).
2. Monitor relevance: a category draw or IRCC change matters to a profile when the service says they are
   in that category (replaces any reachability-only or watched-list heuristic).
3. Consultant view (B2B): the same map per client across a roster.

**The KB sits beside this, never in front of it.** The category NOC lists, CRS grids, and SIRS bands are
structured, verified, and determinism-critical: they stay in code (the trust core). The KB (Bedrock
Knowledge Base on S3 Vectors, never OpenSearch on the budget) covers what code should NOT be the source
of truth for: (a) the NOC corpus at scale beyond hand-picked codes (semantic retrieval, flagged
retrieved-not-exact), (b) grounding the agent's free-text explanations against cited IRCC content (so the
prose is checkable, while the numbers stay deterministic), (c) policy-update text for "what changed and
what it means for you". Determinism below the model holds: the KB grounds explanations, it never decides
a score or a verdict.

## Status
Live: deterministic core (crs → timeline → sirs_bc → reachable_paths), NOC feature + source-verified NOC
2021 ingestion, draw ingestion, Strands agent on AgentCore (py3.13), API Lambda + Function URL, autonomous
monitor, PII letter-scrub guardrail, CI on py3.11+3.13. Building: eligibility/pathways service + KB. See
`TODO.md` for the live tracker.
