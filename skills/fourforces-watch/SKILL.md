---
name: fourforces-watch
description: Query a FourForces Watch server for live civic hazard conditions (flooding seen on traffic cameras, tide level, canal gauges, NWS alerts, tropical storms, heat index, air quality, evacuation zones) by neighborhood or by force (water, air, land, fire). Use when a user asks whether a Miami-Dade neighborhood or road is flooding, what hazards are active right now, or wants GeoJSON / CAP 1.2 hazard data.
license: MIT
compatibility: Needs network access to a running FourForces Watch server (default http://localhost:8000, override with FFW_URL). Python 3.9+ standard library only.
metadata:
  project: fourforces-watch
  version: "0.1"
---

# FourForces Watch skill

FourForces Watch merges public feeds into one Observation schema:
`{force, source, place{id,name,lat,lon}, time, measurement, value, unit, threshold, status, extra}`,
where `status` is `ok | watch | alert | unknown`.

## Steps

1. Pick the base URL: `FFW_URL` env var, else `http://localhost:8000`.
2. Run the helper with the question type:
   - Neighborhood summary: `python scripts/query.py board [neighborhood-name]`
   - Everything currently at watch/alert: `python scripts/query.py hot [water|air|land|fire]`
   - Cameras where Grok saw water: `python scripts/query.py flooded-cameras`
   - Tide: `python scripts/query.py tide`
3. Answer in plain language. Always:
   - say which sources the answer comes from;
   - mention the observation time;
   - say if an item is marked `extra.simulated` (demo image, not real);
   - remind the user it is not an official warning system: follow NWS and county emergency management.

## Raw endpoints

| Endpoint | Use |
|---|---|
| `GET /api/board` | neighborhood tiles: 4 force statuses, reasons, EN/ES/HT message |
| `GET /api/observations?force=&status=watch,alert` | filtered observations |
| `GET /api/cameras?status=alert` | cameras with water on road |
| `GET /api/tide` | water level, anomaly vs forecast, projected next high |
| `GET /api/geojson` | GeoJSON for GIS tools |
| `GET /api/cap` | OASIS CAP 1.2 XML for alerting systems |
| `GET /api/status` | feed health / missing keys |

## Edge cases
- The server requires a signed-in session. Unauthenticated `/api/*` calls return 401. `GET /healthz` stays open. `scripts/query.py` does not sign in.
- `status: unknown` on a camera means it was not checked yet (or no xAI key). It does **not** mean dry.
- Evacuation order flags from the county layer are shown as `watch` with "confirm with official channels". Never present them as an order.
