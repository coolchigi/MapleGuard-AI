# MapleGuard setup + stand-up guide

The one doc from a clean checkout to running, local and on AWS. Deep AWS provisioning detail
(console flows, per-capability IAM) lives in `agentcore-runbook.md`; everything else is here.

Legend: **LOCAL** (no AWS) · **CREDS** (needs AWS identity, no charge) · **$** (spends money).

## The product loop

A user saves a profile (with an optional reference letter) → the deterministic engine computes
their CRS/SIRS position → the autonomous monitor watches draws AND policy changes, computes the
**delta**, then per stored profile decides whether the change actually **moves that person**
(relevance filter) and alerts with the answer — the shortest move, the cliff, or (on a NOC
reclassification) the reference-letter gaps against the new TEER duties — not "the page changed" →
the Bedrock Knowledge Base supplies the cited corpus behind NOC gaps. Determinism below the
model throughout: the model routes, reads, classifies, and explains; it never computes a number or
asserts eligibility.

Two watches now: draws, and **policy changes** — `classify_policy_change` has a model extract
{change_type, affected_noc_codes, effective_date} from an IRCC update, then a deterministic
validator drops anything malformed; a validated NOC change re-audits each affected profile's stored
letter (reusing the real audit path) and cites the gaps. And `POST /brief` assembles the whole thing
— CRS position, dated next moves, cited letter gaps, the drafted correction — into one document to
hand a consultant; every number/citation is the core's, only the cover prose is model-written (and
screened for eligibility verdicts).

The whole loop runs on ONE profile store: `POST /profiles` (intake, letter optional) writes it, the
monitor lists it — no hand-seeded DynamoDB items.

## Deploy status — what's wired vs what needs live creds

Closed in code (tested offline):
- **Profile intake** — `POST /profiles` persists a profile (same shape as `/dashboard`, validated
  by serde) to the store the monitor reads. File store locally, DynamoDB in deploy, one config
  seam (`agent.config.build_profile_store`). The web form's `saveProfile` posts the same JSON.
- **API deploy** — the FastAPI app deploys as a Lambda + public Function URL (`infra/api.tf`,
  `api/lambda_handler.py` via Mangum), sharing the monitor's profiles table. The web app points at
  its URL via `NEXT_PUBLIC_API_BASE_URL`.
- **AgentCore model + KB** — the orchestrator pins one Bedrock model; the NOC audit re-sources gap
  citations from the KB when `MAPLEGUARD_MEMORY_BACKEND=bedrock_kb`; the runtime-role IAM for
  `bedrock:InvokeModel` is in `agentcore-runbook.md` step 1.

Still needs live creds / spend to verify (cannot run here):
- The API Lambda apply (`make aws-up`) and a real invoke of `/profiles` + `/audit`.
- `agentcore configure/launch/invoke` with model access + the role's InvokeModel policy attached.
- The Bedrock KB provisioned so `/audit` cites from live retrieval; AgentCore Memory cross-session.
- **Order traps:** Bedrock model access must precede any invoke; `make aws-up` runs `api-package`
  (builds the API Lambda zip) before apply — don't `terraform apply` the API by hand without it;
  the first monitor tick on an empty snapshot counts every current draw new (quiet from tick 2).

---

## Local — clean checkout to a running stack (LOCAL; one endpoint hits a public feed)

```bash
# 1. venv + deps
cd agents-for-humans/mapleguard
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r server/requirements.txt pytest   # pytest is dev-only, not a runtime dep
```
Working: pip exits 0 with fastapi, mangum, anthropic, strands-agents, bedrock-agentcore, boto3.

```bash
# 2. offline suite green (no network, no AWS)
cd server && PYTHONPATH=. ../.venv/bin/python -m pytest -q
```
Working: `238 passed, 5 skipped, 1 xfailed`. The 5 skips are the live-backend tests, each lit up by
a later step: rounds live-fetch (`MAPLEGUARD_INGEST_LIVE=1`, free), real NOC model (`/audit`,
step 5), the two live NOC unit tests (`MAPLEGUARD_LLM_INTEGRATION=1` + creds), and the live agent
(`MAPLEGUARD_AGENT_INTEGRATION=1` + Bedrock).

```bash
# 3. run the API and exercise the loop locally (file profile store, no AWS)
cd server && PYTHONPATH=. ../.venv/bin/python -m uvicorn api.asgi:app --port 8000
# in another shell:
PROFILE='{"education":"bachelors-or-three-year","first_language":{"speaking":9,"listening":9,"reading":9,"writing":9},"date_of_birth":"1996-07-01","canadian_work_years":1}'
curl -s :8000/health                                                          # {"status":"ok","noc_model":{"configured":...}}
curl -sX POST :8000/position  -H 'Content-Type: application/json' -d "{\"profile\":$PROFILE}"   # {"total":427,...}
curl -sX POST :8000/profiles  -H 'Content-Type: application/json' -d "{\"profile\":$PROFILE}"   # {"id":"...","monitored":true}
curl -s :8000/profiles                                                        # {"profiles":[{"id":"..."}]}
curl -s :8000/draws                                                           # ~439 live cited draws (public feed, free)
```
Working: `/position` returns a computed total + per-factor breakdown; `/profiles` persists to the
local file store (`.mapleguard/profiles/` by default, or `MAPLEGUARD_PROFILES_DIR`); `/audit` +
`/draft` return **503** until a model is configured (step 5) — by design. A malformed profile
answers 422 (serde is the single validation path).

```bash
# 4. see the monitor watch the profile you just saved (same file store, no AWS)
cd server && MAPLEGUARD_INGEST_LIVE=1 PYTHONPATH=. ../.venv/bin/python - <<'PY'
from agent.config import Deployment, build_profile_store
from agent.monitor import tick, MonitorDeps, InMemorySnapshotStore, CollectingAlertSink
from ingest import fetch_rounds_json, ROUNDS_JSON_URL
store = build_profile_store(Deployment.from_env())          # the SAME store the API wrote to
deps = MonitorDeps(fetch_rounds=fetch_rounds_json, source_url=ROUNDS_JSON_URL,
                   profiles=store, snapshots=InMemorySnapshotStore(), sink=CollectingAlertSink())
r = tick(deps, as_of="2026-08-25")
print("watched profiles:", [p.id for p in store.list_profiles()], "alerts:", len(r.alerts))
PY
```
Working: prints the ids you saved in step 3 and any alerts. Demo seed without curl:
`python scripts/seed_profile.py` (writes through the same store).

```bash
# 5. the web dashboard (LOCAL)
cd web && npm install
echo 'NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000' > .env.local
npm run dev        # http://localhost:3000
```
Working: the dashboard loads, sliders + time-machine recompute instantly (Pyodide), and live
`/draws` / `/dashboard` resolve against the API from step 3. The profile form's submit can call
`saveProfile` (web/src/lib/api.ts) to enter the monitored set. No API reachable → it falls back to
the bundled `web/src/data/demo.json` (same shape as `/dashboard`).

---

## AWS — model access, then the stack (CREDS / $)

```bash
# 6. creds + pinned-model access  (CREDS)
export AWS_REGION=us-east-1
aws sts get-caller-identity
# Enable this exact inference profile in the Bedrock console (Model access -> Claude Sonnet 4.5):
#   us.anthropic.claude-sonnet-4-5-20250929-v1:0   (== agent.config.DEFAULT_BEDROCK_MODEL_ID)
# If yours differs: export MAPLEGUARD_BEDROCK_MODEL=<your enabled inference-profile id>
```
Attach `bedrock:InvokeModel` + `InvokeModelWithResponseStream` on the inference-profile ARN AND
the per-region foundation-model ARNs (`agentcore-runbook.md` step 1 — the most common first-invoke
failure). For NOC audit live on Bedrock ($ small): `cd server && MAPLEGUARD_NOC_BACKEND=bedrock
PYTHONPATH=. ../.venv/bin/python scripts/prove_noc_draft.py` (no `ANTHROPIC_API_KEY` needed).

```bash
# 7. stand up the stack: monitor + API Lambda, sharing the profiles table  ($ ~0 idle)
cd infra && make aws-up        # runs `make api-package` (builds the API zip) then terraform apply
make output                    # profiles_table, snapshot_table, monitor_function, api_url, ...
```
Working: `make output` prints `api_url` (the public HTTPS Function URL). Point the web app at it:
`NEXT_PUBLIC_API_BASE_URL=$(terraform output -raw api_url)`. Now the deployed frontend has a real
backend, and a `POST /profiles` there lands in the DynamoDB table the monitor scans — the loop runs
in the cloud with no hand-seeding. Seed a profile through the deployed API (or `MAPLEGUARD_PROFILES_TABLE=$(terraform output -raw profiles_table) python server/scripts/seed_profile.py`, same store). Teardown:
`make aws-down` then `terraform state list` is empty. AgentCore Runtime is separate (step 8).

```bash
# 8. host the agent on AgentCore Runtime  ($)
pip install bedrock-agentcore-starter-toolkit
cd server && agentcore configure --entrypoint agent/agentcore_app.py
# set the live backends on the Runtime config so Memory/KB are NOT inert:
#   MAPLEGUARD_MEMORY_BACKEND=bedrock_kb  MAPLEGUARD_KB_ID=<id>          (cited NOC corpus)
#   MAPLEGUARD_SESSION_BACKEND=agentcore  MAPLEGUARD_MEMORY_ID=<id>      (per-user memory)
agentcore launch
agentcore invoke '{"prompt":"Where do I stand? Education bachelors, CLB 9, age 30, 1yr Cdn work.","session_id":"demo-user"}'
```
Working: `invoke` returns JSON where the agent narrates a position computed through the deterministic
tools, gates intact. Confirm the execution role carries the step-6 InvokeModel policy first.
KB/Memory/Code-Interpreter provisioning + IAM: `agentcore-runbook.md` steps 2–6.

---

## Shortest demo path

Local, no AWS spend, whole loop: **steps 1 → 2 → 3 → 4 → 5** (save a profile through the API, watch
the monitor re-score it, see the dashboard). Add **step 5's live NOC** on Bedrock and **step 7/8**
for the deployed backend + hosted agent when you want the cloud story on camera.
