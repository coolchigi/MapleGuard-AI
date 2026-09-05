# Backend bring-up + test runbook

One strictly-ordered path from a clean checkout to a fully live backend. Each step states what
it verifies, the exact command, what "working" looks like, and whether it needs your AWS
credentials or spends money. Run the steps in order. Steps 1 to 3, plus the free live-feed and
offline-fake checks, have already been executed on this branch and their real results are quoted
inline (marked RESULT). The credentialed and paid steps are written out for you to run, and are
never run for you.

Cost/creds legend:
- FREE / LOCAL — no AWS, no network billing, run it yourself.
- NETWORK (free) — hits a public government feed, no AWS, no cost.
- NEEDS AWS CREDS — resolves your AWS identity, no charge by itself.
- SPENDS MONEY — a metered AWS call (Bedrock tokens, provisioned resources).

All Python commands run from `server/` with `PYTHONPATH=.`. The deterministic core is pure
stdlib, so steps 1 to 3 need only the `server/requirements.txt` install plus `pytest`.

---

## Step 1 — venv + dependencies  (FREE / LOCAL)

Verifies: a clean interpreter can install the server runtime deps.

```bash
cd agents-for-humans/mapleguard
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r server/requirements.txt
.venv/bin/python -m pip install pytest        # test runner, not a runtime dep
```

Working: pip ends with `Successfully installed ... fastapi ... anthropic ... strands-agents ...
bedrock-agentcore ...` and exit code 0. `.venv/` is gitignored.

RESULT (executed): clean install on Python 3.14.6, exit 0. All of fastapi, uvicorn, pydantic,
anthropic, strands-agents, bedrock-agentcore, boto3 resolved.

Note: `server/requirements.txt` does not pin `pytest` (it is a dev tool, not runtime). Install it
separately as shown, or the suite in step 2 reports `No module named pytest` inside the venv.

---

## Step 2 — offline test suite green  (FREE / LOCAL)

Verifies: the deterministic core, the agent layer, the API layer, and the AgentCore seams all
pass offline against injected fakes. No network, no AWS.

```bash
cd server && PYTHONPATH=. ../.venv/bin/python -m pytest -q
```

Working: all pass, only the genuinely-live integration tests skip, one xfail (the BC SIRS bands,
intentionally not line-verified yet).

RESULT (executed): **220 passed, 5 skipped, 1 xfailed** in the venv. With no deps installed at
all (pure system Python), the same command is **158 passed, 26 skipped, 1 xfailed** — the extra
62 that flip to passing are the FastAPI / Strands / bedrock-agentcore tests that need the
packages present. Either number is green.

The 5 remaining skips are the only tests that require a live backend or a key. They are named so
you know exactly what step lights each one up:

| Skipped test | Unlocked by | Covered in |
|---|---|---|
| `test_ingest_rounds.py` live fetch | `MAPLEGUARD_INGEST_LIVE=1` (network, free) | Step 3 / Step 7 |
| `test_api.py` real model | `ANTHROPIC_API_KEY` or Bedrock creds | Step 5 |
| `test_matcher.py` live matcher | `MAPLEGUARD_LLM_INTEGRATION=1` + key | Step 5 |
| `test_draft.py` live corrector | `MAPLEGUARD_LLM_INTEGRATION=1` + key | Step 5 |
| `test_agent.py` live agent | `MAPLEGUARD_AGENT_INTEGRATION=1` + Bedrock | Step 9 |

---

## Step 3 — run the API locally and smoke every endpoint  (FREE / LOCAL, one endpoint NETWORK)

Verifies: the exact HTTP contract the Next.js dashboard calls. Every endpoint deserializes,
calls a pure function (or the model-backed NOC path), and returns the typed result with its
citations. This is the contract the frontend must not break.

Start the server:

```bash
cd server && PYTHONPATH=. ../.venv/bin/python -m uvicorn api.asgi:app --port 8099
```

Then, with this profile as the body variable:

```bash
PROFILE='{"education":"bachelors-or-three-year","first_language":{"speaking":9,"listening":9,"reading":9,"writing":9},"date_of_birth":"1996-07-01","canadian_work_years":1,"first_language_test_date":"2025-09-30"}'
```

Every endpoint, its command, and the shape that proves it works:

| Endpoint | Command | Working shape (RESULT, executed) |
|---|---|---|
| `GET /health` | `curl -s :8099/health` | `{"status":"ok","noc_model":{"configured":false,...}}` — `configured:false` with no key is correct |
| `POST /position` | `curl -sX POST :8099/position -H 'Content-Type: application/json' -d "{\"profile\":$PROFILE,\"as_of\":\"2026-08-25\"}"` | `{"total":427,"core":389,"spouse":0,"skill_transfer":38,"additional":0,"breakdown":[{"factor":"age","points":105},...]}` |
| `POST /trajectory` | body `{"profile":$PROFILE,"start":"2026-08-25","end":"2028-01-01"}` | `{"points":[{"date":"2026-08-25","total":427},...],"cliffs":[{"date":"2027-09-30","kind":"test_expiry",...}]}` |
| `POST /deadlines` | body `{"profile":$PROFILE,"as_of":"2026-08-25"}` | `{"age_cliffs":[...],"test_expiry":"2027-09-30",...}` |
| `POST /dashboard` | body `{"profile":$PROFILE,"as_of":"2026-08-25"}` | `{"generatedBy":"api /dashboard (real crs engine)","position":{"categories":[...]},...}` — shape-identical to `web/src/data/demo.json` |
| `POST /sirs` | body `{"profile":$PROFILE}` | `{"score":70,"breakdown":[...],"job_offer_required":true,"eligible_to_register":false,"crs_bonus_if_nominated":600}` |
| `GET /draws` | `curl -s :8099/draws` **(NETWORK, free)** | `{"draws":[...439 items...],"needs_manual_check":[]}`, HTTP 200, each draw carries `provenance` (source_url, fetched, round_number) |
| `POST /reachable-paths` | body `{"profile":$PROFILE,"draws":<subset of /draws draws>,"as_of":"2026-08-25"}` | `{"as_of":...,"reachable":[],"within_reach":[],"blocked":[...],"needs_eligibility_check":[...]}` |
| `POST /audit` | body `{"letter_text":"...","noc_code":"21234"}` | **HTTP 503** with no key: `{"detail":"NOC model not configured: ..."}` — correct, becomes 200 after Step 5 |
| `POST /draft` | body `{"letter_text":"...","noc_code":"21234","supporting_facts":["..."]}` | **HTTP 503** with no key, same as `/audit` |

RESULT (executed): all ten endpoints returned the shapes above. `/draws` fetched **439 live
draws** from canada.ca (HTTP 200). `/reachable-paths` classified a live-draw subset correctly.
`/audit` and `/draft` returned 503 (model unconfigured), which is the designed behaviour until
Step 5, not a failure.

Contract note to carry into the frontend wiring: `/audit` and `/draft` check the model config
**before** validating the NOC code, so an unknown NOC with no key configured returns 503 (model)
rather than 404 (unknown NOC). Once a key is set, the 404 path is reachable. Harmless, but the
frontend should treat 503 as "model not ready" and 404 as "bad NOC".

---

## Step 4 — AWS credentials + Bedrock model access  (NEEDS AWS CREDS)

Verifies: your credentials resolve, and the target model is enabled in your region. This is the
gate for everything below. No charge for the identity checks themselves.

```bash
export AWS_REGION=us-east-1                       # a region that offers Bedrock + AgentCore
aws sts get-caller-identity                       # NEEDS AWS CREDS — prints your account/arn
aws bedrock list-foundation-models --region "$AWS_REGION" \
  --query "modelSummaries[?contains(modelId,'claude')].modelId" --output table
```

Then, in the Bedrock console (Model access), request access to the Claude model you will run on,
in `$AWS_REGION`. The runbook's default posture is a low-cost Sonnet model (not Opus) for the
orchestrator.

Working: `get-caller-identity` prints a real account id and ARN. `list-foundation-models` lists
the Claude model ids available to you. The console shows your target model as "Access granted".

Minimum IAM to call Bedrock: `bedrock:InvokeModel` (and `bedrock:InvokeModelWithResponseStream`)
on the model ARN, plus `bedrock:ListFoundationModels` for the check above. The full runtime role
adds more later (Steps 6 to 9); this is the floor to make a single model call.

> INTEGRATION GAP — read before Step 5. The NOC model id defaults to `claude-opus-5` in
> `server/noc/matcher.py` (`DEFAULT_MODEL`). That is not a valid Anthropic API model id and not a
> valid Bedrock model id, so Step 5 and the `/audit` `/draft` endpoints will fail against a real
> backend unless you override it. On every credentialed model command below, set
> `MAPLEGUARD_NOC_MODEL` to a real id for your backend:
> - Anthropic API: `export MAPLEGUARD_NOC_MODEL=claude-sonnet-4-5-20250929` (use the current
>   Sonnet 4.5 id your account exposes).
> - Bedrock: `export MAPLEGUARD_NOC_MODEL=<the exact modelId from the list command above>`
>   (Bedrock ids look like `anthropic.claude-...`, or an inference-profile id such as
>   `us.anthropic.claude-...`).
> This is a config default to fix in a follow-up branch, not something to paper over. Flagging
> per the honesty rule.

---

## Step 5 — model-backed NOC live on Bedrock  (SPENDS MONEY, small)

Verifies: the model-backed half (duty matcher + correction drafter) runs end to end against a
real Claude model, with the deterministic scorer and `validate_alignment` guard still on top.
Small cost: a handful of Claude calls on one short letter.

```bash
cd server
# Bedrock:
AWS_PROFILE=<you> MAPLEGUARD_NOC_BACKEND=bedrock \
  MAPLEGUARD_NOC_MODEL=<real-bedrock-model-id> \
  PYTHONPATH=. ../.venv/bin/python scripts/prove_noc_draft.py
# or Anthropic API:
ANTHROPIC_API_KEY=sk-... MAPLEGUARD_NOC_BACKEND=anthropic \
  MAPLEGUARD_NOC_MODEL=claude-sonnet-4-5-20250929 \
  PYTHONPATH=. ../.venv/bin/python scripts/prove_noc_draft.py
```

Working: prints `Using backend=... model=...`, then the audit gaps each citing NOC 21234 duty
text, then a corrected draft with `[employer to confirm: ...]` placeholders for unsupported
duties, then a re-audit showing the supported gap closed and the unsupported one still cited.
Ends with `OK: model-backed NOC audit + draft ran end to end with the trust guards intact.`

To light up the same path through the HTTP API (turns the Step 3 `/audit` `/draft` 503 into 200),
export the same three env vars before `uvicorn api.asgi:app`, then re-POST `/audit`. The live
pytest equivalents:

```bash
cd server
MAPLEGUARD_LLM_INTEGRATION=1 ANTHROPIC_API_KEY=sk-... MAPLEGUARD_NOC_MODEL=<real-id> \
  PYTHONPATH=. ../.venv/bin/python -m pytest tests/test_matcher.py tests/test_draft.py -q
```

NOT RUN here (spends money, needs your creds). Command handed off as-is.

---

## Step 6 — AgentCore capabilities, offline then live

Each capability has an offline-fake test (already green in Step 2) and a live test. The offline
result is quoted; the live command is handed off.

### 6a. Code Interpreter — the reproducible proof surface  (`agent/sandbox.py`)

Offline (FREE / LOCAL): `LocalSubprocessSandbox` recomputes CRS in a separate process and asserts
it equals the in-process engine.

```bash
cd server && PYTHONPATH=. ../.venv/bin/python -m pytest tests/test_agentcore.py -q
```

RESULT (executed): green. A direct run of `run_crs_in_sandbox(profile, as_of="2026-08-25")`
returned `matches=True sandbox_total=427`, equal to the in-process source of truth.

Live (SPENDS MONEY, small) — runs the same snippet inside a real AgentCore Code Interpreter
sandbox and confirms the docs-derived `executeCode` stream parse in
`AgentCoreCodeSandbox._parse`:

```bash
cd server && AWS_REGION=us-east-1 PYTHONPATH=. ../.venv/bin/python - <<'PY'
from agent.sandbox import build_agentcore_sandbox, run_crs_in_sandbox
prof={"education":"bachelors-or-three-year",
      "first_language":{"speaking":9,"listening":9,"reading":9,"writing":9},
      "date_of_birth":"1996-07-01","canadian_work_years":1}
sandbox=build_agentcore_sandbox(region="us-east-1")   # starts a session, uploads crs/ + serde
proof=run_crs_in_sandbox(prof, as_of="2026-08-25", sandbox=sandbox)
print("matches", proof.matches, "sandbox_total", proof.sandbox_total)
assert proof.matches, proof.stdout
PY
```

Working: `matches True sandbox_total 427`. If `matches` is False but the number is right, inspect
`proof.stdout` — the parser shape is the thing to confirm (this is the one docs-derived seam).
IAM: `bedrock-agentcore:StartCodeInterpreterSession` / `InvokeCodeInterpreterSession` /
`StopCodeInterpreterSession`. The built-in `aws.codeinterpreter.v1` needs no create step.

### 6b. KB memory — the cited corpus  (`agent/memory.py`, `agent/citations.py`)

Offline (FREE / LOCAL): `MemoryManager` over the seeded `TestMemoryStore` re-sources each flagged
NOC gap's citation from a retrieved passage. Covered by the agent tests in Step 2.

```bash
cd server && PYTHONPATH=. ../.venv/bin/python -m pytest tests/test_agent.py -q
```

RESULT (executed): green offline. The bright line holds — memory returns reference TEXT only,
never a number the engine scores against.

Live (SPENDS MONEY — KB provisioning + retrieval): stand up a Bedrock Knowledge Base over the
NOC passages, then point the agent at it. Full provisioning steps are in
`docs/agentcore-runbook.md` section 2. Smoke it with:

```bash
cd server && export MAPLEGUARD_MEMORY_BACKEND=bedrock_kb MAPLEGUARD_KB_ID=<kb-id> \
  MAPLEGUARD_KB_REGION=us-east-1
PYTHONPATH=. ../.venv/bin/python - <<'PY'
from agent import build_orchestrator
from agent.config import Deployment
d=Deployment.from_env()
print("offline?", d.is_offline, "memory backend wired to KB:", not d.is_offline)
PY
```

Working: `d.is_offline` is False once `MAPLEGUARD_MEMORY_BACKEND=bedrock_kb` and a KB id are set,
proving the seam reaches AWS instead of the in-memory mirror. IAM: `bedrock:Retrieve`,
`bedrock:GetKnowledgeBase`.

### 6c. Session / state stores  (`agent/stores_aws.py`)

Offline (FREE / LOCAL): `FileSessionManager` + profile in `agent.state` restores a conversation
by session id. Config-level tests confirm the AgentCore Memory seam is built with the right
shape. Covered in `tests/test_agentcore.py` (Step 2), including
`test_agentcore_session_manager_reaches_the_real_client`, which builds the real client and only
fails to connect because there is no live Memory resource — proof the wiring is real.

Live (SPENDS MONEY, small). Pick ONE backend:

```bash
# S3 sessions (simplest):
aws s3 mb s3://mapleguard-sessions-<suffix>
export MAPLEGUARD_SESSION_BACKEND=s3 MAPLEGUARD_SESSION_BUCKET=mapleguard-sessions-<suffix>
# or AgentCore Memory (longitudinal per-user profile) — create the resource per
# docs/agentcore-runbook.md 3b, then:
export MAPLEGUARD_SESSION_BACKEND=agentcore MAPLEGUARD_MEMORY_ID=<memory-id> \
  MAPLEGUARD_MEMORY_REGION=us-east-1
```

Working: after a run, `aws s3 ls s3://mapleguard-sessions-<suffix>/` lists the session object (S3
path), or `ListEvents` on the Memory resource returns the turn history (AgentCore path). IAM:
S3 get/put/list on the bucket, or `bedrock-agentcore:CreateEvent` / `ListEvents` /
`RetrieveMemoryRecords` / `GetMemory`.

---

## Step 7 — autonomous monitor loop  (local NETWORK-free, then Lambda)

Verifies: the unprompted watch loop — ingest the live feed, diff against the stored snapshot,
emit a relevance-filtered alert per affected profile, persist the snapshot so a second run is
quiet.

### 7a. Local end to end against the live feed  (NETWORK, free — no AWS)

```bash
cd server && PYTHONPATH=. ../.venv/bin/python - <<'PY'
from agent.monitor import (tick, MonitorDeps, InMemorySnapshotStore,
                           InMemoryProfileStore, CollectingAlertSink, StoredProfile)
from ingest import fetch_rounds_json, ROUNDS_JSON_URL
prof={"education":"bachelors-or-three-year",
      "first_language":{"speaking":9,"listening":9,"reading":9,"writing":9},
      "date_of_birth":"1996-07-01","canadian_work_years":1}
deps=MonitorDeps(fetch_rounds=fetch_rounds_json, source_url=ROUNDS_JSON_URL,
                 snapshots=InMemorySnapshotStore(),
                 profiles=InMemoryProfileStore([StoredProfile(id="demo", profile=prof)]),
                 sink=CollectingAlertSink())
r1=tick(deps, as_of="2026-08-25"); print("tick1 new_draws", r1.new_draw_count, "alerts", len(r1.alerts))
r2=tick(deps, as_of="2026-08-25"); print("tick2 new_draws", r2.new_draw_count, "alerts", len(r2.alerts))
PY
```

RESULT (executed): `tick1 new_draws 439 alerts 1` (cold snapshot, everything is new, one
self-actionable alert survives the relevance filter), `tick2 new_draws 0 alerts 0` (snapshot
persisted, nothing new, silence is a feature). This is the whole autonomous decision loop proven
locally with the LLM out of the decision path.

### 7b. As the Lambda handler  (SPENDS MONEY — after Step 8 stands up the stores)

`agent.monitor_lambda.lambda_handler` assembles `MonitorDeps` from the DynamoDB snapshot/profile
stores and the SNS-or-logging sink via `build_monitor_deps(env)`. It runs on the schedule Step 8
creates. Invoke it manually to confirm:

```bash
aws lambda invoke --function-name <monitor_function from tf output> \
  --payload '{"as_of":"2026-08-25"}' --cli-binary-format raw-in-base64-out /dev/stdout
```

Working: returns `{"ran_at":...,"new_draws":N,"alerts":[...],"snapshot":{...}}`. First real run
sees every current round as new (like tick1); subsequent scheduled runs are quiet until IRCC
posts a new round. IAM on the Lambda role: DynamoDB read/write on both tables, `sns:Publish` on
the alert topic, plus the feed fetch (public, no IAM).

---

## Step 8 — infra up, confirm, clean down  (SPENDS MONEY — provisions resources)

Verifies: the always-on monitor stack stands up, every resource is live, and teardown leaves
nothing orphaned. `infra/` is Terraform wrapped by a Makefile; you run the apply.

Offline pre-check (FREE / LOCAL, already run):

```bash
cd infra && terraform init -backend=false && terraform validate && terraform fmt -check -recursive
```

RESULT (executed): `Success! The configuration is valid.` fmt clean. Ten resources declared:
`aws_s3_bucket.sessions`, `aws_dynamodb_table.profiles`, `aws_dynamodb_table.snapshot`,
`aws_sns_topic.alerts`, `aws_iam_role.monitor` (+ policy + attachment), `aws_lambda_function.monitor`,
`aws_cloudwatch_event_rule.monitor` (+ target + permission).

Stand it up (NEEDS AWS CREDS, SPENDS MONEY — DynamoDB is PAY_PER_REQUEST so idle cost is ~zero,
Lambda + EventBridge bill per run):

```bash
cd infra
make aws-up            # terraform init + apply -auto-approve
make output            # prints session_bucket, profiles_table, snapshot_table, alerts_topic_arn,
                       # monitor_function, schedule -> these become the MAPLEGUARD_* env vars
```

Confirm each resource is live end to end (not just "apply succeeded"):

```bash
aws dynamodb describe-table --table-name $(cd infra && terraform output -raw profiles_table) \
  --query 'Table.TableStatus'                        # -> "ACTIVE"
aws dynamodb describe-table --table-name $(cd infra && terraform output -raw snapshot_table) \
  --query 'Table.TableStatus'                        # -> "ACTIVE"
aws s3 ls s3://$(cd infra && terraform output -raw session_bucket)          # bucket exists
aws sns get-topic-attributes --topic-arn $(cd infra && terraform output -raw alerts_topic_arn) \
  --query 'Attributes.TopicArn'                       # topic exists
aws lambda get-function --function-name $(cd infra && terraform output -raw monitor_function) \
  --query 'Configuration.State'                       # -> "Active"
aws events describe-rule --name <rule name> --query 'ScheduleExpression'     # e.g. rate(6 hours)
```

Seed a monitored profile and let the schedule (or a manual Step 7b invoke) run:

```bash
aws dynamodb put-item --table-name $(cd infra && terraform output -raw profiles_table) \
  --item '{"id":{"S":"demo"},"data":{"S":"{\"education\":\"bachelors-or-three-year\",\"first_language\":{\"speaking\":9,\"listening\":9,\"reading\":9,\"writing\":9},\"date_of_birth\":\"1996-07-01\",\"canadian_work_years\":1}"}}'
```

Working: `describe-table` ACTIVE, Lambda State Active, the rule's schedule matches
`schedule_expression` (default `rate(6 hours)`), and after an invoke the snapshot table holds a
snapshot item. The full shape end to end: EventBridge rule -> Lambda -> reads live feed + profiles
table -> diffs vs snapshot table -> publishes to SNS -> writes snapshot back.

Clean teardown — the proof there are no orphans (SPENDS/STOPS billing):

```bash
cd infra && make aws-down          # terraform destroy -auto-approve
terraform state list               # -> empty
```

Working: destroy reports every resource removed, `terraform state list` is empty. S3 uses
`force_destroy` and the tables are PAY_PER_REQUEST, so the sweep is clean and instant with no
leftover buckets or provisioned capacity. Every resource is tagged `Project=mapleguard` if you
want to double-check in the console.

Note: AgentCore Runtime (Step 9) is deliberately NOT in this Terraform. It deploys via its own
`agentcore` CLI. So `make aws-down` does not touch the hosted agent — tear that down separately in
Step 9.

---

## Step 9 — AgentCore Runtime, hosting the agent  (SPENDS MONEY — provisions + per-invoke)

Verifies: the agent runs as a hosted AgentCore Runtime and responds to an invoke. The
module-level entrypoint is `server/agent/agentcore_app.py` (exposes `app`, a
`BedrockAgentCoreApp`); `server/Dockerfile` is the explicit arm64 container.

```bash
pip install bedrock-agentcore-starter-toolkit        # the `agentcore` CLI is not installed yet
cd server
agentcore configure --entrypoint agent/agentcore_app.py
agentcore launch                                     # builds arm64 container, provisions Runtime
agentcore invoke '{"prompt":"Where do I stand? Education bachelors, CLB 9, age 30, 1yr Cdn work."}'
```

Set the Step 6b/6c env vars (`MAPLEGUARD_MEMORY_BACKEND`, `MAPLEGUARD_SESSION_BACKEND`, ids) on
the Runtime configuration so the hosted handler uses the live backends. The runtime role needs
the union of the IAM from Steps 6 to 8 plus `bedrock:InvokeModel*` for your Step 4 model.

Working: `agentcore launch` finishes with a Runtime ARN; `agentcore invoke` returns a JSON
response where the agent narrates a position it computed through the deterministic tools (never a
number the model made up), with the never-submit / never-assert gates intact. Live pytest
equivalent:

```bash
cd server && MAPLEGUARD_AGENT_INTEGRATION=1 AWS_PROFILE=<you> \
  MAPLEGUARD_NOC_MODEL=<real-bedrock-id> PYTHONPATH=. ../.venv/bin/python -m pytest tests/test_agent.py -q
```

Confirm the hosted agent responds, then tear down through the AgentCore console or CLI when done
(it is not covered by `make aws-down`).

---

## Env var summary (for Steps 5 to 9)

| Var | Values | Activates |
|---|---|---|
| `MAPLEGUARD_NOC_BACKEND` | `anthropic` \| `bedrock` \| `auto` | which real model client (Step 5) |
| `MAPLEGUARD_NOC_MODEL` | a real model id | overrides the bad `claude-opus-5` default (Step 4 gap) |
| `MAPLEGUARD_MEMORY_BACKEND` | `dev` \| `bedrock_kb` \| `none` | KB corpus (6b) |
| `MAPLEGUARD_KB_ID` / `MAPLEGUARD_KB_REGION` | ids | KB corpus |
| `MAPLEGUARD_SESSION_BACKEND` | `file` \| `s3` \| `agentcore` \| `none` | sessions (6c) |
| `MAPLEGUARD_SESSION_BUCKET` | bucket | S3 sessions |
| `MAPLEGUARD_MEMORY_ID` / `MAPLEGUARD_MEMORY_REGION` | ids | AgentCore Memory (6c/9) |

Everything with no var set stays on the offline dev mirror. `Deployment.from_env()` reads them;
`Deployment.is_offline` is the guard that no seam reaches AWS. Deeper AWS provisioning detail
(exact console flows, IAM policy text) lives in `docs/agentcore-runbook.md`; this file is the
ordered path, that one is the reference.
