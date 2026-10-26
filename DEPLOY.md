# Deploying a live demo

The app is one container: FastAPI serves both the API and the static web page, and it refreshes the feeds in a
background loop. Pick a host that runs a long-lived container (serverless/static hosts like Vercel don't keep the
5-minute background refresh running).

Secrets: set `XAI_API_KEY` in the host's secret settings. **Never commit `.env`.**
Recommended for the judging demo: `DEMO_MODE=1`.

## Option A: Hugging Face Spaces (Docker), free
1. Create a new Space, SDK **Docker**, visibility Public.
2. Push this repo to the Space. The Space's README.md must start with the YAML header in
   `deploy/huggingface-space-README.md`: copy that header to the top of README.md in the Space repo.
3. Settings > Variables and secrets: add secret `XAI_API_KEY`, variable `DEMO_MODE=1`.
4. URL: `https://huggingface.co/spaces/<user>/<space>` (the app listens on port 7860).

## Option B: Render, free web service
1. New > Blueprint > select the GitHub repo (it reads `render.yaml`).
2. Enter `XAI_API_KEY` when prompted. The free plan sleeps when idle, so open the URL a minute before the demo.
3. Set `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD`, and `DASHBOARD_SESSION_SECRET` (a long random string).
   All three are required. If any is missing, the login page says sign-in is not configured and no one gets in.
   `GET /healthz` stays open for the Render health check (`healthCheckPath` in `render.yaml`).
4. Error monitoring: set secret `SENTRY_DSN` (Sentry project DSN). The service still boots if it is empty;
   Sentry stays off. Optional: `SENTRY_ENVIRONMENT` (default `production`),
   `SENTRY_TRACES_SAMPLE_RATE` (default `0.1`), and `ADAPTER_TRANSIENT_FAILURES_BEFORE_SENTRY` (default `3`,
   how many refresh cycles a 5xx, 429, timeout, or dropped connection must last before Sentry is notified).
   Other feed errors are reported on the first poll. Leave `SENTRY_DEBUG_ROUTE` unset. Set it to `1` only long
   enough to open `https://<your-service>/sentry-debug`, confirm the error in Sentry, then remove it.

## Option C: anywhere with Docker
```bash
docker build -t fourforces-watch .
docker run -p 8000:7860 -e XAI_API_KEY=... -e DEMO_MODE=1 \
  -e DASHBOARD_USERNAME=... -e DASHBOARD_PASSWORD=... -e DASHBOARD_SESSION_SECRET=... \
  fourforces-watch
```
