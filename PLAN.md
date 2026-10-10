# PLAN

Working plan for FourForces Watch. Milestone definitions live in [ROADMAP.md](ROADMAP.md) and per-piece status in
[DELIVERY.md](DELIVERY.md); this file is the order of attack. Open items are in [TO-DO.md](TO-DO.md), and project
facts worth keeping are in [MEMORY.md](MEMORY.md).

_Last updated: Sat Oct 10, 2026, 2:30 PM ET._

## Where we are

- `dev` is the integrated app: 17 adapters across four forces, force rules, Miami city pack, JSON / GeoJSON /
  CAP 1.2 API, Leaflet dashboard, Grok vision + trilingual messages, demo mode. New since noon (DELIVERY rows
  28–30): Miami-Dade County Open Data reference sites, six map overlays at `/api/overlays`, optional Mapbox basemap.
  `pytest` passes (13 tests).
- `dev_seb` holds the completed fire force (M0.9, DELIVERY rows 31–34): multi-sensor FIRMS, hotspot distance and
  confidence rule, nearest fire station and cooling centers on the board, Fire view, SIMULATED demo hotspot. It is
  3 commits ahead of `dev` and **not merged yet**.
- `main` is behind: `dev` is 6 commits ahead of it. `main` catches up at the 3:45 PM freeze (M0.8).
- Phase 0 status: M0.1, M0.3, M0.4, M0.5 **Done** · M0.9 **Done on `dev_seb`** · M0.2 **In progress** (needs a live
  run with `XAI_API_KEY`) · M0.6 (live demo link), M0.8 (freeze) and M0.7 (submission) **Planned**.
- The Phase 0 gate needs M0.6, M0.8 and M0.7. All three are open, so they are the critical path.

## Who is on what

| Person | Now | Next |
|---|---|---|
| Sébastien | Air force (in progress on his side; nothing air-related is pushed to `dev_seb` yet) | Merge `dev_seb` into `dev`; live Grok run (M0.2); video link; submission (M0.7) |
| Enrique | Live deploy (M0.6) | Pull `dev` into `dev_enrique` once fire lands, run tests, sync to `feature/fire`; README live URL; status updates |

Fire was going to be Enrique's next piece. Sébastien has already completed it on `dev_seb`, so Enrique's fire work
is now review and testing of that code rather than a parallel implementation.

## Today: finish Phase 0 (all times ET)

| When | Step | Milestone | Owner | Done when |
|---|---|---|---|---|
| 2:30–3:00 PM | Deploy the container with `DEMO_MODE=1` on Render from branch **`dev`** (not `main`, which lacks the county layers) | M0.6 | Enrique | public URL loads the map, the board and `/api/status` |
| 2:30–3:15 PM | Air force work; merge `dev_seb` (fire, and air if ready) into `dev` | M0.9 | Sébastien | `dev` has the fire force and CI is green |
| 3:00–3:30 PM | Pull `dev` into `dev_enrique`, run `pytest`, redeploy, browser pass (map, overlays, Fire view, Hazard Board in EN/ES/HT, Status tab), one rehearsal of `docs/DEMO.md` | M0.3 | both | script runs in 2 minutes with no surprises |
| 3:30 PM | Build window ends. Recommended cutoff: anything not in `dev` by now waits for v0.2. | — | both | `dev` green |
| 3:45 PM | Freeze: merge `dev` into `main`, tag `v0.1`, point the deploy at `main` | M0.8 | Sébastien | `main` equals `dev`; tag published; CI green on `main` |
| by 4:00 PM | Put the live URL and video link in README; submit the project page (description, repo, live link, video, track 04 Data to Action) | M0.6, M0.7 | both | submitted before the shortlist (hard deadline 4:30 PM) |

**Risks right now**

- The deploy was planned for 1:00 PM and is not up at 2:30 PM. It is the only Phase 0 item with no fallback that
  satisfies the gate; the fallback below only covers the demo itself.
- Air work started after 2:15 PM. If it is not merged and tested by 3:30 PM, ship without it.
- Two people editing TO-DO.md and MEMORY.md on separate branches will produce small merge conflicts; keep edits
  in separate lines and merge often.

**Fallbacks**

- Deploy fails or the free host is asleep: demo from `localhost` with `DEMO_MODE=1`, and submit the backup video.
- No xAI key or the API is down: cameras stay "not checked", the board uses templates; lean on tide, NWS and canal layers.
- Venue Wi-Fi down: backup video.

## Next: Phase 1 → v0.2 (Oct 12–23)

In order, because each one makes the next cheaper:

1. **M1.1 Offline test suite** (Oct 16). Recorded fixtures and parser tests for every adapter, plus lint and type
   checks in CI. Today `tests/test_core.py` and `tests/test_arcgis.py` exist (`tests/test_fire.py` is on `dev_seb`);
   the water, air and land feed parsers are still uncovered.
2. **M1.3 Second city pack** (Oct 22). Fort Lauderdale is the cheap one (same FL511, NOAA and USGS adapters, YAML
   only); Montreal proves the "at most one new adapter" claim. Pick one before Oct 16.
3. **M1.2 Better camera checks** (Oct 20). Skip offline/placeholder frames, handle night, publish precision/recall
   on a small labelled set.
4. **M1.4 Adapter guide + JSON Schema** (Oct 23), then **M1.5 tag `v0.2.0`**.

Hardening to fold into Phase 1 (found while reading the code, not yet on the roadmap):

- `POST /api/cameras/{id}/check` and `POST /api/refresh` are open to anyone. On a public deploy with a key set,
  that is unmetered xAI spend. Add a rate limit or a shared token before a keyed deploy stays up long-term.
- County reference sites get positional ids (`mdc_fire_stations-0`, `-1`, …) because `OBJECTID` is not requested;
  the ids shift if the county reorders rows. Add `OBJECTID` to each layer's `fields`.
- `core/arcgis.layer_observations` drops the error when one county layer fails and another succeeds, so the Status
  tab shows the adapter as healthy. Log it and surface a partial-failure note.
- CAP export wraps alerts in a non-standard `<capFeed>` and has no `<expires>`; M3.2 will need this validated.

## Later

Phases 2–4 are unchanged from ROADMAP.md: installable adapter packages and a versioned `/v1` API (Nov), municipal
pilot outreach and CAP validation (Dec–Jan), more cities and a pluggable AI provider (2027).
