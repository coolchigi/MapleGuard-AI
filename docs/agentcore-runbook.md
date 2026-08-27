# AgentCore provisioning runbook

How to take the offline dev stack live on AWS. The dev mirror runs with none of this:
`agent/config.Deployment` defaults to a seeded `TestMemoryStore` + `FileSessionManager`, and
the Code Interpreter proof surface falls back to a local subprocess. Each step here flips one
seam to a real AWS resource by setting env vars. Do them in order; each is independent enough
to demo on its own.

Verification status of the wiring these steps activate (checked in a real venv with
`strands-agents==1.54.0`, `bedrock-agentcore==1.22.0`, `boto3==1.43.82`):

- **Import-verified** (the client surface exists and is called with the right shape):
  `BedrockAgentCoreApp` (runtime), `CodeInterpreter.start/execute_code/stop` +
  `code_session` (Code Interpreter), `AgentCoreMemorySessionManager` + `AgentCoreMemoryConfig`
  + `RetrievalConfig` (Memory), `StrandsTelemetry.setup_console_exporter/setup_otlp_exporter`
  (observability), `BedrockKnowledgeBaseStore`, `FileSessionManager`/`S3SessionManager`.
- **Docs-derived, not exercised offline** (needs a live resource to confirm): the
  `executeCode` result-stream shape parsed in `agent/sandbox.py::AgentCoreCodeSandbox._parse`
  (modelled on the SDK's own `download_file` stream reader), and the source-upload step. Run
  step 4's smoke test against a real Code Interpreter to confirm the parse.

Prereqs: an AWS account with Bedrock access, the AWS CLI configured, and a region that offers
AgentCore (e.g. `us-east-1`, `us-west-2`). Set `export AWS_REGION=us-east-1` first.

---

## 1. Bedrock model access

Enable the model the orchestrator runs on, in your region, in the Bedrock console
(Model access -> request the target model). Then pick a concrete model when you build the
orchestrator, instead of the deploy-time default:

```python
from strands.models import BedrockModel
from agent import build_orchestrator
agent = build_orchestrator(model=BedrockModel(model_id="<enabled-model-id>"))
```

No env var. This is the only step required before anything else works live.

---

## 2. Bedrock Knowledge Base — the cited corpus (memory backend `bedrock_kb`)

Turns the seeded `TestMemoryStore` into a live retrieval over IRCC / NOC reference text (the
passages the agent quotes and cites; never the cutoff numbers the engine scores against — see
the bright line in `agent/memory.py`).

1. Create an S3 bucket for the source documents and upload the NOC passages. The exact
   passages the dev corpus seeds are produced by `agent.noc_seed_passages()`:

   ```bash
   aws s3 mb s3://mapleguard-corpus-<suffix>
   # write agent.noc_seed_passages() to text/JSON files, then:
   aws s3 cp ./corpus/ s3://mapleguard-corpus-<suffix>/ --recursive
   ```

2. Create the Knowledge Base with a vector store behind it (OpenSearch Serverless is the
   default managed option; a CUSTOM data source also works for direct writes). The console
   flow (Bedrock -> Knowledge Bases -> Create) provisions the vector store, embeddings model,
   and data source in one wizard. Note the **Knowledge Base id** it returns.

3. Sync the data source so the documents are ingested, then point MapleGuard at it:

   ```bash
   export MAPLEGUARD_MEMORY_BACKEND=bedrock_kb
   export MAPLEGUARD_KB_ID=<knowledge base id>
   export MAPLEGUARD_KB_REGION=$AWS_REGION
   ```

IAM for the runtime role: `bedrock:Retrieve`, `bedrock:GetKnowledgeBase`, and
`bedrock:IngestKnowledgeBaseDocuments` (writes only, if the research worker writes passages).

---

## 3. Session persistence

Pick ONE backend. Both persist the conversation + `agent.state` profile across instances.

### 3a. S3 sessions (session backend `s3`) — simplest

```bash
aws s3 mb s3://mapleguard-sessions-<suffix>
export MAPLEGUARD_SESSION_BACKEND=s3
export MAPLEGUARD_SESSION_BUCKET=mapleguard-sessions-<suffix>
export MAPLEGUARD_SESSION_PREFIX=advisor        # optional
```

IAM: `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` on that bucket/prefix.

### 3b. AgentCore Memory (session backend `agentcore`) — the longitudinal per-user profile

The stronger seam: the candidate profile and history follow the user across sessions, keyed by
`actor_id`. Create a Memory resource once, then point MapleGuard at its id.

Create it programmatically (control plane, verified client):

```python
from bedrock_agentcore.memory.client import MemoryClient
mc = MemoryClient(region_name="us-east-1")
mem = mc.create_or_get_memory(name="mapleguard_profiles",
                              description="Longitudinal per-user MapleGuard profile + history")
print(mem["id"])   # -> mgd-mem-... (min length 12)
```

Then:

```bash
export MAPLEGUARD_SESSION_BACKEND=agentcore
export MAPLEGUARD_MEMORY_ID=<memory id from above>
export MAPLEGUARD_MEMORY_REGION=$AWS_REGION
export MAPLEGUARD_ACTOR_ID=<per-user id>          # defaults to the session id
```

IAM: `bedrock-agentcore:CreateEvent`, `bedrock-agentcore:ListEvents`,
`bedrock-agentcore:RetrieveMemoryRecords`, `bedrock-agentcore:GetMemory` on the memory
resource (grant the control-plane `CreateMemory` only to whoever runs the one-time create).

Bright line: the profile Memory carries is data the tools read, never a source the model
computes a score from.

---

## 4. Code Interpreter — the reproducible proof surface

Runs the deterministic CRS math inside a visible AgentCore sandbox, so the demo shows the
number was computed (not model-generated). This is presentation of determinism, not a safety
layer — our engine is trusted library code.

Provision a Code Interpreter (needs an execution role the sandbox assumes):

```python
from bedrock_agentcore.tools.code_interpreter_client import CodeInterpreter
ci = CodeInterpreter(region="us-east-1")
ci.create_code_interpreter(
    name="mapleguard_crs",
    execution_role_arn="arn:aws:iam::<acct>:role/<code-interpreter-exec-role>",
    network_configuration={"networkMode": "SANDBOX"},   # no egress needed
)
```

Or use the built-in `aws.codeinterpreter.v1` interpreter with no create step — `.start()`
defaults to it. Then run the proof surface against the live sandbox:

```python
from agent.sandbox import build_agentcore_sandbox, run_crs_in_sandbox
sandbox = build_agentcore_sandbox(region="us-east-1")   # starts a session, uploads crs/ + agent/serde.py
proof = run_crs_in_sandbox(profile_dict, as_of="2026-08-25", sandbox=sandbox)
assert proof.matches            # sandbox total == in-process source of truth
print(proof.sandbox_total, proof.snippet)
```

This is where the docs-derived stream parse (`_parse`) is confirmed against a real
`executeCode` response. If `proof.matches` is False but the in-process total is right, inspect
`proof.stdout` — the parser shape is the thing to check.

IAM: `bedrock-agentcore:StartCodeInterpreterSession`,
`bedrock-agentcore:InvokeCodeInterpreter`, `bedrock-agentcore:StopCodeInterpreterSession`
(and `Create/Get/DeleteCodeInterpreter` if you provision your own rather than using the
built-in).

---

## 5. Observability — tracing the agent loop

Offline, the loop trace already works (`agent.observability.agent_loop_trace(result)` reads
the metrics every `AgentResult` carries; `enable_tracing(console=True)` prints real OTEL
spans). On AgentCore Runtime, export to the platform collector so traces land in CloudWatch
GenAI Observability:

```python
from agent.observability import enable_tracing, DEFAULT_TRACE_ATTRIBUTES
enable_tracing(console=False)          # uses OTEL_EXPORTER_OTLP_ENDPOINT (AgentCore injects it)
agent = build_orchestrator(model=..., trace_attributes=DEFAULT_TRACE_ATTRIBUTES)
```

Enable GenAI Observability for the account once (CloudWatch console -> Application Signals ->
Transaction Search / GenAI Observability, or the AgentCore console's Observability toggle).
IAM for the runtime role: `logs:PutLogEvents`, `cloudwatch:PutMetricData`, and the
`xray:PutTraceSegments` / OTLP permissions the AgentCore role policy grants by default.

---

## 6. AgentCore Runtime — hosting

Package and deploy the entrypoint (`agent/runtime.py::build_app`, marked `@app.entrypoint`).
Fastest path is the AgentCore starter toolkit:

```bash
pip install bedrock-agentcore-starter-toolkit
agentcore configure --entrypoint agent/runtime.py       # detects build_app / @app.entrypoint
agentcore launch                                        # builds the container, provisions Runtime
agentcore invoke '{"prompt": "Where do I stand? ..."}'  # smoke test the deployed handler
```

`launch` provisions the container, scaling, and the tracing pipeline (step 5). Set the step
2/3 env vars on the Runtime configuration so the deployed handler uses the live backends. The
runtime role needs the union of the IAM actions above plus `bedrock:InvokeModel*` for the
model in step 1.

---

## Env var summary

| Var | Values | Activates |
|---|---|---|
| `MAPLEGUARD_MEMORY_BACKEND` | `dev` \| `bedrock_kb` \| `none` | KB corpus (step 2) |
| `MAPLEGUARD_KB_ID` / `MAPLEGUARD_KB_REGION` | ids | KB corpus |
| `MAPLEGUARD_SESSION_BACKEND` | `file` \| `s3` \| `agentcore` \| `none` | sessions (step 3) |
| `MAPLEGUARD_SESSION_BUCKET` / `MAPLEGUARD_SESSION_PREFIX` | s3 | S3 sessions (3a) |
| `MAPLEGUARD_MEMORY_ID` / `MAPLEGUARD_MEMORY_REGION` / `MAPLEGUARD_ACTOR_ID` | ids | AgentCore Memory (3b) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | url | tracing export (step 5, AgentCore injects it) |

Everything with no var set stays on the offline dev mirror. `Deployment.from_env()` reads
them all; `Deployment.is_offline` is the guard that no seam reaches AWS.
