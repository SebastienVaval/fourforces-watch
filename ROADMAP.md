# FourForces Watch: public roadmap

FourForces Watch is an open, MIT-licensed civic hazard framework covering water, air, land and fire:
- **L0:** adapters;
- **L1:** force rules;
- **L2:** city packs;
- **L3:** open API and dashboard.

Every phase is a set of numbered **milestones**. Each milestone has deliverables, exit criteria ("done when…"), a
target date and a status. A status is **Done** only when it has been verified. Statuses: **Done** · **In progress** · **Planned**.
Day-to-day tracking is in [DELIVERY.md](DELIVERY.md), and each delivery row links back to a milestone here.

## Phase 0: Hackathon build (Sat Oct 10, 2026; build 11:00 AM–3:30 PM ET)

| # | Milestone | Deliverables | Done when… | Target | Status |
|---|---|---|---|---|---|
| **M0.1** | L0–L3 for Miami-Dade | 4-force adapters, force rules, `cities/miami.yaml`, JSON / GeoJSON / CAP 1.2 API, Leaflet map, Hazard Board (EN/ES/HT), Status tab | `pytest` passes; all endpoints return live data; map and board render in a browser | Oct 10, 1:00 PM | **Done** (verified 11:20 AM: 389 cameras, tide, 61 gauges, NWS alerts, 10 tiles) |
| **M0.2** | Grok AI layer | xAI vision flood check, Grok trilingual messages, graceful no-key fallback | unit tests pass; with no key the app runs (cameras "not checked", templates); with a key a camera is classified | Oct 10, 2:00 PM | **In progress**: code + tests done, fallback verified; a live run needs `XAI_API_KEY` |
| **M0.3** | Dry-day demo | `DEMO_MODE=1` with labelled CC0 2016 Miami photos, `docs/DEMO.md` script, ~2 min backup video | demo runs end to end; video recorded (1280×720, captions, simulated cameras labelled) | Oct 10, 2:30 PM | **Done** (video 115 s recorded 11:35 AM) |
| **M0.4** | Development pipeline | `.cursor/rules/fourforces.mdc`, `AGENTS.md`, feature branches, GitHub Actions `pytest` | rules + AGENTS.md committed; branches exist; workflow file committed (green run once on GitHub) | Oct 10, 12:00 PM | **Done** (verified 11:58 AM: CI green on GitHub main) |
| **M0.5** | Public repository | public GitHub repo (MIT), all branches pushed, no secrets | repo is public and browsable; `.env` absent; README renders | Oct 10, 12:30 PM | **Done** (verified 11:50 AM: public, MIT, all branches, no `.env`) |
| **M0.6** | Live demo link | deployed instance with `DEMO_MODE=1`, no key needed | public URL loads the map, board and `/api/status` | Oct 10, 3:00 PM | **Planned**: Vercel serverless not a fit as-is; deploy the container on Render or an HF Space (DEPLOY.md) |
| **M0.7** | Submission | project page: description, repo, live link, video, track 04 Data to Action | submitted before the shortlist (~4:00 PM ET); hard deadline 4:30 PM ET | Oct 10, 4:00 PM | **Planned** |

**Phase 0 gate:** M0.1, M0.3, M0.5, M0.6 and M0.7 are Done.

## Phase 1: Cleanup and a second city → v0.2 (Oct 12–23)

| # | Milestone | Deliverables | Done when… | Target | Status |
|---|---|---|---|---|---|
| **M1.1** | Offline test suite | recorded fixtures for every adapter, contract tests, lint + type checks in CI | CI is green with no network access; coverage of every adapter's parser | Oct 16 | Planned |
| **M1.2** | Better camera checks | skip offline/placeholder frames, night handling, small labelled evaluation set | a precision/recall figure is published in the README for the evaluation set | Oct 20 | Planned |
| **M1.3** | Second city pack | `cities/fort_lauderdale.yaml` (FL511 + NOAA + USGS) **or** `cities/montreal.yaml` (+ a camera adapter and Canadian alert/hydrometric adapters) | `CITY=<new>` runs with no code change beyond at most one new adapter | Oct 22 | Planned |
| **M1.4** | Adapter guide + schema | "Write an adapter in 30 minutes" doc; versioned JSON Schema for Observation | an outside contributor can add an adapter by following the doc alone | Oct 23 | Planned |
| **M1.5** | Release v0.2 | tag `v0.2.0`, changelog | tag published; demo updated | Oct 23 | Planned |

**Phase 1 gate:** M1.1, M1.3 and M1.5 are Done.

## Phase 2: Community adapters and extension API (Month 1, Oct 26 – Nov 20)

| # | Milestone | Deliverables | Done when… | Target | Status |
|---|---|---|---|---|---|
| **M2.1** | Installable adapter packages | `ADAPTER_PACKAGES` discovery documented, template adapter repo, registry page | one adapter installed from a separate package with no change to core | Nov 6 | Planned |
| **M2.2** | Extension API v1 | `/v1/...` versioned read API, pagination, `since=` filters, Server-Sent Events/webhooks for status changes, API keys + rate limits | third-party layers consume `/v1` without forking; deprecation policy published | Nov 20 | Planned |
| **M2.3** | Accessibility + languages | WCAG pass, low-bandwidth page, languages configurable per city pack | an accessibility audit has no blocking issues | Nov 20 | Planned |

**Phase 2 gate:** at least 2 external adapters or API consumers; `/v1` is stable.

## Phase 3: Municipal pilot outreach (Months 2–3, Dec – Jan)

| # | Milestone | Deliverables | Done when… | Target | Status |
|---|---|---|---|---|---|
| **M3.1** | Pilot outreach | briefing for Miami-Dade County and City of Miami Beach (emergency management, resilience, open data) | written letter of interest or pilot agreement | Jan 15, 2027 | Planned |
| **M3.2** | CAP integration | CAP 1.2 feed validated against the schema and by at least one alert aggregator / consumer | a consumer ingests the feed in a test environment | Jan 31, 2027 | Planned |
| **M3.3** | Responsible-AI pack | model card for the camera check, privacy/retention note (no imagery stored), limitations | published in the repo and reviewed by the pilot partner | Jan 31, 2027 | Planned |

**Phase 3 gate:** M3.1 and M3.2 are Done.

## Phase 4: More cities via the template (2027+)

| # | Milestone | Deliverables | Done when… | Target | Status |
|---|---|---|---|---|---|
| **M4.1** | City contribution process | PR checklist for city packs (feeds, thresholds, neighborhoods, languages) | 3 or more community city packs merged | Q2 2027 | Planned |
| **M4.2** | Pluggable AI provider | provider interface (hosted APIs or self-hosted models) | two providers pass the same evaluation set | Q2 2027 | Planned |
| **M4.3** | History + analytics | archive of statuses, flood frequency per camera, tide correlations | a public dataset is published with documentation | Q3 2027 | Planned |

## Principles
- Open by default: MIT code, public feeds, open standards (GeoJSON, CAP 1.2).
- Not an official warning system: it points people to official sources and never issues orders.
- No storage of third-party camera imagery; simulated data is always labelled.
