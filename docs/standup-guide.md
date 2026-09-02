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
the Bedrock Knowledge Base supplies the cited corpus behind NOC gaps → `POST /brief` assembles it
into one consultant-ready document. Determinism below the model throughout: the model routes, reads,
classifies, and explains; it never computes a number or asserts eligibility.

The whole loop runs on ONE profile store: the intake endpoints write it, the monitor lists it —
no hand-seeded DynamoDB items.

## Deploy status — what's wired vs what needs live creds

Wired in code (tested offline, 249 passing):
- **Profile + letter intake** — `POST /profiles` / `PUT /profiles/{id}/letter` persist to the store
  the monitor reads (file locally, DynamoDB in deploy; one seam, `agent.config.build_profile_store`).
- **API deploy** — the FastAPI app as a Lambda + public Function URL (`infra/api.tf`,
  `api/lambda_handler.py` via Mangum), sharing the monitor's profiles table.
- **Policy-change watch** — `classify_policy_change` (model extracts, `validate_policy_change` drops
  bad output); a validated NOC change re-audits the stored letter via the real audit path.
- **Consultant brief** — `POST /brief`; numbers/citations from the core, prose screened.
- **AgentCore model + KB** — one pinned Bedrock model; NOC audit re-sources citations from the KB
  when `MAPLEGUARD_MEMORY_BACKEND=bedrock_kb`.

Still needs live creds / spend (cannot run here):
- API Lambda apply (`make aws-up`) and a real invoke of `/profiles` / `/audit` / `/brief`.
- `agentcore configure/launch/invoke` with model access + the role's `bedrock:InvokeModel` policy.
- The Bedrock classifier + duty-matcher on deploy, and a real IRCC-update URL for the deployed
  monitor's `MAPLEGUARD_POLICY_URL`.
- The Bedrock KB provisioned so `/audit` cites from live retrieval; AgentCore Memory cross-session.
- **PII:** stored reference letters are **unscrubbed** until Bedrock Guardrails PII redaction is
  provisioned (flagged, not faked — scrub on write once Guardrails is stood up).
- **Order traps:** Bedrock model access must precede any invoke; `make aws-up` runs `api-package`
  (builds the API Lambda zip) before apply — don't `terraform apply` the API by hand without it;
  the first monitor tick on an empty snapshot counts every current draw new (quiet from tick 2).

---

## Local — clean checkout to a running stack (LOCAL; one endpoint hits a public feed)

```bash
# 1. venv + deps   (LOCAL)
cd agents-for-humans/mapleguard
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r server/requirements.txt pytest   # pytest is dev-only, not runtime
```
Working: pip exits 0 with fastapi, mangum, anthropic, strands-agents, bedrock-agentcore, boto3.

```bash
# 2. offline suite green   (LOCAL)
cd server && PYTHONPATH=. ../.venv/bin/python -m pytest -q
```
Working: `249 passed, 5 skipped, 1 xfailed`. The 5 skips are live-backend tests lit up later:
rounds live-fetch (`MAPLEGUARD_INGEST_LIVE=1`, free), real NOC model (`/audit`, step 6), two live
NOC unit tests (`MAPLEGUARD_LLM_INTEGRATION=1` + creds), and the live agent
(`MAPLEGUARD_AGENT_INTEGRATION=1` + Bedrock).

```bash
# 3. run the API   (LOCAL; /draws hits a public feed)
cd server && PYTHONPATH=. ../.venv/bin/python -m uvicorn api.asgi:app --port 8000
```

```bash
# 4. profile + reference-letter intake — put a candidate in front of the monitor   (LOCAL)
PROFILE='{"education":"bachelors-or-three-year","first_language":{"speaking":9,"listening":9,"reading":9,"writing":9},"date_of_birth":"1996-07-01","canadian_work_years":1}'
LETTER='This confirms Jane Doe worked as a Web Developer, 37.5 hrs/wk at $85,000. She wrote some HTML. Sincerely.'
# save the profile WITH a letter (one call), keyed by a stable id:
curl -sX POST :8000/profiles -H 'Content-Type: application/json' \
  -d "{\"profile\":$PROFILE,\"id\":\"demo\",\"reference_letter\":{\"noc_code\":\"21234\",\"letter_text\":\"$LETTER\"}}"
# ...or attach/replace a letter on an existing profile:
curl -sX PUT :8000/profiles/demo/letter -H 'Content-Type: application/json' \
  -d "{\"noc_code\":\"21234\",\"letter_text\":\"$LETTER\"}"
curl -s :8000/profiles            # {"profiles":[{"id":"demo"}]}  <- this is what the monitor scans
curl -s :8000/profiles/demo       # the stored profile + reference_letter
```
Working: `POST /profiles` → `{"id":"demo","monitored":true}`; `PUT .../letter` →
`{"letter_stored":true,...}`. The profile+letter are persisted to the local file store
(`.mapleguard/profiles/` by default, or `MAPLEGUARD_PROFILES_DIR`) — the SAME store the monitor
lists, so a saved profile is a watched profile with no hand-seeding. A malformed profile answers 422
(serde is the single validation path). `/audit`, `/draft`, and the letter form of `/brief` answer
**503** until a model is configured (step 6). Seed without curl: `python scripts/seed_profile.py`
(writes through the same store).

```bash
# 5. the monitor watches BOTH: a new draw, and a NOC-reclassification -> letter re-audit   (LOCAL)
cd server && PYTHONPATH=. ../.venv/bin/python - <<'PY'
from agent.config import Deployment, build_profile_store
from agent.monitor import tick, MonitorDeps, InMemorySnapshotStore, CollectingAlertSink
from ingest import validate_policy_change
# The SAME store the API wrote to in step 4:
store = build_profile_store(Deployment.from_env())
# Simulate a validated IRCC NOC 2016->TEER 2021 reclassification touching NOC 21234. In deploy the
# model extracts this and validate_policy_change drops bad output; here we build the validated change
# and stub the two model steps so the BRIDGE runs offline (extract + duty-match need creds, step 6).
change = validate_policy_change(
    {"change_type": "noc", "affected_noc_codes": ["21234"], "effective_date": "2022-11-16",
     "summary": "NOC 2016 -> TEER 2021 reclassification"},
    "https://www.canada.ca/noc-2021-teer-update").to_dict()
deps = MonitorDeps(
    fetch_rounds=lambda: '{"rounds": []}',                       # no new draw; the trigger is policy
    profiles=store, snapshots=InMemorySnapshotStore(), sink=CollectingAlertSink(),
    fetch_policy_update=lambda: "IRCC reclassifies NOC 21234 to TEER 2021",
    classify_update=lambda text: change,                          # deploy: Bedrock classifier + validate
    matcher=lambda letter, occ: ({}, ""))                         # deploy: the real duty-matcher
r = tick(deps, as_of="2026-08-25")
for a in r.alerts:
    if a.policy_change:
        print("policy alert for", a.profile_id, "| CRS", a.crs["after"], "delta", a.crs["delta"],
              "| letter gaps:", len(a.letter_gaps), "cited to:", a.citations[:1])
PY
```
Working: prints a policy alert for `demo` with the deterministic CRS (delta 0 — a reclassification
changes the letter bar, not CRS points) and the re-audited **letter gaps cited to the NOC/TEER duty
text**. Swap `classify_update`/`matcher` for the Bedrock clients (step 6 / `MAPLEGUARD_POLICY_URL`)
to run the model extraction for real.

```bash
# 6. the consultant brief — one document to hand a consultant   (LOCAL for the CRS/moves half)
curl -sX POST :8000/brief -H 'Content-Type: application/json' -d "{\"profile\":$PROFILE,\"as_of\":\"2026-08-25\"}"
# with a letter (audit + drafted correction) this needs the model configured (step 7):
# curl -sX POST :8000/brief -d "{\"profile\":$PROFILE,\"noc_code\":\"21234\",\"letter_text\":\"$LETTER\",\"draws\":[...from /draws...]}"
```
Working: returns `{crs, deadlines, next_moves, letter_audit, correction_draft, prose, disclaimer}`.
Every number/citation is a core-tool result; `next_moves` are ranked and dated; with a letter,
`letter_audit.duties.gaps` are cited and `correction_draft` is the drafted letter. `prose` is empty
unless a brief narrator is configured, and any prose that states an eligibility verdict is screened
out. Numbers never come from the prose (a lying narrator's number is ignored).

```bash
# 7. the web dashboard   (LOCAL)
cd web && npm install
echo 'NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000' > .env.local
npm run dev        # http://localhost:3000
```
Working: the dashboard loads, sliders + time-machine recompute instantly (Pyodide), and live
`/draws` / `/dashboard` resolve against the API. The form's submit can call `saveProfile`
(`web/src/lib/api.ts`) to enter the monitored set. No API reachable → it falls back to the bundled
`web/src/data/demo.json` (same shape as `/dashboard`).

---

## AWS — model access, then the stack (CREDS / $)

```bash
# 8. creds + pinned-model access + InvokeModel   (CREDS)
export AWS_REGION=us-east-1
aws sts get-caller-identity
# Enable this exact inference profile in the Bedrock console (Model access -> Claude Sonnet 4.5):
#   us.anthropic.claude-sonnet-4-5-20250929-v1:0   (== agent.config.DEFAULT_BEDROCK_MODEL_ID)
# If yours differs: export MAPLEGUARD_BEDROCK_MODEL=<your enabled inference-profile id>
```
Working: identity resolves and the console shows the model "Access granted". Attach
`bedrock:InvokeModel` + `InvokeModelWithResponseStream` on the inference-profile ARN AND the
per-region foundation-model ARNs — the runtime/API roles both need it (this is the most common
first-invoke failure; the exact policy is in `agentcore-runbook.md` step 1). NOC audit live on
Bedrock ($ small): `cd server && MAPLEGUARD_NOC_BACKEND=bedrock PYTHONPATH=. ../.venv/bin/python
scripts/prove_noc_draft.py` (no `ANTHROPIC_API_KEY` needed — Bedrock uses the AWS creds).

```bash
# 9. stand up the stack: monitor + API Lambda, sharing the profiles table   ($ ~0 idle)
cd infra && make aws-up        # runs `make api-package` (builds the API zip) then terraform apply
make output                    # profiles_table, snapshot_table, monitor_function, api_url, ...
# point the web app at the deployed backend:
#   NEXT_PUBLIC_API_BASE_URL=$(terraform output -raw api_url)
```
Working: `make output` prints `api_url` (the public HTTPS Function URL). Set the web app's
`NEXT_PUBLIC_API_BASE_URL` to it, and a `POST /profiles` there lands in the DynamoDB table the
monitor scans — the loop runs in the cloud with no hand-seeding. To turn on the **deployed policy
watch**, set `MAPLEGUARD_POLICY_URL=<IRCC update page/feed>` on the monitor Lambda: it then fetches
that page, runs the Bedrock classifier + `validate_policy_change`, and re-audits affected letters
each tick (off by default, so the Lambda stays draws-only and dependency-light). Teardown:
`make aws-down` then `terraform state list` is empty. AgentCore Runtime is separate (step 11).

```bash
# 10. the cited corpus: KB dev -> real flip   ($ — KB provisioning + retrieval)
# Provision a Bedrock Knowledge Base over the NOC passages (agentcore-runbook.md step 2), then:
export MAPLEGUARD_MEMORY_BACKEND=bedrock_kb MAPLEGUARD_KB_ID=<kb-id> MAPLEGUARD_KB_REGION=$AWS_REGION
```
Working: with these set, the audit re-sources each NOC gap's citation from live KB retrieval instead
of the seeded dev store — same code path, `cited_via` flips to `corpus_retrieval`. Unset = the
offline seeded corpus. IAM: `bedrock:Retrieve`, `bedrock:GetKnowledgeBase`.

```bash
# 11. host the agent on AgentCore Runtime   ($)
pip install bedrock-agentcore-starter-toolkit
cd server && agentcore configure --entrypoint agent/agentcore_app.py
# set the live backends on the Runtime config so Memory/KB are NOT inert:
#   MAPLEGUARD_MEMORY_BACKEND=bedrock_kb  MAPLEGUARD_KB_ID=<id>          (cited NOC corpus)
#   MAPLEGUARD_SESSION_BACKEND=agentcore  MAPLEGUARD_MEMORY_ID=<id>      (per-user memory)
agentcore launch
agentcore invoke '{"prompt":"Where do I stand? Education bachelors, CLB 9, age 30, 1yr Cdn work.","session_id":"demo-user"}'
```
Working: `invoke` returns JSON where the agent narrates a position computed through the deterministic
tools, gates intact. Confirm the execution role carries the step-8 `bedrock:InvokeModel` policy
first. KB/Memory/Code-Interpreter provisioning + IAM: `agentcore-runbook.md` steps 2–6.

---

## Run the headline demo

The NOC 2016 → TEER 2021 reclassification catching a reference-letter gap, end to end. Local, no AWS
spend (the two model steps stubbed as in step 5; wire Bedrock for the real extraction):

1. **Save a profile with a reference letter** — step 4 (`POST /profiles` with `reference_letter`, or
   `PUT /profiles/demo/letter`). It is now in the monitored store.
2. **Feed the monitor a NOC reclassification update** — step 5: `fetch_policy_update` returns the
   IRCC update text; the classifier extracts `{change_type:"noc", affected_noc_codes:["21234"], ...}`
   and `validate_policy_change` keeps it (drops it if malformed).
3. **The monitor re-audits + alerts** — because NOC 21234 matches the stored letter, `tick` re-audits
   that letter via the real `noc.audit_letter` and emits an alert carrying the deterministic CRS
   position and the **letter gaps cited to the new TEER duty text** (only if the change actually
   creates gaps — relevance still applies).
4. **Assemble the brief** — step 6: `POST /brief` with the profile + `noc_code` + `letter_text`
   returns the CRS position, ranked dated next moves, the cited gaps, and the drafted correction, in
   one document to hand a consultant. Every number is the core's; the prose is screened.

Shortest local path: **1 → 2 → 3 → 4 → 5 → 6 → 7**. Add **step 8's live NOC** on Bedrock and steps
**9–11** for the deployed backend, policy watch, KB, and hosted agent when you want the cloud story
on camera.
