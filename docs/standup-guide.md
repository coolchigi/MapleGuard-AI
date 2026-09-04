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
`/brief` need the AI model, so they answer 503 locally. They work against the deployed backend
(see "Run it on AWS"), which has the model turned on.

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
# The letter audit + rewrite parts need the AI model, so run them against the deployed backend:
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

The local run above uses no cloud. This deploys the real backend: the same API and monitor you ran
locally, now hosted on AWS with the AI letter audit turned on.

**First, how you authenticate.** This repo uses **aws-vault**, so your AWS keys are not sitting in
`~/.aws/credentials`. Put `aws-vault exec terraform-dev --no-session --` in front of every `aws`,
`terraform`, and `make` command below, or they fail with "Unable to locate credentials". The
`--no-session` flag avoids a stale cached login. If you are not on aws-vault, set a normal profile
instead (`export AWS_PROFILE=...`) and drop the wrapper.

### 8. Stand up the entire backend (one command)

From the `infra` directory:

```bash
export AWS_REGION=us-east-1
cd infra && aws-vault exec terraform-dev --no-session -- make aws-up
```

That one command does everything: it packages the API into a Lambda zip and creates the whole
backend in AWS. Idle cost is close to zero. What it creates:

- the **API**, a Lambda with a public HTTPS URL,
- the **monitor**, a Lambda that runs itself every 6 hours,
- their shared storage: two DynamoDB tables, an S3 bucket, and an alerts topic.

When it finishes it prints the addresses of what it made:

```
alerts_topic_arn = "arn:aws:sns:us-east-1:337305803512:mapleguard-alerts"
api_url          = "https://24kfuvos2p4l46slfkmiztkozq0imghb.lambda-url.us-east-1.on.aws/"
monitor_function = "mapleguard-monitor"
profiles_table   = "mapleguard-profiles"
schedule         = "rate(6 hours)"
session_bucket   = "mapleguard-sessions-337305803512"
snapshot_table   = "mapleguard-snapshot"
```

The one you need is **`api_url`**: that is your live backend. The rest are the pieces it just
created (the two tables the API and monitor share, the monitor Lambda's name, the S3 bucket, the
alerts topic, and how often the monitor runs). You can reprint this list any time with
`aws-vault exec terraform-dev --no-session -- make output`.

### 9. Confirm it works, and point the web app at it

Check the API is up and the AI audit works (use your own `api_url`):

```bash
API=https://24kfuvos2p4l46slfkmiztkozq0imghb.lambda-url.us-east-1.on.aws
curl -s $API/health        # -> {"status":"ok", ...}
curl -s -X POST $API/audit -H 'Content-Type: application/json' \
  -d '{"noc_code":"21231","letter_text":"Jane Doe worked as a software engineer, wrote and tested code."}'
```
The `/audit` call returns a real Claude-generated audit. The audit uses Claude through Bedrock, and
`make aws-up` already gave the Lambda permission to call it, so there is nothing extra to enable.

Then point the web dashboard at the deployed backend: set `NEXT_PUBLIC_API_BASE_URL` to your
`api_url` in the Vercel project and redeploy. A profile saved through the deployed API lands in the
cloud store the monitor reads, the same loop as local.

To tear the whole backend down: `aws-vault exec terraform-dev --no-session -- make aws-down`.

That is the backend, fully stood up. Everything below is optional and not required for it to run.

---

## Optional extras

Skip this whole section unless you want one of these specific capabilities. The backend from step 8
works without any of them.

### Watch for occupation-rule changes, not just new draws

Out of the box the deployed monitor reacts to new Express Entry draws. To also have it catch
occupation-rule changes (the step-5 behaviour) it needs a page to watch.

**What you do:** in the Lambda console, open the `mapleguard-monitor` function, go to
Configuration -> Environment variables, and add `MAPLEGUARD_POLICY_URL` set to the IRCC update page
you want it to read each run. That is the only action. Leave it unset and the monitor stays
draws-only. Note it calls the AI on every run once set, so it adds a small ongoing cost.

### Cite letter audits from a live source instead of the built-in copy

Today the letter audit cites occupation duties from a copy bundled in the repo, which is accurate
and needs nothing. This option swaps that for citations pulled from a searchable AWS store, a
**Bedrock Knowledge Base**.

There is no Knowledge Base yet. "Where do we get it" means you create one, it is an AWS resource
you provision once:

1. In the Bedrock console: Knowledge Bases -> Create.
2. For the vector store, choose **Amazon S3 Vectors** (available in us-east-1, billed per use). Do
   not pick OpenSearch Serverless, it charges a standing hourly minimum.
3. Point it at the occupation text (the passages the code seeds from `agent.noc_seed_passages()`).
4. Copy the Knowledge Base id it gives you, and set it on the API Lambda:
   `MAPLEGUARD_MEMORY_BACKEND=bedrock_kb`, `MAPLEGUARD_KB_ID=<that id>`, `MAPLEGUARD_KB_REGION=us-east-1`.

With those set, audit citations come from live retrieval. Unset, they come from the built-in copy.
This is a nice-to-have, not part of standing up the backend.

### Redact personal data from stored letters

Reference letters hold names and contact details. To strip that before a letter is saved, create a
**Bedrock Guardrail** with PII redaction (Bedrock console -> Guardrails -> Create -> Sensitive
information filters -> PII: Redact), then set `MAPLEGUARD_GUARDRAIL_ID=<id>` (and optionally
`MAPLEGUARD_GUARDRAIL_VERSION`) on the API Lambda. Once set, a saved letter is scrubbed before it
reaches the database and the save response reports `pii_scrubbed: true`. Unset, letters are stored
as-is and the response says `pii_scrubbed: false`, so the state is always honest.

### Host the conversational agent (AgentCore Runtime)

This hosts the chat agent that answers "where do I stand?" by calling the deterministic tools. It
is a separate deploy from the backend above:

```bash
pip install bedrock-agentcore-starter-toolkit
cd server && aws-vault exec terraform-dev --no-session -- agentcore configure --entrypoint agent/agentcore_app.py
aws-vault exec terraform-dev --no-session -- agentcore launch
aws-vault exec terraform-dev --no-session -- agentcore invoke '{"prompt":"Where do I stand? Education bachelors, CLB 9, age 30, 1yr Cdn work.","session_id":"demo-user"}'
```
Full details (roles, memory, sandbox) are in `agentcore-runbook.md`.

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

Locally that runs end to end with no AWS (the two AI calls are stubbed). Run step 8 to deploy the
same thing on AWS with the real AI audit, and see the optional extras if you want live-sourced
citations, PII redaction, or the hosted chat agent.
