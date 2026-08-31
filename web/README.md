# MapleGuard — live dashboard

The proof surface. Three editorial "passport" panels over the **real** deterministic CRS engine:

- **Profile** — the input form. Age, education, per-ability CLB for first and second language,
  Canadian and foreign work, spouse detail (revealed only when the partner is actually scored),
  and the additional-factor levers. It computes nothing; it collects a profile and posts it.
- **Position** — the returned CRS out of 1200, the cited "how this number is built" breakdown
  with IRCC category caps, and the COMPUTED · NOT ADJUDICATED stamp.
- **Time machine** — an interactive scrubber you drag across dates. The number falls at each
  real cliff: an age-bracket step-down, or the language-test expiry that drops language points
  and their skill transferability to zero.

Interactive: the time-machine scrubber (drag with mouse/touch, or focus the handle and use
← → / Shift+← → / Home / End). The hero number, the dot on the step line, the delta-from-today
readout, and the highlighted cliff row all track the scrubbed date live.

## Where the numbers come from

Nothing in this app computes a CRS number. Every figure on screen is a value the Python engine
returned, and it arrives one of two ways:

**Live** — `POST /dashboard` on the FastAPI server (`server/api/app.py`). One round trip returns
the whole document: position categories plus the time-machine trajectory and its dated cliffs.

**Offline fallback** — `src/data/demo.json`, for when the server is not running.

These are the *same document*, not two versions of one. `web/scripts/precompute.py` writes
`demo.json` by calling `api.dashboard.build_dashboard` — the exact function behind the endpoint —
so the fallback needs no separate TypeScript type and cannot drift from the live response.
`server/tests/test_dashboard.py` asserts that equality, and fails if `demo.json` goes stale:

```bash
npm run precompute          # cd .. && PYTHONPATH=server python3 web/scripts/precompute.py
```

The app always says which of the two it is showing. A server that *rejects* a profile (a 422 from
`agent/serde.py`) never falls back to demo numbers — that would put someone else's score under
your inputs. It surfaces the reason on the form instead.

## Run locally

The dashboard wants both halves running.

```bash
# 1 — the Python API (from the repo root)
cd server && PYTHONPATH=. uvicorn api.asgi:app --reload      # http://127.0.0.1:8000

# 2 — the web app
cd web && npm install && npm run dev                          # http://localhost:3000
```

Without step 1 the app still runs: it serves the bundled demo document and says so in the bar
under the tabs.

`/audit` and `/draft` need a model configured (`MAPLEGUARD_NOC_BACKEND`, `ANTHROPIC_API_KEY`);
the dashboard does not — it is pure deterministic compute and works with no credentials at all.

### Pointing at a different API

```bash
cp .env.local.example .env.local     # NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Next.js inlines `NEXT_PUBLIC_*` at build time, so restart the dev server after changing it.

## Layout

```
src/
  app/page.tsx              tab shell; owns the profile, renders one of three panels
  components/
    ProfileForm.tsx         the input form; owns the working Profile
    FormControls.tsx        ruled-row field primitives (select, date, toggle, CLB grid)
    PositionPanel.tsx       renders whatever categories the server sent
    TimeMachine.tsx         trajectory chart + scrubber; y-scale derived from the data
    SourceBar.tsx           says where the numbers on screen came from
    atoms.tsx               masthead, cite, stamp, guilloche, MRZ strip
  hooks/useDashboard.ts     fetch / loading / fallback state machine
  lib/api.ts                typed client; classifies failures
  lib/profile.ts            defaults, option lists, validation, request normalisation
  data/types.ts             the wire contract with Python
```

## Deploy to Vercel

Standard Next.js App Router, no exotic config.

1. `npm i -g vercel` (once), then from this `web/` folder: `vercel`
2. Set the Vercel project **Root Directory** to `web` (the repo root is the Python engine).
3. Set `NEXT_PUBLIC_API_BASE_URL` to the deployed API's URL. Without it the build falls back to
   `http://127.0.0.1:8000`, which no visitor can reach — the app will run, but every visitor
   sees the demo document.
4. `vercel --prod` to promote.
