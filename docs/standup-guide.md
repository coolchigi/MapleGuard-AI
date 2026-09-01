# MapleGuard stand-up guide — zero to running

One page, top to bottom, assuming **PR #5 is merged** (pinned Bedrock model, Bedrock-backed NOC
tools, per-session agent, auto-tracing). Two companion docs go deeper and are cross-referenced:
`backend-bringup.md` (the ordered 9-step path with real RESULT outputs) and `agentcore-runbook.md`
(per-capability AWS provisioning + IAM). This page is the fast path plus the honest gap list.

Legend: **LOCAL** (no AWS) · **CREDS** (needs AWS identity, no charge) · **$** (spends money).

---

## What's missing to actually run — ranked (read this first)

The code is written and tested offline; these are the gaps between "written" and "stands up".
Ranked by how hard they block a live end-to-end demo.

### P0 — blocks a working end-to-end demo

1. **Nothing writes monitored profiles into DynamoDB.** `DynamoDBProfileStore` has only
   `list_profiles()` (a read); no API endpoint, script, or agent path writes a profile to the
   `*-profiles` table. So the autonomous monitor scans an **empty table and never alerts**. The
   only way in today is a hand-written `aws dynamodb put-item` (shown in step 6 below and
   `backend-bringup.md` step 8). *Fix later: a small `POST /monitor/profiles` endpoint or a seed
   script that writes `{"id", "profile", "bc_offer"?}` as a JSON `data` attribute.*

2. **The FastAPI API has no deployment.** `infra/` only stands up the monitor stack (S3 + DynamoDB
   + SNS + Lambda + EventBridge); there is no container or host for `api.asgi:app`, and the
   `server/Dockerfile` is the **AgentCore agent**, not the API. The web app defaults to
   `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000`, so live `/dashboard`, `/draws`, `/audit`
   only work while you run `uvicorn` locally. A deployed frontend has no backend to call. *Fix
   later: an API container + host (App Runner / ECS / Lambda-adapter), or run uvicorn on a box the
   browser can reach.*

3. **On AgentCore Runtime, the AWS primitives are inert until you set env + IAM.** `build_app`
   defaults to `MAPLEGUARD_MEMORY_BACKEND=dev` and `SESSION_BACKEND=file`, so the hosted agent uses
   the offline seeded corpus and no cross-session Memory **unless you set the env vars on the
   Runtime config** (step 7). And the execution role the `agentcore` CLI creates does **not**
   automatically carry `bedrock:InvokeModel` for the pinned model, nor the KB / Memory /
   Code-Interpreter grants — attach them or the first invoke fails AccessDenied. Policy is in
   `agentcore-runbook.md` step 1.

### P1 — order-of-operations / bootstrap traps

4. **`agentcore launch` prerequisites and Dockerfile ownership.** `launch` needs the starter
   toolkit (`pip install bedrock-agentcore-starter-toolkit`), builds a **linux/arm64** image, and
   provisions ECR itself (via CodeBuild or local Docker — Docker must be running for the local
   path). `agentcore configure` typically **generates its own Dockerfile/config**, so the
   hand-written `server/Dockerfile` may be ignored — treat it as the reference contract, and
   verify the generated config installs `requirements.txt` and runs `agent.agentcore_app`.
   **Order trap:** Bedrock model access (step 4) must exist *before* `agentcore invoke`.

5. **The web frontend has no stand-up step anywhere.** `web/` needs `npm install`, the
   `NEXT_PUBLIC_API_BASE_URL` env, and `npm run dev`/`build`. Covered in step 8 below; it was
   absent from both existing runbooks (they are backend-only).

6. **First real monitor tick floods.** With an empty snapshot, `tick` marks **every current draw
   new** (the local proof shows 439). It is quiet only from the *second* run on. If you seed
   profiles before the first scheduled run, prime the snapshot (one manual invoke) or expect a
   one-time burst.

### P2 — minor / robustness

7. **Region consistency.** The pinned model defaults to `us-east-1`; KB, Memory, and Code
   Interpreter must live in the **same region** (or set `MAPLEGUARD_*_REGION` per seam), or calls
   cross-region-mismatch.
8. **Multi-turn needs a stable session id.** The handler keys per-caller state on the AgentCore
   session id; pass a stable one to `agentcore invoke` (or the client header) for continuity —
   otherwise every invoke is a fresh session (correct, but no memory of the last turn).
9. **`boto3` is now declared** in `requirements.txt` (was transitive only). **`pytest` is not** a
   runtime dep — install it separately (step 1).

---

## Local — from a clean checkout to a running API  (all LOCAL, one endpoint hits a public feed)

```bash
# 1. venv + deps
cd agents-for-humans/mapleguard
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r server/requirements.txt pytest
```
Working: pip exits 0 with fastapi, anthropic, strands-agents, bedrock-agentcore, boto3 resolved.

```bash
# 2. offline suite green (no network, no AWS)
cd server && PYTHONPATH=. ../.venv/bin/python -m pytest -q
```
Working: `227 passed, 5 skipped, 1 xfailed`. The 5 skips are the live-backend tests (they light up
with creds/keys). See `backend-bringup.md` step 2 for the skip→step map.

```bash
# 3. run the API and smoke it
cd server && PYTHONPATH=. ../.venv/bin/python -m uvicorn api.asgi:app --port 8000
# in another shell:
curl -s :8000/health          # {"status":"ok","noc_model":{"configured":false,...}} with no creds
PROFILE='{"education":"bachelors-or-three-year","first_language":{"speaking":9,"listening":9,"reading":9,"writing":9},"date_of_birth":"1996-07-01","canadian_work_years":1}'
curl -sX POST :8000/position -H 'Content-Type: application/json' -d "{\"profile\":$PROFILE,\"as_of\":\"2026-08-25\"}"   # {"total":427,...}
curl -s :8000/draws           # ~439 live cited draws (hits canada.ca, free)
```
Working: `/position` returns a computed total with a per-factor breakdown; `/draws` returns cited
draws. `/audit` + `/draft` return **503** until a model is configured (below) — by design. Full
endpoint table with expected shapes: `backend-bringup.md` step 3.

---

## AWS — model access, then the pieces  (CREDS / $)

```bash
# 4. creds + pinned-model access  (CREDS)
export AWS_REGION=us-east-1
aws sts get-caller-identity                                  # prints your account/arn
# Enable this exact inference profile in the Bedrock console (Model access -> Claude Sonnet 4.5):
#   us.anthropic.claude-sonnet-4-5-20250929-v1:0   (== agent.config.DEFAULT_BEDROCK_MODEL_ID)
# If yours differs: export MAPLEGUARD_BEDROCK_MODEL=<your enabled inference-profile id>
```
Working: caller identity resolves; the console shows the model "Access granted". Attach
`bedrock:InvokeModel` + `InvokeModelWithResponseStream` on the inference-profile ARN **and** the
per-region foundation-model ARNs (see `agentcore-runbook.md` step 1 — the single most common
first-invoke failure).

```bash
# 5. NOC audit/draft live on Bedrock  ($ small — a few Claude calls)
cd server
MAPLEGUARD_NOC_BACKEND=bedrock PYTHONPATH=. ../.venv/bin/python scripts/prove_noc_draft.py
```
Working: prints the audit gaps (each citing NOC 21234 duty text), a corrected draft with
`[employer to confirm: ...]` placeholders, and ends `OK: ... trust guards intact.` Set
`MAPLEGUARD_NOC_BACKEND=bedrock` before `uvicorn` to turn the `/audit` `/draft` 503s into 200s.
(No `ANTHROPIC_API_KEY` needed — Bedrock uses your AWS creds, per PR #5.)

```bash
# 6. monitor stack up + SEED A PROFILE (the P0-1 gap) + confirm  ($ — PAY_PER_REQUEST, ~0 idle)
cd infra && make aws-up && make output
# >>> nothing to monitor until you seed a profile: <<<
aws dynamodb put-item --table-name $(terraform output -raw profiles_table) \
  --item '{"id":{"S":"demo"},"data":{"S":"{\"education\":\"bachelors-or-three-year\",\"first_language\":{\"speaking\":9,\"listening\":9,\"reading\":9,\"writing\":9},\"date_of_birth\":\"1996-07-01\",\"canadian_work_years\":1}"}}'
aws lambda invoke --function-name $(terraform output -raw monitor_function) \
  --payload '{"as_of":"2026-08-25"}' --cli-binary-format raw-in-base64-out /dev/stdout
```
Working: `make output` prints table/bucket/topic/function names; the manual invoke returns
`{"ran_at":...,"new_draws":N,"alerts":[...],"snapshot":{...}}`. First run sees all current draws
new (P1-6 flood); the next scheduled run is quiet. Teardown: `make aws-down` then
`terraform state list` is empty. AgentCore Runtime is **not** in this Terraform — tear it down
separately (step 7). Detail: `backend-bringup.md` step 8.

```bash
# 7. host the agent on AgentCore Runtime  ($ — provisions + per-invoke)
pip install bedrock-agentcore-starter-toolkit
cd server
agentcore configure --entrypoint agent/agentcore_app.py
# set the live backends on the Runtime config so Memory/KB are NOT inert (P0-3):
#   MAPLEGUARD_SESSION_BACKEND=agentcore  MAPLEGUARD_MEMORY_ID=<id>  MAPLEGUARD_MEMORY_REGION=us-east-1
#   MAPLEGUARD_MEMORY_BACKEND=bedrock_kb  MAPLEGUARD_KB_ID=<id>      (optional cited corpus)
agentcore launch                                            # arm64 build -> ECR -> Runtime
agentcore invoke '{"prompt":"Where do I stand? Education bachelors, CLB 9, age 30, 1yr Cdn work.","session_id":"demo-user"}'
```
Working: `launch` ends with a Runtime ARN; `invoke` returns JSON where the agent narrates a
position it computed **through the deterministic tools** (never a model-invented number), gates
intact. Confirm the execution role carries the step-4 InvokeModel policy first (P0-3). Provisioning
+ IAM for Memory / KB / Code Interpreter: `agentcore-runbook.md` steps 2–6.

Optional live checks (each `$`, offline mirrors already pass in step 2):
- **Code Interpreter** proof surface — `agentcore-runbook.md` step 4 / `backend-bringup.md` 6a.
- **AgentCore Memory** cross-session restore — `agentcore-runbook.md` step 3b.

---

## Web — the proof-surface dashboard  (LOCAL)

```bash
# 8. run the frontend against the local API (or your deployed API URL)
cd web
npm install
echo 'NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000' > .env.local   # or your hosted API
npm run dev            # http://localhost:3000
```
Working: the dashboard loads, the position panel + what-if sliders + time-machine scrubber recompute
instantly client-side (Pyodide), and the live `/draws` + `/audit` calls resolve against the API from
step 3/5. With no API reachable it falls back to the bundled `web/src/data/demo.json` (same shape as
`/dashboard`). Remember the API host must be reachable from the browser (P0-2).

---

## The shortest demo path

Local only, no AWS spend, shows the whole trust story: **steps 1 → 2 → 3 → 8** (offline agent tests
prove the compute-and-refuse loop; the API + web show live cited draws and the deterministic
position). Add **step 5** for live NOC audit on Bedrock, and **step 7** for the hosted AgentCore
agent when you want the deployed-runtime story on camera.
