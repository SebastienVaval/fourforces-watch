# PLAN

Working plan for FourForces Watch. Milestone definitions live in [ROADMAP.md](ROADMAP.md) and per-piece status in
[DELIVERY.md](DELIVERY.md); this file is the order of attack. Open items are in [TO-DO.md](TO-DO.md), and project
facts worth keeping are in [MEMORY.md](MEMORY.md).

_Last updated: Sat Oct 10, 2026, 12:00 PM ET._

## Where we are

- `main` is the integrated app: 15 adapters across four forces, force rules, Miami city pack, JSON / GeoJSON /
  CAP 1.2 API, Leaflet dashboard, Grok vision + trilingual messages, demo mode. `pytest` passes (6 tests) locally and in CI.
- Phase 0 status: M0.1, M0.3, M0.4, M0.5 **Done** · M0.2 **In progress** (needs a live run with `XAI_API_KEY`) ·
  M0.6 (live demo link) and M0.7 (submission) **Planned**.
- The Phase 0 gate needs M0.6 and M0.7. Both are still open, so they are the critical path.

## Today: finish Phase 0 (all times ET)

| When | Step | Milestone | Owner | Done when |
|---|---|---|---|---|
| 12:00–1:00 PM | Deploy the container with `DEMO_MODE=1` on Render (`render.yaml`) or a Hugging Face Space (Dockerfile) | M0.6 | Enrique | public URL loads the map, the board and `/api/status` |
| 12:00–1:00 PM | Live Grok run: set `XAI_API_KEY`, classify one demo camera and one real camera, get one Grok-written message | M0.2 | Sébastien | `/api/status` shows `cameras_checked` > 0 and a board message with `by` other than `template` |
| 1:00–1:30 PM | Put the live URL and video link in README; update ROADMAP and DELIVERY statuses | M0.6 | Enrique | README header has no "pending" placeholders |
| 1:30–2:30 PM | Browser pass on the deployed app (map, layer toggles, camera popup, Hazard Board in EN/ES/HT, Status tab); rehearse `docs/DEMO.md` twice | M0.3 | both | script runs in 2 minutes with no surprises |
| 2:30–3:30 PM | Buffer: fix only what the rehearsal broke. No new features. | — | both | `main` green, deploy matches `main` |
| by 4:00 PM | Submit the project page: description, repo, live link, video, track 04 Data to Action | M0.7 | Sébastien | submitted before the shortlist (hard deadline 4:30 PM) |

**Fallbacks**

- Deploy fails or the free host is asleep: demo from `localhost` with `DEMO_MODE=1`, and submit the backup video.
- No xAI key or the API is down: cameras stay "not checked", the board uses templates; lean on tide, NWS and canal layers.
- Venue Wi-Fi down: backup video.

## Next: Phase 1 → v0.2 (Oct 12–23)

In order, because each one makes the next cheaper:

1. **M1.1 Offline test suite** (Oct 16). Recorded fixtures and parser tests for every adapter, plus lint and type
   checks in CI. Today only `tests/test_core.py` exists and no adapter parser is covered.
2. **M1.3 Second city pack** (Oct 22). Fort Lauderdale is the cheap one (same FL511, NOAA and USGS adapters, YAML
   only); Montreal proves the "at most one new adapter" claim. Pick one before Oct 16.
3. **M1.2 Better camera checks** (Oct 20). Skip offline/placeholder frames, handle night, publish precision/recall
   on a small labelled set.
4. **M1.4 Adapter guide + JSON Schema** (Oct 23), then **M1.5 tag `v0.2.0`**.

Hardening to fold into Phase 1 (found while reading the code, not yet on the roadmap):

- `POST /api/cameras/{id}/check` and `POST /api/refresh` are open to anyone. On a public deploy with a key set,
  that is unmetered xAI spend. Add a rate limit or a shared token before a keyed deploy stays up long-term.
- CAP export wraps alerts in a non-standard `<capFeed>` and has no `<expires>`; M3.2 will need this validated.

## Later

Phases 2–4 are unchanged from ROADMAP.md: installable adapter packages and a versioned `/v1` API (Nov), municipal
pilot outreach and CAP validation (Dec–Jan), more cities and a pluggable AI provider (2027).
