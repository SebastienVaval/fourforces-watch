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

## Option C: anywhere with Docker
```bash
docker build -t fourforces-watch .
docker run -p 8000:7860 -e XAI_API_KEY=... -e DEMO_MODE=1 fourforces-watch
```
