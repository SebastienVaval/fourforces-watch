"""Record a ~100 s demo video of a running FourForces Watch instance.

Needs: pip install playwright ; a Chrome/Chromium binary ; ffmpeg.
    DEMO_MODE=1 uvicorn app:app --port 8000 &
    python -m scripts.record_demo --url http://localhost:8000 --out demo.mp4

Each scene is a 1280x720 screenshot with a caption bar injected into the page,
then ffmpeg turns the stills into an MP4 (H.264, 30 fps).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request

from playwright.sync_api import sync_playwright

CAPTION_JS = """(text) => {
  let el = document.getElementById('__cap');
  if (!el) { el = document.createElement('div'); el.id = '__cap'; document.body.appendChild(el); }
  el.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:99999;background:rgba(2,6,23,.88);color:#fff;'
    + 'font:600 22px system-ui,sans-serif;padding:14px 22px;line-height:1.3;border-top:3px solid #38bdf8';
  el.innerHTML = text;
}"""


def find_chrome():
    for c in (os.getenv("CHROME"), "google-chrome", "chromium", "chromium-browser"):
        if c and shutil.which(c):
            return shutil.which(c)
    return None


def raw(page, base, path):
    """Show a raw API response (JSON or XML) as a readable HTML page so captions can overlay it."""
    import html
    body = urllib.request.urlopen(base + path).read().decode()
    if path.startswith("/api/geojson"):
        body = json.dumps(json.loads(body), indent=2)
    page.set_content(f"<html><body style='margin:0;background:#0f172a;color:#e2e8f0'>"
                     f"<div style='padding:10px 18px;font:600 18px system-ui;color:#38bdf8'>GET {html.escape(path)}</div>"
                     f"<pre style='margin:0;padding:0 18px;font:13px/1.35 monospace;white-space:pre-wrap'>"
                     f"{html.escape(body[:6000])}</pre></body></html>")
    page.wait_for_timeout(500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--out", default="demo.mp4")
    args = ap.parse_args()
    base = args.url.rstrip("/")
    status = json.load(urllib.request.urlopen(base + "/api/status"))
    cams = json.load(urllib.request.urlopen(base + "/api/cameras"))
    sim = [c for c in cams if c["extra"].get("simulated")]
    real = next(c for c in cams if not c["extra"].get("simulated") and "Brickell" not in c["place"]["name"])
    ai_note = ("AI check: Grok via xAI API" if status["ai"]["key_present"]
               else "Recorded WITHOUT an AI key: cameras show 'not checked'; with XAI_API_KEY, Grok classifies them")
    tmp = tempfile.mkdtemp()
    shots: list[tuple[str, float]] = []

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=find_chrome(), args=["--no-sandbox"])
        page = b.new_page(viewport={"width": 1280, "height": 720})
        page.goto(base, wait_until="load")
        page.wait_for_timeout(3500)

        def shot(caption, secs):
            page.evaluate(CAPTION_JS, caption)
            page.wait_for_timeout(600)
            path = os.path.join(tmp, f"{len(shots):02d}.png")
            page.screenshot(path=path)
            shots.append((path, secs))

        def tab(name):
            page.click(f'button.tab[data-tab="{name}"]')
            page.wait_for_timeout(1200)

        shot("<b>FourForces Watch</b>: open civic hazard map for Miami-Dade · water · air · land · fire · MIT license", 8)
        shot("Live public feeds: NWS coastal flood statement + NOAA Virginia Key tide running above forecast "
             "(side panel). 389 FDOT traffic cameras on the map.", 9)
        if sim:
            c = sim[1] if len(sim) > 1 else sim[0]
            page.evaluate("([lat, lon]) => map.setView([lat, lon], 14)", [c["place"]["lat"], c["place"]["lon"]])
            page.wait_for_timeout(2500)
            page.evaluate("(id) => markers[id] && markers[id].openPopup()", c["place"]["id"])
            page.wait_for_timeout(3000)
            shot("<span style='color:#fbbf24'>SIMULATED</span>: cameras with a yellow ring show archived 2016 Miami "
                 "flood photos (CC0, Wikimedia Commons) to demo detection on a dry day. " + ai_note, 12)
        page.evaluate("([lat, lon]) => map.setView([lat, lon], 13)", [real["place"]["lat"], real["place"]["lon"]])
        page.wait_for_timeout(2500)
        page.evaluate("(id) => markers[id] && markers[id].openPopup()", real["place"]["id"])
        page.wait_for_timeout(4000)
        shot("A real FDOT camera: live snapshot (hot-linked, never stored) + tide + active NWS alerts. "
             "'Check now' sends it to the AI check.", 10)
        page.evaluate("() => map.closePopup()")
        page.evaluate("() => map.setView([25.77, -80.25], 10)")
        page.uncheck('input[data-force="water"]')
        page.wait_for_timeout(1500)
        shot("Four forces as layers: canals, storms, evacuation zones, heat index… each from a public feed.", 7)
        page.check('input[data-force="water"]')

        tab("board")
        shot("Hazard Board: 10 neighborhoods × 4 forces (ok / watch / alert) with the reasons behind each status.", 9)
        page.click('button.lang[data-lang="es"]'); page.wait_for_timeout(800)
        shot("Same message in Spanish…", 6)
        page.click('button.lang[data-lang="ht"]'); page.wait_for_timeout(800)
        shot("…and Haitian Creole (Kreyòl). With an xAI key, Grok writes these from the facts; otherwise fixed templates.", 8)

        tab("data")
        shot("Open data: one Observation schema → JSON, GeoJSON and CAP 1.2 (the emergency-alert standard).", 7)
        raw(page, base, "/api/geojson?force=water")
        shot("/api/geojson: drop it into any GIS tool.", 7)
        raw(page, base, "/api/cap")
        shot("/api/cap: watch/alert items as OASIS CAP 1.2 for alerting systems.", 7)
        page.goto(base, wait_until="load"); page.wait_for_timeout(3000)
        tab("status")
        shot("Status: live health of every feed (last fetch, last success, items, errors). "
             "Feeds needing a key skip gracefully.", 9)
        tab("map")
        shot("Reuse in your city with one YAML file · github: fourforces-watch · Not an official warning system: "
             "follow NWS and county emergency management.", 8)
        b.close()

    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w") as f:
        for path, secs in shots:
            f.write(f"file '{path}'\nduration {secs}\n")
        f.write(f"file '{shots[-1][0]}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-vf", "scale=1280:720,fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "medium",
                    "-crf", "23", "-movflags", "+faststart", args.out], check=True)
    print(f"wrote {args.out} ({sum(s for _, s in shots):.0f} s, {len(shots)} scenes)")


if __name__ == "__main__":
    main()
