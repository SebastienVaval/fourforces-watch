# TO-DO

Open items only. Finished work is recorded in [DELIVERY.md](DELIVERY.md). Order and timing are in [PLAN.md](PLAN.md).

_Last updated: Sat Oct 10, 2026, 1:40 PM ET._

## Now: before the 4:00 PM ET shortlist (hard deadline 4:30 PM)

Branch rule: work on `dev_seb` / `dev_enrique` and merge into `dev`. `dev` is merged into `main` and tagged `v0.1` at the 3:45 PM freeze (M0.8).

- [ ] **Next quick win: deploy the live demo on Render** (M0.6, Enrique; roadmap target 3:00 PM). Needs no API
      key, takes about 10 minutes, and unblocks the README link, the 3:45 PM freeze (M0.8) and the submission.
  - [ ] Go to render.com and sign in with GitHub.
  - [ ] New ÔåÆ Web Service ÔåÆ Public Git Repository, paste `https://github.com/SebastienVaval/fourforces-watch`.
        The repo is S├®bastien's, so the Blueprint route (`render.yaml`) would need him to grant Render access;
        the public-URL route should not.
  - [ ] Set branch `main`, runtime Docker, plan Free, health check path `/healthz`.
  - [ ] Add environment variables `CITY=miami` and `DEMO_MODE=1`. Leave `XAI_API_KEY` out for now; the app runs
        without it (cameras show "not checked", the board uses template messages).
  - [ ] Deploy, then open the URL and check: map loads, orange SIMULATED banner shows, 5 demo cameras present,
        Hazard Board has 10 tiles, `/api/status` and `/healthz` respond. The host must reach Wikimedia Commons
        to fetch the demo images.
  - [ ] Later, if S├®bastien has a key: add `XAI_API_KEY` as a Render secret (never in the repo). Grok checks
        switch on at the next restart.
  - [ ] Fallback if Render does not work: HF Space with the header from `deploy/huggingface-space-README.md`.
- [x] Miami-Dade County Open Data layers + overlays and Mapbox basemap (DELIVERY rows 28–30), on `dev_seb`.
- [ ] Render: add `MAPBOX_TOKEN` (public pk. token) and `FIRMS_MAP_KEY` as secret env vars (both `sync: false` in
      `render.yaml`). Without `MAPBOX_TOKEN` the map falls back to OSM/CARTO tiles.
- [ ] Demo: open the map's layer control (top left) and show the evacuation zones + FEMA VE overlays with a camera.
- [ ] **Live Grok run** (M0.2, S├®bastien): with `XAI_API_KEY` set, confirm a camera is classified and a board
      message is Grok-written. Confirm the default model ids in `.env.example` are accepted by the API.
- [ ] Upload the 115 s demo video (unlisted YouTube or Drive) and get a shareable link (Sébastien).
- [ ] Fallback if the deploy is not up by about 1:30 PM: demo from `localhost` with `DEMO_MODE=1` and use the video. Do not block the rehearsal.
- [ ] Once the URL exists: add it and the video link to the README header (both are placeholders now), on `dev_enrique`.
- [ ] Update ROADMAP.md (M0.2, M0.6), DELIVERY.md (rows 7, 9, 18, 21) and this file once the above are verified.
- [ ] Visual check in a browser: layer toggles, camera popup + "Check now with Grok", Hazard Board in EN/ES/HT,
      Status tab (DELIVERY row 14 still says to do this).
- [ ] Rehearse `docs/DEMO.md` twice. Re-check its live hooks first: the NWS Coastal Flood Statement and the tide
      figures are from this morning and may have changed.
- [ ] If on Render free tier, open the URL a minute before presenting (it sleeps when idle).
- [ ] **Submit** on OrganizerHQ (M0.7, S├®bastien): description, repo, live link, video, track 04 Data to Action.

## Housekeeping (small, any time)

- [ ] README pipeline diagram lists Vercel as a deploy target, but DEPLOY.md and ROADMAP say Vercel does not fit.
      Drop it from the diagram.
- [ ] Feature branches (`feature/*`, `docs/roadmap`, `chore/dev-pipeline`) are 3 commits behind `main`. Sync or
      delete them after the event.
- [ ] Optional keys still unset on deploys, so adapters skip: `AIRNOW_API_KEY`, `PURPLEAIR_API_KEY` (DELIVERY row 3).
      `FIRMS_MAP_KEY` now exists locally (Sébastien's `.env`); add it as a Render secret too (DELIVERY row 6).
- [ ] README says `pip install pytest` separately; either add a `requirements-dev.txt` or keep it and say so in AGENTS.md.

## Phase 1 (Oct 12ÔÇô23)

- [ ] M1.1: fixtures + parser tests for each of the 15 adapters (monkeypatched HTTP); add ruff and a type check to CI.
- [ ] M1.1: API tests with FastAPI `TestClient` for `/api/observations`, `/api/geojson`, `/api/cap`, `/api/board`.
- [ ] Protect `POST /api/cameras/{id}/check` and `POST /api/refresh` (rate limit or token) before a keyed public deploy.
- [ ] M1.3: decide Fort Lauderdale vs Montreal by Oct 16, then write the city pack.
- [ ] M1.2: detect offline/placeholder and night frames before sending to Grok; build a small labelled set; publish precision/recall.
- [ ] M1.4: "Write an adapter in 30 minutes" doc; versioned JSON Schema for `Observation`.
- [ ] CAP: validate output against the CAP 1.2 schema; add `<expires>`; decide on the `<capFeed>` wrapper (feeds M3.2).
- [ ] M1.5: changelog, tag `v0.2.0`.
