# TO-DO

Open items only. Finished work is recorded in [DELIVERY.md](DELIVERY.md). Order and timing are in [PLAN.md](PLAN.md).

_Last updated: Sat Oct 10, 2026, 12:00 PM ET._

## Now: before the 4:00 PM ET shortlist (hard deadline 4:30 PM)

- [ ] **Deploy the live demo** (M0.6, Enrique). Render Blueprint from `render.yaml`, or HF Space with the header
      from `deploy/huggingface-space-README.md`. `DEMO_MODE=1`; `XAI_API_KEY` as a host secret, never in the repo.
- [ ] Check the deployed URL: map loads, SIMULATED banner shows, 5 demo cameras present, board has 10 tiles,
      `/api/status` and `/healthz` respond. The host must reach Wikimedia Commons to fetch the demo images.
- [ ] **Live Grok run** (M0.2, Sébastien): with `XAI_API_KEY` set, confirm a camera is classified and a board
      message is Grok-written. Confirm the default model ids in `.env.example` are accepted by the API.
- [ ] Add the live URL and the video link to the README header (both are placeholders now).
- [ ] Update ROADMAP.md (M0.2, M0.6) and DELIVERY.md (rows 7, 9, 18, 21) once the above are verified.
- [ ] Visual check in a browser: layer toggles, camera popup + "Check now with Grok", Hazard Board in EN/ES/HT,
      Status tab (DELIVERY row 14 still says to do this).
- [ ] Rehearse `docs/DEMO.md` twice. Re-check its live hooks first: the NWS Coastal Flood Statement and the tide
      figures are from this morning and may have changed.
- [ ] If on Render free tier, open the URL a minute before presenting (it sleeps when idle).
- [ ] **Submit** on OrganizerHQ (M0.7, Sébastien): description, repo, live link, video, track 04 Data to Action.

## Housekeeping (small, any time)

- [ ] README pipeline diagram lists Vercel as a deploy target, but DEPLOY.md and ROADMAP say Vercel does not fit.
      Drop it from the diagram.
- [ ] Feature branches (`feature/*`, `docs/roadmap`, `chore/dev-pipeline`) are 3 commits behind `main`. Sync or
      delete them after the event.
- [ ] `dev` is 1 commit ahead of `main` (the PLAN / TO-DO / MEMORY files). Merge once these are reviewed.
- [ ] Optional keys still unset, so three adapters skip: `AIRNOW_API_KEY`, `PURPLEAIR_API_KEY`, `FIRMS_MAP_KEY`
      (DELIVERY rows 3 and 6, Enrique). All are free to request.
- [ ] README says `pip install pytest` separately; either add a `requirements-dev.txt` or keep it and say so in AGENTS.md.

## Phase 1 (Oct 12–23)

- [ ] M1.1: fixtures + parser tests for each of the 15 adapters (monkeypatched HTTP); add ruff and a type check to CI.
- [ ] M1.1: API tests with FastAPI `TestClient` for `/api/observations`, `/api/geojson`, `/api/cap`, `/api/board`.
- [ ] Protect `POST /api/cameras/{id}/check` and `POST /api/refresh` (rate limit or token) before a keyed public deploy.
- [ ] M1.3: decide Fort Lauderdale vs Montreal by Oct 16, then write the city pack.
- [ ] M1.2: detect offline/placeholder and night frames before sending to Grok; build a small labelled set; publish precision/recall.
- [ ] M1.4: "Write an adapter in 30 minutes" doc; versioned JSON Schema for `Observation`.
- [ ] CAP: validate output against the CAP 1.2 schema; add `<expires>`; decide on the `<capFeed>` wrapper (feeds M3.2).
- [ ] M1.5: changelog, tag `v0.2.0`.
