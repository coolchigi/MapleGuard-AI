# Strands below the model: orchestrating a compute-and-refuse agent

MapleGuard is a Strands agent, and the interesting engineering is not that a model calls some functions. It is what Strands lets us build underneath the model. The whole product rests on one rule: the model orchestrates, retrieves, and explains, and it never computes a score or asserts eligibility. Deterministic code does. This post is about the Strands machinery that turns that rule from a line in a prompt into something enforced in code.

Everything here was written against Strands Agents SDK 1.53.0. Where a construct was import-verified in a real SDK environment it is called out. Where a seam is wired but not yet confirmed against a live deploy, that is called out too, because honesty about status is part of the same trust posture.

## The deterministic core as typed tools

The core is a set of pure functions: `crs`, `crs_trajectory`, `crs_deadlines`, `sirs_bc`, `reachable_paths`, the reference-letter audit and draft. Each is exposed to the model as a Strands `@tool`. A tool is a thin wrapper: it deserializes the arguments, calls the pure function, and serializes the typed result back with every number and every citation intact.

```python
@tool
def compute_crs(profile: ProfileInput, as_of: Optional[str] = None) -> dict:
    """Compute a candidate's Comprehensive Ranking System (CRS) score from the published
    IRCC grid. Returns the total, the four block subtotals, and a per-factor breakdown.
    ...
    """
    p = serde.profile_from_dict(profile)
    return serde.score_to_dict(crs(p, serde._parse_date(as_of)))
```

The `@tool` import is behind a fallback, so the module imports and the tests run with or without Strands installed. Without the SDK, `@tool` is an identity decorator and each wrapper is a plain callable. With it, each is a registerable `DecoratedFunctionTool` that returns the same dict. The wrapper is the single source of tool behavior either way.

The argument types are not `dict`. They are `TypedDict` schemas, chosen deliberately over Pydantic. Strands generates the same rich nested JSON schema from a `TypedDict` (verified against 1.53.0), but at runtime the argument still arrives as a plain dict, so there is one validation path (`serde`), not two. Literal-typed fields become enums in the schema the model sees:

```python
class ProfileInput(TypedDict, total=False):
    education: Required[EducationLevel]           # a Literal -> becomes an enum in the ToolSpec
    first_language: Required[LanguageScoresInput]
    age: int
    date_of_birth: str                            # ISO 'YYYY-MM-DD'
    first_language_test_date: str                 # results valid 2 years
    canadian_work_years: int
    has_provincial_nomination: bool
    ...
```

Because `EducationLevel` and `MaritalStatus` are `Literal` types, the model is handed the exact allowed values in the tool schema rather than guessing a free string. The type-level `Required` shapes the schema, and the authoritative runtime validation stays in `serde`, which raises on a malformed profile rather than silently defaulting.

This is the compute-and-refuse posture made mechanical. The model picks a tool and reads its result. It never does the arithmetic, because the arithmetic is not something it is asked to produce.

## Two policy gates, below the model

A system prompt can tell the model to never submit an application and never assert eligibility. A prompt is a request, not a guarantee. Strands lets us make it a guarantee, in two different places, because the two rules guard two different things.

**never-submit guards tool calls.** It is a Strands hook on `BeforeToolCallEvent`. Before any tool runs, a deterministic check reads the selected tool's name and cancels the call if it looks like filing a government application.

```python
class MapleGuardPolicyGate(HookProvider):
    def register_hooks(self, registry: "HookRegistry", **_kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call)

    def _before_tool_call(self, event: "BeforeToolCallEvent") -> None:
        name = ""
        if event.selected_tool is not None:
            name = getattr(event.selected_tool, "tool_name", "") or ""
        if not name:
            name = (event.tool_use or {}).get("name", "")
        decision = never_submit(name)
        if not decision.allowed:
            event.cancel_tool = f"blocked by policy ({decision.gate}): {decision.reason}"
```

The decision itself lives in `gates.py` as a pure function, so it is testable with no SDK and no network. There is also defence in depth at build time: the orchestrator refuses to even construct if a submission-shaped tool is in the list.

```python
def assert_no_forbidden_tools(tools: Iterable[Any]) -> None:
    bad = forbidden_tools(tool_name(t) for t in tools)
    if bad:
        raise ValueError(
            f"refusing to register submission tools {bad}: MapleGuard never submits "
            "applications (the human does). Remove them before building the orchestrator."
        )
```

**never-assert-eligibility guards text, not tool calls.** An eligibility verdict is something the model says, so it is screened over the final response rather than at a tool boundary. The runtime handler runs the model, pulls the text out of the Strands `AgentResult`, and passes it through the gate before returning it.

```python
def handle(payload: dict, agent: Any = None, model: Any = None) -> dict:
    prompt = payload.get("prompt", "")
    if agent is None:
        agent = build_orchestrator(model=model)

    result = agent(prompt)
    text = _result_text(result)

    decision = screen_response(text)          # never_assert_eligibility over the answer
    if not decision.allowed:
        return {"blocked": True, "gate": decision.gate, "reason": decision.reason}
    return {"result": text}
```

The gate is deliberately careful about what it refuses. The engine legitimately reports cited comparisons like "your CRS is 470" or "you clear this cutoff of 468", because those are facts against published numbers. What is refused is a conclusion about the person: eligible, qualifies, guaranteed an invitation or a nomination. That distinction is the whole product, so it lives in a documented regex with a carve-out, not a blanket filter.

Using Strands hooks as a deterministic policy layer under an otherwise free-form model is the non-obvious part. The model can be as conversational as it likes on top. It cannot cross the two lines, because the lines are enforced by code the model does not sit above.

## Small, deliberate multi-agent

The default topology is one orchestrator over a flat tool list, because the flow is knowable and a single agent is easier to trust and debug than emergent handoff. But there is one honest split available, built on the SDK's native `Agent.as_tool()`: a document auditor that owns the reference-letter tools, and a strategist that owns the position engine.

```python
POSITION_TOOLS = [compute_crs, crs_trajectory, crs_deadlines, sirs_bc, reachable_paths, ingest_draws]
NOC_TOOLS = [audit_reference_letter, draft_corrected_letter]
MAPLEGUARD_TOOLS = POSITION_TOOLS + NOC_TOOLS
```

The two tool subsets exist precisely so each specialist can carry its own kit without changing any tool's behavior. Every specialist runs the same deterministic tools and the same two gates as the flat orchestrator, so the split adds a separation of concerns without adding any place for the model to invent a number.

The choice of construct was made on purpose. `Agent.as_tool()` fits an on-demand, in-process call. A `GraphBuilder` DAG would over-fit, because the one real seam in the system (a scheduled research worker that keeps rules and draws current, feeding the interactive advisor) is not a request-time branch. That seam is a shared-corpus boundary, not a live edge, so it is modelled as a background job writing to the same store the advisor reads, not as a multi-agent graph. Reaching for the heaviest multi-agent primitive available would have been the wrong call, and saying so is part of using the SDK well.

## Live citations through MemoryManager

The trust story is "every claim carries a real source." The NOC lead statements and duties start as cited strings in `noc/data.py`, which is honest but static. Strands memory upgrades a citation from a transcription to a live retrieval: for each flagged gap, the agent looks the duty up in a corpus and attaches the source of the passage the corpus actually returned.

One `MemoryManager` interface sits over two backends. Dev uses `TestMemoryStore`, seeded from the real NOC passages, with no AWS. Deploy uses `BedrockKnowledgeBaseStore` over a provisioned Knowledge Base.

```python
def build_test_memory(persist=False, seed=True, name=CORPUS_NAME):
    from strands.memory import MemoryManager
    from strands.vended_memory_stores.test_memory_store import TestMemoryStore
    store = TestMemoryStore(name=name, persist=persist, writable=True)
    if seed:
        seed_store(store, noc_seed_passages())
    return MemoryManager(stores=[store]), store
```

Both backends and the `MemoryManager` wiring were import-verified against 1.53.0, so swapping dev for deploy is a one-call change. Retrieved entries carry the passage source (and `_relevanceScore` and `_sourceLocation` from a real KB), which is exactly the citation surface the audit needs.

There is a bright line running through this. Only reference text goes in the corpus: NOC prose, rule prose. The cutoff numbers the engine scores against never come from semantic search. Those stay in the deterministic ingest path, which refuses an unparseable value rather than guessing. A Knowledge Base can return an approximate or reworded number, so the engine must never read one from it. Retrieval re-sources what the deterministic scorer already flagged, and it stamps how each citation was resolved:

```python
if found and found.get("source"):
    gap["cited_via"] = "corpus_retrieval"
    gap["source"] = found["source"]
    gap["retrieved_text"] = found["retrieved_text"]
else:
    gap["cited_via"] = "seed"
```

Memory cites the rule. Deterministic ingest owns the cutoff. That line is what keeps a retrieval feature on the right side of the thesis.

## Session, state, and the deploy seam

Per-user persistence uses the SDK's own attach points. A session manager persists conversation and state per session (`FileSessionManager` in dev, `S3SessionManager` in deploy), and `agent.state` holds the structured candidate profile the tools consume between turns. The profile is data the tools read, never a source the model computes from.

The deploy target is Amazon Bedrock AgentCore Runtime, which hosts the agent without hand-rolling the container, scaling, and tracing. The entrypoint is kept thin, and the pure request handler is separated from the hosting wrapper so it runs anywhere a model is injected:

```python
def build_app(model: Any = None):
    from bedrock_agentcore.runtime import BedrockAgentCoreApp
    app = BedrockAgentCoreApp()
    agent = build_orchestrator(model=model)

    @app.entrypoint
    def invoke(payload: dict) -> dict:
        return handle(payload, agent=agent)
    ...
```

A single `Deployment` config record decides which memory backend and which session store the agent uses, flipped by environment variables, so moving from offline dev to Bedrock and S3 touches configuration, not orchestration code.

Honest status: the memory stores, session managers, `Agent` parameters, `Agent.as_tool()`, and the hooks were import-verified against 1.53.0. The AgentCore Runtime, Code Interpreter, Memory, and Observability primitives are wired as seams and structured to attach without touching the orchestration, but they rest on the docs and have not yet been confirmed against a live deploy. Nothing has been deployed. The blog will not pretend otherwise.

## Everything runs offline

A discipline runs through the whole layer: it must import, run, and test with no SDK, no key, and no AWS. Strands is imported lazily inside the builders. The model, the tools, the matcher, the corrector, the memory store, and the session manager are all injectable, so the offline tests exercise the real deterministic scoring, the real gates, the real serde paths, the flat orchestrator loop, the agents-as-tools loop, and the runtime `handle()` against fakes. The integration tests that need the real SDK, a live model, or AWS are the only ones that skip.

## Why this is not a wrapper

A wrapper hands the model a task and trusts the prose it returns. MapleGuard uses Strands to do the opposite. The model is given typed tools and told to route to them, a pre-tool-call hook that cancels a forbidden action, a response screen that refuses an eligibility verdict, a memory layer that lets it cite a retrieved source without ever pulling a number from it, and a specialist split that keeps the same guarantees on both sides. The model routes, retrieves, and explains. The SDK is used, deliberately and at each layer, to guarantee that it never computes the number and never crosses the two lines. That guarantee is the product, and Strands is how it is enforced.
