# MapleGuard setup + stand-up guide

Get MapleGuard running from a fresh clone, first on your laptop, then on AWS. Deep AWS
provisioning detail (console click-paths, per-service IAM) lives in `agentcore-runbook.md`.
Everything you need to stand the thing up is here.

## What MapleGuard is (read this first, the rest assumes it)

MapleGuard tracks where a person stands in Canada's Express Entry immigration system and warns
them when something changes that actually affects them.

- You give it a **profile**: a candidate's age, education, language scores, and work experience.
  It computes their **CRS score** (the points total IRCC ranks people on) straight from the
  official government tables. That math is plain Python. The AI never makes up a number.
- You can attach a **reference letter**: an employer letter tied to a specific occupation code
  (a **NOC** code). MapleGuard can check that letter against the official duties for that
  occupation and tell you which required duties the letter fails to support.
- Once a profile is saved, an **autonomous monitor** re-checks that person whenever either of two
  things changes, and alerts them only when the change moves their standing:
  1. **A new Express Entry draw.** IRCC publishes rounds with a cutoff score. The monitor sees
     whether a new round changes where the candidate sits.
  2. **A change to the occupation rules.** For example the 2021 NOC reclassification. The monitor
     re-audits the saved reference letter against the new duties and flags any new gaps.

Everything runs off ONE saved-profile store: the save endpoints write to it, the monitor reads
from it. Saving a profile is all it takes to put someone on the watch list.

---

## Run it locally

```bash
# 1. Create the Python environment and install dependencies.
cd agents-for-humans/mapleguard
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r server/requirements.txt pytest
```

```bash
# 2. Sanity check: run the tests. They run fully offline (no AWS, no API keys) and should pass.
cd server && PYTHONPATH=. ../.venv/bin/python -m pytest -q
```

```bash
# 3. Start the API server on http://127.0.0.1:8000
cd server && PYTHONPATH=. ../.venv/bin/python -m uvicorn api.asgi:app --port 8000
```
The `/draws` endpoint reaches out to the public IRCC feed. Everything else is local.

### 4. Save an example candidate onto the watch list

This step puts one candidate into the set the monitor watches. Nothing is being monitored yet,
you are just adding someone to watch.

```bash
# PROFILE = the candidate's details. LETTER = their employer reference letter.
PROFILE='{"education":"bachelors-or-three-year","first_language":{"speaking":9,"listening":9,"reading":9,"writing":9},"date_of_birth":"1996-07-01","canadian_work_years":1}'
LETTER='This confirms Jane Doe worked as a Web Developer, 37.5 hrs/wk at $85,000. She wrote some HTML. Sincerely.'

# Save the profile and its letter in one call, under the id "demo".
# "demo" is just a name we pick so we can look this candidate up again. Any string works.
curl -sS -X POST 127.0.0.1:8000/profiles -H 'Content-Type: application/json' \
  -d "{\"profile\":$PROFILE,\"id\":\"demo\",\"reference_letter\":{\"noc_code\":\"21234\",\"letter_text\":\"$LETTER\"}}"

# Or add / replace the letter on a candidate that already exists:
curl -sS -X PUT 127.0.0.1:8000/profiles/demo/letter -H 'Content-Type: application/json' \
  -d "{\"noc_code\":\"21234\",\"letter_text\":\"$LETTER\"}"

# Read it back. First the watch list (ids only, since the full profiles hold personal data),
# then the full record for "demo".
curl -s 127.0.0.1:8000/profiles            # -> {"profiles":[{"id":"demo"}]}
curl -s 127.0.0.1:8000/profiles/demo       # -> the stored profile + reference letter
```

You should see `{"id":"demo","monitored":true}` from the save. The candidate now lives in the
same store the monitor reads, so it will be re-checked automatically when the data changes. A
badly-formed profile is rejected with a 422. `/audit`, `/draft`, and the letter version of
`/brief` need the AI model, so they answer 503 until you configure one (step 8).

### 5. Watch the monitor catch a rule change

This is the headline behaviour. The monitor reacts to two kinds of change (a new draw, or an
occupation-rule change). This snippet simulates the second: IRCC reclassifies occupation 21234.
The monitor finds the "demo" candidate you saved in step 4 (their letter claims 21234), re-audits
that letter against the occupation's new duties, and prints an alert listing the gaps.

In production the AI reads the change off the live IRCC page. Here we hand it a canned change and
stub the two AI calls, so the whole flow runs with no AWS.

```bash
cd server && PYTHONPATH=. ../.venv/bin/python - <<'PY'
from agent.config import Deployment, build_profile_store
from agent.monitor import tick, MonitorDeps, InMemorySnapshotStore, CollectingAlertSink
from ingest import validate_policy_change

# Read the SAME store the API wrote to in step 4.
store = build_profile_store(Deployment.from_env())

# A validated "occupation 21234 was reclassified" change. In production the AI extracts this from
# the IRCC page and validate_policy_change throws out malformed output; here we build it directly.
change = validate_policy_change(
    {"change_type": "noc", "affected_noc_codes": ["21234"], "effective_date": "2022-11-16",
     "summary": "NOC 2016 -> TEER 2021 reclassification"},
    "https://www.canada.ca/noc-2021-teer-update").to_dict()

deps = MonitorDeps(
    fetch_rounds=lambda: '{"rounds": []}',                 # no new draw this run; the trigger is the rule change
    profiles=store, snapshots=InMemorySnapshotStore(), sink=CollectingAlertSink(),
    fetch_policy_update=lambda: "IRCC reclassifies NOC 21234 to TEER 2021",
    classify_update=lambda text: change,                    # in production: the AI classifier
    matcher=lambda letter, occ: ({}, ""))                   # in production: the AI duty-matcher

r = tick(deps, as_of="2026-08-25")
for a in r.alerts:
    if a.policy_change:
        print("alert for", a.profile_id, "| CRS", a.crs["after"], "delta", a.crs["delta"],
              "| letter gaps:", len(a.letter_gaps), "| cited to:", a.citations[:1])
PY
```

You should see one alert for `demo`. The CRS delta is 0 because a reclassification changes which
duties the letter must cover, not the point total, and the alert lists the letter's gaps against
the new duty text, each with a government citation.

### 6. Get the whole thing as one document

`/brief` bundles a candidate's position, their dated next moves, and (if a letter is attached) the
letter audit and a suggested rewrite, into a single document you could hand to a consultant.

```bash
curl -sS -X POST 127.0.0.1:8000/brief -H 'Content-Type: application/json' -d "{\"profile\":$PROFILE,\"as_of\":\"2026-08-25\"}"
# The letter audit + rewrite parts need the AI model configured (step 8):
# curl -sS -X POST 127.0.0.1:8000/brief -d "{\"profile\":$PROFILE,\"noc_code\":\"21234\",\"letter_text\":\"$LETTER\",\"draws\":[...]}"
```
Every number and citation comes from the deterministic engine. Any AI-written prose that tries to
state an eligibility verdict is stripped out.

### 7. Run the web dashboard

```bash
cd web && npm install
echo 'NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000' > .env.local
npm run dev        # http://localhost:3000
```
The score panel and the time-machine slider recompute instantly in the browser. When the API is
unreachable the page falls back to a bundled sample so it still renders.

The production build is already live at **https://web-coolchigis-projects.vercel.app** (public, no
login). It points at the deployed API. To re-point it, set `NEXT_PUBLIC_API_BASE_URL` in the
Vercel project and redeploy.

---

## Run it on AWS

The local run above uses no cloud and no AI. This section turns on the real pieces: the AI model
that audits letters, and the always-on cloud deployment (the API, the monitor, and their stores).

**First, how you authenticate.** This repo uses **aws-vault**, so your AWS keys are not sitting in
`~/.aws/credentials`. Put `aws-vault exec <profile> --no-session --` in front of every `aws`,
`terraform`, `make`, and `agentcore` command below, or they fail with "Unable to locate
credentials". Two profiles: **terraform-dev** (creates the cloud resources) and **strands-lab**
(Bedrock model calls only). The `--no-session` flag avoids a stale cached login. If you are not on
aws-vault, set a normal profile instead (`export AWS_PROFILE=...`) and drop the wrapper.

### 8. Turn on the AI model (AWS Bedrock)

The letter audit and rewrite call Claude through AWS Bedrock. You enable the model once in the
console, then confirm your identity resolves.

```bash
export AWS_REGION=us-east-1
aws-vault exec terraform-dev --no-session -- aws sts get-caller-identity   # confirms who you are
# In the Bedrock console: Model access -> enable "Claude Sonnet 4.5"
#   model id: us.anthropic.claude-sonnet-4-5-20250929-v1:0
```
The model id above is the one the code expects. If you enable a different one, set
`MAPLEGUARD_BEDROCK_MODEL=<your id>`. The role that calls Bedrock needs `bedrock:InvokeModel` on
that model (the exact policy is in `agentcore-runbook.md`, and a missing grant is the most common
first-call failure). To prove it works end to end:

```bash
cd server && MAPLEGUARD_NOC_BACKEND=bedrock PYTHONPATH=. \
  aws-vault exec strands-lab --no-session -- ../.venv/bin/python scripts/prove_noc_draft.py
```

### 9. Deploy the always-on stack

This creates the cloud version of what you ran locally: the API (as a Lambda with a public URL),
the monitor (a Lambda that runs itself every 6 hours), and their DynamoDB and S3 storage. It costs
almost nothing while idle.

```bash
cd infra && aws-vault exec terraform-dev --no-session -- make aws-up     # builds + deploys everything
aws-vault exec terraform-dev --no-session -- make output                 # prints the resource names + the API URL
```
`make output` gives you `api_url`, the public HTTPS address of the deployed API. Point the web app
at it (set `NEXT_PUBLIC_API_BASE_URL` to that value), and a profile saved through it lands in the
cloud store the monitor reads, exactly like the local flow.

To make the deployed monitor also watch for occupation-rule changes (step 5's behaviour, not just
new draws), set `MAPLEGUARD_POLICY_URL=<IRCC update page>` on the monitor Lambda. That turns on the
AI classifier on every run, so it does add ongoing model cost. It is off by default.

To tear it all down: `aws-vault exec terraform-dev --no-session -- make aws-down`.

### 10. Give the audit real sources (Bedrock Knowledge Base)

By default the letter audit cites occupation duties from a small built-in copy. To cite them from
a live, searchable source instead, put the occupation text in a **Knowledge Base**.

Use **Amazon S3 Vectors** as the store behind it. It is generally available in us-east-1 and bills
per use. Do not use OpenSearch Serverless here, it charges a standing hourly minimum that would eat
a small budget. Create the Knowledge Base in the Bedrock console (Knowledge Bases -> Create ->
choose "S3 vectors"), point it at the occupation passages, then:

```bash
export MAPLEGUARD_MEMORY_BACKEND=bedrock_kb MAPLEGUARD_KB_ID=<kb-id> MAPLEGUARD_KB_REGION=$AWS_REGION
```
With this set, each audit citation comes from live retrieval. Unset, it uses the built-in copy.
(Note: the local aws-cli 2.24.17 is too old to have the `s3vectors` commands, so create the KB in
the console or upgrade the CLI.)

### 10b. Redact personal data from stored letters (Bedrock Guardrails)

Reference letters contain names and contact details. To strip that out before a letter is stored,
create a **Bedrock Guardrail** with PII redaction (Bedrock console -> Guardrails -> Create ->
Sensitive information filters -> PII: Redact), then point the API at it:

```bash
# set on the API Lambda:
#   MAPLEGUARD_GUARDRAIL_ID=<id>   MAPLEGUARD_GUARDRAIL_VERSION=<version or DRAFT>
```
With a guardrail set, a saved letter is scrubbed before it hits the database, and the save response
reports `pii_scrubbed: true` (`/health` shows `pii_guardrail.configured`). With none set, letters
are stored as-is and the response says `pii_scrubbed: false`, so the state is always honest.

### 11. Host the AI agent (AgentCore Runtime)

This hosts the conversational agent (the one that answers "where do I stand?" by calling the
deterministic tools) on AWS.

```bash
pip install bedrock-agentcore-starter-toolkit
cd server && aws-vault exec terraform-dev --no-session -- agentcore configure --entrypoint agent/agentcore_app.py
aws-vault exec terraform-dev --no-session -- agentcore launch
aws-vault exec terraform-dev --no-session -- agentcore invoke '{"prompt":"Where do I stand? Education bachelors, CLB 9, age 30, 1yr Cdn work.","session_id":"demo-user"}'
```
`invoke` returns the agent's answer, with every number computed by the deterministic tools. The
runtime role needs the same `bedrock:InvokeModel` grant from step 8. Knowledge Base, memory, and
sandbox setup are in `agentcore-runbook.md`.

---

## The 60-second demo

The story worth showing: an occupation reclassification quietly breaks someone's reference letter,
and MapleGuard catches it.

1. **Save a candidate with a letter** (step 4). They are now on the watch list.
2. **Feed the monitor the rule change** (step 5). The AI reads that occupation 21234 was
   reclassified.
3. **The monitor re-audits and alerts** (step 5 output). It finds the saved candidate, re-checks
   their letter against the new duties, and reports the gaps with citations.
4. **Hand over the brief** (step 6). One document with the position, the next moves, the letter
   gaps, and the suggested rewrite.

Locally that runs end to end with no AWS (the two AI calls are stubbed). Add steps 8 through 11 for
the live model, the cloud deployment, and the hosted agent.
