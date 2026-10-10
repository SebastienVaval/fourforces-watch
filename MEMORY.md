# MEMORY

Facts about this project that are easy to forget and slow to rediscover. Not a changelog (that is git) and not a
status board (that is [DELIVERY.md](DELIVERY.md)). Plan: [PLAN.md](PLAN.md). Open items: [TO-DO.md](TO-DO.md).

_Last updated: Sat Oct 10, 2026, 2:15 PM ET._

## Context

- Built at Hack for Humanity Miami, The LAB Miami, Oct 10, 2026. Track 04 Data to Action (secondary: 01 Four Forces, water).
- Clock (ET): build 11:00 AM–3:30 PM · shortlist ~4:00 PM · hard submission deadline 4:30 PM.
- Team: Sébastien Vaval, Enrique Escobar. Repo: https://github.com/SebastienVaval/fourforces-watch (public, MIT).
- Branches: all work is done on `dev`, not `main`. Personal branches (`dev_seb`) and `feature/*` / `docs/*` branch
  from `dev`, tests run, then merge into `dev`. No force-pushes. `main` stays untouched until the 3:45 PM ET
  submission freeze (M0.8), when `dev` is merged into `main` and tagged `v0.1`; after that, `main` changes only at a
  release tag.

## How the app works

- One process. FastAPI serves the API and the static dashboard, and a background loop refreshes every
  `REFRESH_SECONDS` (default 300). All state is in memory (`State` in `app.py`); a restart starts empty and the
  first refresh takes a few seconds, ~30 s with camera checks.
- Adapters are auto-discovered: any non-underscore module in `adapters/<force>/` with `FORCE` and `fetch`. External
  packages plug in through `ADAPTER_PACKAGES`. A failing adapter keeps its previous observations; a `SkipAdapter`
  clears them.
- Status tab states come from `/api/status`: live, skipped (reason shown), or error.
- The four `nws_*` adapters are thin wrappers over `adapters/nws.py`, which calls api.weather.gov once and caches
  for 120 s. An alert goes to the first force whose keyword matches, in the order water → fire → air → land, so
  "Storm Surge Warning" is water and "Tropical Storm Warning" is air. Unmatched events default to land.
- Board relevance (`forces/base.py`): an observation counts for a neighborhood if it is tagged with that
  neighborhood, or is area-scoped and its zone list is empty or includes the tile's NWS zone, or is a point within
  `nearby_km` (6 km for Miami). Tide readings count only for `coastal_zones`. Open shelters never raise a status.
- A force with no relevant observations is `unknown`, not `ok`. A tile's status is the worst of its four forces.

## Grok (xAI API)

- Vision verdicts are cached by image SHA-256 in `.cache/grok_vision.json` (gitignored). Each refresh checks at most
  `MAX_CLASSIFY` cameras (default 12): demo cameras first, then a rotation through the rest. With 389 cameras a
  full pass takes about 2.7 hours at the default refresh.
- Camera status (`grok.status_from`): `water_on_road` true with confidence ≥ 0.6 is `alert`, below that `watch`;
  false is `ok`; null (no key, no snapshot) is `unknown`.
- Without `XAI_API_KEY` everything else still runs: cameras stay "not checked" and messages come from EN/ES/HT
  templates (`by: template`).
- Model ids come from env (`XAI_VISION_MODEL`, `XAI_TEXT_MODEL`). They have not yet been exercised against the live
  API with a real key; only the request path up to auth has.

## Demo mode

- `DEMO_MODE=1` swaps the camera nearest five neighborhoods (downtown, miami-beach, little-haiti, north-miami,
  key-biscayne) for CC0 photos of 2016 Miami tidal flooding by Wikimedia Commons user B137.
- The photos are downloaded from Wikimedia Commons on first use into `demo/images/` and are never committed. A host
  with no outbound access to Commons gets no simulated cameras, silently.
- Simulated items are labelled in three places: page banner, popup tag, `extra.simulated`. A verdict for a
  simulated image is never applied to the real camera, and the reverse.

## Data rules that must not be broken

- FL511 camera images are © FDOT. They are hot-linked by the browser and read in memory for the AI check. Never
  write them to disk or redistribute them; only the verdict and the hash are cached.
- No secrets in the repo. New env vars go in `.env.example` with empty values.
- Not an official warning system. Evacuation order flags are shown as "confirm with official channels"
  (`trust_orders: false`). Generated messages never issue orders.
- No proprietary, client or vendor-recommendation content; the repo is public.

## Gotchas

- `pytest` is not in `requirements.txt`. Install it separately, as CI does.
- `pytest.ini` sets `pythonpath = .`; without it imports fail in CI. Run `python -m pytest -q`.
- CI and the Dockerfile use Python 3.12. The suite also passes on 3.14 locally.
- Hosting needs a long-lived container (background refresh loop). Serverless and static hosts such as Vercel do not
  fit. The container listens on `PORT`, default 7860.
- Render's free plan sleeps when idle; the first request after a sleep is slow and state is empty.
- Miami tide thresholds in `cities/miami.yaml` are in ft MLLW, converted from NOAA's station datum (MLLW = 10.13 ft
  STND): watch 3.0, minor 3.53, moderate 3.93, major 4.73.
- NWS requires a contact in the User-Agent; set `CONTACT` on any real deployment.
- `POST /api/cameras/{id}/check` and `POST /api/refresh` have no auth or rate limit.
- Miami-Dade County Open Data layers are hosted on `services.arcgis.com/8Pc9XBTAsYuxx9Ny` (public, no key).
  `f=geojson` + `outSR=4326` works on every layer used. The FEMA flood-zone views have `maxRecordCount` 100, so
  `page_size: 100` is set in the YAML and `core/arcgis.py` follows `exceededTransferLimit`. AE is ~2 MB even
  simplified; it is off by default and lazy-loaded.
- County shelter layers (`EvacuationCenter_gdb`, `EvacuationCenterShelters_Open`) return 0 features outside a storm
  activation. That is expected, not a broken feed.
- County point layers are `extra.reference = true`: shown on the map, excluded from the board by
  `forces/base.applies_to`, so a fire station never turns a tile's fire badge from `unknown` to `ok`.
- `MAPBOX_TOKEN` is read from env and sent to the browser via `/api/config` only if it starts with `pk.`. Never put
  the token in a tracked file; on Render it is a `sync: false` secret.
- Fire hotspot status is per tile, not per observation: `forces/fire.status_for` uses distance + confidence from
  `fire.hotspots`. The engine supports optional per-force hooks `status_for`, `annotate` and `context`
  (`forces/engine.py`); forces without them behave as before.
- FIRMS: one request per product (`fire.firms.sources`); the area API returns a header-only CSV when there are no
  fires, and text starting with "Invalid" for a bad key. MODIS confidence is 0-100, VIIRS is l/n/h; both are
  normalised in `adapters/fire/firms.norm_confidence`. Most days Miami-Dade has 0 detections: use the demo hotspot.
- The SIMULATED fire hotspot is stored under `S.obs["demo_fire"]` (source `demo_fire`), never inside `nasa_firms`,
  and is empty when `DEMO_MODE` is off.
- Fire view in the dashboard turns off the non-fire overlays and restores them on exit; the heat-island overlay id is
  hard-coded as `mdc_heat_islands` in `web/app.js`.
