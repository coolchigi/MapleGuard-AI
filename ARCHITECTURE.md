# MapleGuard — read this first (shared context for every session)

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
Split by determinism: instant local recompute in the browser for the proof surface; the server only does what the browser can't (live data, model, state).

## Rules for your work
- Match the codebase: typed dataclasses, pure functions where possible, docstrings that state the trust posture. Tests never hit the network (inject fakes); keep `PYTHONPATH=. python3 -m pytest -q` green.
- Cite every value. Mark unverified data `verified=False` / `needs_manual_check` rather than encoding a guess as fact.
- Writing (docs, comments, blogs): no em dashes, no semicolons in prose. Specific and honest. No fabricated numbers. No hype buzzwords.
- Public repo (github.com/coolchigi/MapleGuard-AI): no personal data, no internal competitor strategy.
- Commit on a branch with the Co-Authored-By trailer; don't merge (the orchestrator session merges).

## Status
Done: deterministic core end to end (crs → timeline → sirs_bc → reachable_paths), NOC feature (matcher + corrector + BC Tech NOCs + verification guard), draw ingestion. Building: Strands agent, README + 3 technical blogs. Not started: server API, web app, alerting, AgentCore/Guardrails/DynamoDB deploy. See `TODO.md` for the live tracker.
