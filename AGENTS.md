# AGENTS.md: guidance for AI coding agents

This file is for any AI coding agent (Cursor, Grok Build / Grok Bot, others) working in this repository. Cursor
also loads the same rules from `.cursor/rules/fourforces.mdc`.

## Project in one paragraph
FourForces Watch is an open civic hazard framework covering four forces: water, air, land and fire.
- **L0:** adapters turn public feeds into one `Observation` schema.
- **L1:** force rules give each neighborhood an ok / watch / alert status.
- **L2:** city packs (YAML) hold every city-specific value.
- **L3:** a FastAPI app serves JSON, GeoJSON, CAP 1.2 and a Leaflet dashboard.

## Setup and checks
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest -q                                   # must pass before any merge
DEMO_MODE=1 uvicorn app:app --port 8000     # runs without any API key
python -m scripts.check_feeds               # live feed check (network)
```

## Conventions
1. **One adapter per source per force:** `adapters/<force>/<source>.py` exposing `NAME`, `FORCE`, `fetch(city) -> list[Observation]`.
2. **Common schema only:** build `core.schema.Observation`. Times are UTC ISO-8601. `status` is one of ok / watch /
   alert / unknown. Put feed-specific details in `extra`.
3. **City values live in `cities/*.yaml`**, never in adapters. A new city should need a YAML file, and at most one new adapter.
4. **Graceful degradation:** a missing key or config raises `SkipAdapter`. With no `XAI_API_KEY`, the app still runs
   (cameras "not checked", template messages).
5. **No secrets in the repo:** environment variables only. Document new ones in `.env.example` with empty values.
   Never commit `.env`.
6. **Tests required** for new adapters, rules and exports. They run offline (fixtures or monkeypatched HTTP).
7. **Branches:** work on `feature/*` or `docs/*`, run tests, merge to `main`, then deploy. No force-pushes to `main`.
8. **No proprietary content:** no company, client or private-roadmap material, no vendor recommendations. Everything
   here is public and MIT.
9. **Honesty in the UI:** label simulated data; don't present the app as an official warning system.

## Where things are
`core/` schema, city loader, HTTP · `adapters/` L0 · `forces/` L1 · `cities/` L2 · `app.py` + `web/` L3 ·
`detect/` Grok (xAI API) image check and messages · `demo/` dry-day images · `tests/` · `skills/` agent skill ·
`docs/DEMO.md` · `ROADMAP.md` · `DELIVERY.md`.
