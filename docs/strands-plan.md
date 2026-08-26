# Strands / AgentCore deepening plan

Scope: how MapleGuard goes deep into the Strands ecosystem without weakening the
determinism / compute-and-refuse thesis in `ARCHITECTURE.md`. Every API below was checked
against Strands Agents SDK 1.53.0. What was import-verified in a real venv is marked
**[verified]**; what rests on the docs only (packages not installed here) is marked
**[docs-only]** and must be confirmed against the running SDK before we lean on it.

The rule that governs the whole plan: the model retrieves, routes, and explains. Deterministic
code still owns every number, and every asserted fact still carries a real source. Memory and
retrieval make the *citations* live instead of hardcoded. They never become the thing that
computes a score or decides eligibility.

---

## 1. Memory and storage

### 1a. Bedrock Knowledge Base as the cited corpus (the strongest on-thesis use)

Today the NOC lead statements and duties are hardcoded strings in `noc/data.py` with a
`source` URL and a `verified` flag. That is honest but static. A Knowledge Base turns "every
claim cited" into a live retrieval: the agent pulls the actual IRCC / NOC / draw-history
passage and quotes it, with the KB's own source location as the citation.

APIs (all **[verified]** importable in 1.53.0):

```python
from strands import Agent
from strands.memory import MemoryManager
from strands.vended_memory_stores import BedrockKnowledgeBaseStore

store = BedrockKnowledgeBaseStore(
    name="ircc_corpus",
    description="IRCC rule text, NOC 2021 lead statements and duties, and draw history.",
    config={"knowledge_base_id": "<KB id>"},
)
agent = Agent(memory_manager=MemoryManager(stores=[store]))
```

Retrieved entries carry `_relevance_score` and `_sourceLocation` in metadata (per the
bedrock-knowledge-base doc), which is exactly the citation surface we need. IAM needed:
`bedrock:Retrieve`, `bedrock:GetKnowledgeBase`, and `bedrock:IngestKnowledgeBaseDocuments`
for writes.

What goes in the KB, and what does NOT:
- IN: the reference *text* the agent quotes. NOC lead statements + duties, IRCC rule prose,
  the draw-history narrative. These are things we cite, not things we compute from.
- OUT: the cutoff numbers the engine scores against. Those still come through
  `ingest.rounds` as typed, cited `Draw` records with a hard `needs_manual_check` refusal on
  an unparseable value. A KB is a semantic-search surface and can return an approximate or
  reworded number. We must never feed a retrieved number into `crs()` / `reachable_paths()`.
  The KB cites the rule, the deterministic ingest owns the cutoff. Keep that line bright.

On-thesis payoff: the NOC audit already flags a gap and cites `noc/data.py`. With the KB, the
same gap cites the retrieved official passage, so the proof surface shows a real source the
judge can follow, not our transcription. This is the single most defensible KB use.

Honesty note: the KB needs live Bedrock, so for dev we use the test store (1b), and the
`needs_verification` flag stays until the cited text is confirmed against the source.

### 1b. Dev mirror: TestMemoryStore

**[verified]** `strands.vended_memory_stores.test_memory_store.TestMemoryStore` mirrors the
store interface with no provisioned resources (keyword recall, `persist=False` for pure
in-memory). This is the offline path so retrieval-shaped code is testable with no AWS:

```python
from strands.vended_memory_stores.test_memory_store import TestMemoryStore
store = TestMemoryStore(name="ircc_corpus", persist=False)   # same MemoryManager wiring
```

Same `MemoryManager(stores=[store])` wiring as the KB, so swapping dev to deploy is a
one-line store change. Seed it with a few real NOC passages for the demo.

### 1c. Session and per-user state (profile + conversation persistence)

**[verified]** two attach points on `Agent`:
- `Agent(session_manager=...)` persists conversation + state automatically per session.
  `strands.session.file_session_manager.FileSessionManager(session_id, storage_dir=...)` for
  dev, `strands.session.s3_session_manager.S3SessionManager(session_id, bucket, prefix=...)`
  for deploy. Both restore existing state on init.
- `Agent(state=...)` / `agent.state` holds the structured per-user profile (the dict our
  tools already consume). This is where the deterministic `Profile` lives between turns.

Plan: `FileSessionManager` in dev, `S3SessionManager` in deploy, and the candidate profile
carried in `agent.state`. The profile is data the tools read, never a source the model
computes from.

---

## 2. Pattern for the one genuine seam (research agent -> advisor)

The seam: a background **research / ingestion agent** (Feature 1: keep IRCC rules, draws, and
NOC text current and cited, writing into the KB) feeding the interactive **advisor** (the
orchestrator already built: position, reachable paths, NOC audit). This is the one place two
real agents earn their keep. It is NOT a swarm and NOT agent-for-agent's-sake.

Three candidate Strands constructs (all real in 1.53.0):

| Construct | Fit for this seam | Verdict |
|---|---|---|
| **agents-as-tools** (`Agent.as_tool()`) **[verified]** | Advisor calls research on demand, in one process, synchronously. We already use this for the auditor/strategist split. | Good for on-demand, wrong for background. |
| **graph** (`strands.multiagent.GraphBuilder`) **[verified]** | A DAG of agent nodes with conditional edges. Research and advisor are not a request-time DAG. Research runs on a schedule and writes to the KB; the advisor reads the KB later. There is no live edge to traverse per request. | Over-fit. A graph models a branching in-request multi-agent flow we do not have. |
| **scheduled worker + shared KB** (no multi-agent primitive) | Research runs as a background job (`ingest.rounds` + KB writes) on a cron. The advisor is a separate agent that retrieves from the same KB. The "edge" is the KB, not a call. | **Recommended.** |

Recommendation: **the seam is a shared-KB boundary, not a graph edge.** The research agent is
a scheduled worker that ingests and writes cited passages to the KB (`store.add(...)`). The
advisor retrieves from the KB at question time. This matches `ARCHITECTURE.md` ("the
policy-diff and PNP radar run as scheduled background workers, not conversational agents") and
keeps the two agents decoupled through data, which is more robust than a live handoff.

If we want a small conversational multi-agent showcase, we already have the honest one: the
auditor + strategist agents-as-tools split (`agent/team.py`). Reserve `GraphBuilder` for a
future request-time branch that genuinely needs conditional routing between LLM agents. We do
not have one yet, so we should not add one.

---

## 3. AgentCore wiring (now that AWS is available)

| Primitive | What it does here | Attaches where | Needs live AWS? | Offline path |
|---|---|---|---|---|
| **Runtime** (`BedrockAgentCoreApp`) **[docs-only]** | Hosts the advisor, handles container/scaling/tracing. Already have the guarded entrypoint in `agent/runtime.py`. | wraps `handle()` | yes (deploy) | `handle(payload, model=fake)` runs anywhere |
| **Code Interpreter** **[docs-only]** | Run the deterministic `crs` / `paths` / `pnp` math inside a visible sandbox, so the number is computed in a reproducible, inspectable environment. | inside the tool wrappers (the tool ships the pure-Python call into the sandbox and returns the typed result) | yes | tool computes in-process locally, identical result |
| **AgentCore Memory** **[docs-only]** | Longitudinal per-user profile across sessions (the living profile). | alongside / instead of the session manager | yes | `TestMemoryStore` + `FileSessionManager` |
| **Observability** **[docs-only]** | The proof surface: traces of which tools ran, what they returned, which citations. | agent tracing config | partial | Strands emits local traces/metrics without AWS |

Code Interpreter, the framing that matters: our core is already trusted library code, so the
sandbox is **not** a safety mechanism (we are not running model-generated code). Its value is
the **proof surface** point: "this CRS was computed in a visible, reproducible sandbox from
the published grid, not generated by the model." That is on-thesis and worth doing, but it is
presentation of determinism, not a new guarantee. We keep the in-process computation as the
source of truth and the sandbox as the demonstrable mirror, and we mark it honestly.

What stays testable offline (no regression): every tool, gate, serde path, the flat
orchestrator loop, the agent-as-tool team loop, and `handle()` all run with a fake model and
no AWS today. The AgentCore primitives are additive wrappers over that same tested core.

Cannot verify here (packages not installed in this env): the exact `bedrock_agentcore` Code
Interpreter / Memory client surface and `strands_tools.retrieve`. Confirm these against the
running SDK before wiring. Everything in sections 1 and 2 (memory stores, session managers,
`Agent` params, `GraphBuilder`) was import-verified in a real 1.53.0 venv.

---

## Build order (proposed, pending confirmation)

1. Session + state: `FileSessionManager` + `agent.state` profile, offline. Cheap, no AWS.
2. KB retrieval behind the `MemoryManager` interface, `TestMemoryStore` in dev; seed real NOC
   passages; wire the NOC audit to cite the retrieved passage. Then point at a real KB.
3. Research worker: `ingest.rounds` + `store.add(...)` on a schedule, writing cited passages.
4. AgentCore: Code Interpreter mirror for the math (proof surface), then Memory, then
   Observability, each additive over the tested core.

Not started, not merged. Awaiting confirmation on this plan.
