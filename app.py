"""FourForces Watch - open civic hazard map (water, air, land, fire).

Run:  uvicorn app:app --port 8000   (see README)
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from adapters.base import SkipAdapter, discover  # noqa: E402
from core import arcgis  # noqa: E402
from core.city import load_city  # noqa: E402
from core.http import client  # noqa: E402
from core.schema import FORCES, Observation, to_cap, to_geojson, utcnow_iso  # noqa: E402
from demo import demo_mode  # noqa: E402
from detect import grok, messages  # noqa: E402
from forces.engine import board as build_board  # noqa: E402

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("app")
ROOT = Path(__file__).resolve().parent
REFRESH = int(os.getenv("REFRESH_SECONDS", "300"))
MAX_CLASSIFY = int(os.getenv("MAX_CLASSIFY", "12"))


class State:
    def __init__(self):
        self.lock = threading.RLock()
        self.city = load_city()
        self.adapters = discover([p.strip() for p in os.getenv("ADAPTER_PACKAGES", "").split(",") if p.strip()])
        self.obs: dict[str, list[Observation]] = {}
        self.adapter_status: dict[str, dict] = {}
        self.detections: dict[str, dict] = {}  # camera place.id -> last Grok result
        self.rotation = 0
        self.board: list[dict] = []
        self.last_refresh: str | None = None
        self.refreshing = False

    def all_obs(self) -> list[Observation]:
        with self.lock:
            return [o for lst in self.obs.values() for o in lst]

    def cameras(self) -> list[Observation]:
        with self.lock:
            return list(self.obs.get("fl511_cameras", []))


S = State()


# ------------------------------------------------------------------ refresh
def _run_adapter(mod):
    t0 = time.time()
    try:
        res = mod.fetch(S.city)
        return mod, res, {"ok": True, "count": len(res), "ms": int((time.time() - t0) * 1000)}
    except SkipAdapter as e:
        return mod, [], {"ok": False, "skipped": str(e)}
    except Exception as e:  # one bad feed never takes the app down
        log.warning("adapter %s failed: %s", mod.NAME, e)
        return mod, None, {"ok": False, "error": str(e)[:200]}


def _fetch_image(cam: Observation) -> tuple[bytes, str] | None:
    if cam.extra.get("local_image"):
        p = Path(cam.extra["local_image"])
        return (p.read_bytes(), "image/jpeg") if p.exists() else None
    try:  # transient, in memory only: FL511 snapshots are never written to disk
        with client(timeout=15) as c:
            r = c.get(cam.extra["image_url"])
        if r.status_code != 200 or len(r.content) < 2000:
            return None
        cam.extra["image_last_modified"] = r.headers.get("last-modified")
        return r.content, r.headers.get("content-type", "image/jpeg").split(";")[0]
    except Exception as e:
        log.info("snapshot fetch failed %s: %s", cam.place.id, e)
        return None


def _apply_detection(cam: Observation):
    d = S.detections.get(cam.place.id)
    # a result for a simulated image must never stick to the real camera (and vice versa)
    if not d or bool(d.get("simulated")) != bool(cam.extra.get("simulated")):
        return
    cam.value = d.get("water_on_road")
    cam.status = grok.status_from(d)
    cam.extra["detection"] = d
    if cam.status in ("watch", "alert"):
        cam.extra["headline"] = ("SIMULATED: " if cam.extra.get("simulated") else "") + \
            f"Water on road seen by camera {cam.place.name}"


def classify_camera(cam: Observation) -> dict:
    img = _fetch_image(cam)
    res = grok.classify_image(*img) if img else \
        {"water_on_road": None, "confidence": None, "note": "snapshot unavailable", "model": None}
    res.update(checked_at=utcnow_iso(), simulated=bool(cam.extra.get("simulated")))
    with S.lock:
        S.detections[cam.place.id] = res
    _apply_detection(cam)
    return res


def refresh():
    if S.refreshing:
        return
    S.refreshing = True
    t0 = time.time()
    try:
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(_run_adapter, S.adapters))
        with S.lock:
            for mod, res, st in results:
                prev = S.adapter_status.get(mod.NAME, {})
                now = utcnow_iso()
                S.adapter_status[mod.NAME] = st | {"name": mod.NAME, "force": mod.FORCE, "last_run": now,
                                                   "last_ok": now if st["ok"] else prev.get("last_ok"),
                                                   "doc": (mod.__doc__ or "").strip().splitlines()[0]}
                if res is not None:
                    S.obs[mod.NAME] = res
        with S.lock:  # simulated hotspots live under their own key, never inside nasa_firms
            S.obs["demo_fire"] = demo_mode.fire_hotspots(S.city) if demo_mode.enabled() else []
        cams = S.cameras()
        demo_cams = demo_mode.apply(cams, S.city) if demo_mode.enabled() else []
        for cam in cams:
            _apply_detection(cam)
        todo = list(demo_cams)  # demo cameras first, then rotate through the rest
        if cams and grok.available():
            rest = [c for c in cams if c not in demo_cams]
            n = max(0, min(MAX_CLASSIFY - len(todo), len(rest)))
            todo += [rest[(S.rotation + i) % len(rest)] for i in range(n)]
            S.rotation = (S.rotation + n) % max(len(rest), 1)
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(classify_camera, todo))
        tiles = build_board(S.all_obs(), S.city)
        for t in tiles:
            statuses = {f: v["status"] for f, v in t["forces"].items()}
            facts = [r for v in t["forces"].values() for r in v["reasons"]]
            ctx = t["forces"]["fire"].get("context") or {}
            if t["forces"]["fire"]["status"] in ("watch", "alert") and ctx.get("cooling_centers"):
                cc = ctx["cooling_centers"][0]
                facts.append(f"Nearest cooling center: {cc['name']} ({cc['km']} km)")
            t["message"] = messages.neighborhood_message(S.city["name"], t["name"], t["status"], statuses, facts)
        with S.lock:
            S.board, S.last_refresh = tiles, utcnow_iso()
        log.info("refresh done in %.1fs: %d observations, %d cameras checked",
                 time.time() - t0, len(S.all_obs()), len(todo))
    except Exception:
        log.exception("refresh failed")
    finally:
        S.refreshing = False


async def _loop():
    while True:
        await asyncio.to_thread(refresh)
        await asyncio.sleep(REFRESH)


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(_loop())
    yield
    task.cancel()


app = FastAPI(title="FourForces Watch", version="0.1.0", lifespan=lifespan,
              description="Open civic hazard map for water, air, land and fire. Public feeds -> one Observation schema.")


def _filter(force=None, status=None, source=None) -> list[Observation]:
    obs = S.all_obs()
    if force:
        obs = [o for o in obs if o.force == force]
    if status:
        wanted = set(status.split(","))
        obs = [o for o in obs if o.status in wanted]
    if source:
        obs = [o for o in obs if o.source == source]
    return obs


# ------------------------------------------------------------------ API
@app.get("/api/status")
def api_status():
    return {"city": {k: S.city.get(k) for k in ("id", "name", "center", "zoom", "bbox")},
            "neighborhoods": S.city.get("neighborhoods", []), "demo_mode": demo_mode.enabled(),
            "ai": {"provider": "xAI API (Grok)", "key_present": grok.available(),
                   "vision_model": grok.vision_model(), "text_model": grok.text_model(),
                   "cameras_checked": sum(1 for d in S.detections.values() if d.get("water_on_road") is not None)},
            "last_refresh": S.last_refresh, "refreshing": S.refreshing, "refresh_seconds": REFRESH,
            "adapters": S.adapter_status, "forces": FORCES,
            "overlays": arcgis.overlay_meta(S.city), "basemap": "mapbox" if _mapbox_token() else "carto/osm"}


def _mapbox_token() -> str:
    """Only public Mapbox tokens (pk.*) are ever sent to the browser."""
    t = os.getenv("MAPBOX_TOKEN", "").strip()
    return t if t.startswith("pk.") else ""


@app.get("/api/config")
def api_config():
    """Front-end config. MAPBOX_TOKEN is a public (pk.) browser token; empty -> OSM/CARTO tiles."""
    return {"mapbox_token": _mapbox_token() or None,
            "mapbox_style": os.getenv("MAPBOX_STYLE", "mapbox/dark-v11"),
            "center": S.city.get("center"), "zoom": S.city.get("zoom"),
            "open_data": {k: arcgis.open_data(S.city).get(k) for k in ("portal", "attribution")}}


@app.get("/api/overlays")
def api_overlays():
    return arcgis.overlay_meta(S.city)


@app.get("/api/overlays/{overlay_id}")
def api_overlay(overlay_id: str):
    try:
        fc = arcgis.overlay_geojson(S.city, overlay_id)
    except Exception as e:
        raise HTTPException(502, f"overlay source failed: {str(e)[:200]}")
    if fc is None:
        raise HTTPException(404, "overlay not found")
    return JSONResponse(fc, media_type="application/geo+json", headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/observations")
def api_observations(force: str | None = Query(None, enum=list(FORCES)), status: str | None = None,
                     source: str | None = None):
    return [o.to_dict() for o in _filter(force, status, source)]


@app.get("/api/cameras")
def api_cameras(status: str | None = None):
    return [o.to_dict() for o in _filter("water", status, "fl511_cameras")]


@app.post("/api/cameras/{cam_id}/check")
def api_check_camera(cam_id: str):
    cam = next((c for c in S.cameras() if c.place.id == cam_id), None)
    if not cam:
        raise HTTPException(404, "camera not found")
    return {"camera": cam.to_dict(), "result": classify_camera(cam)}


@app.get("/api/tide")
def api_tide():
    return [o.to_dict() for o in _filter("water", None, "noaa_tide")]


@app.get("/api/board")
@app.get("/api/hazards")
def api_board():
    return {"generated": S.last_refresh, "demo_mode": demo_mode.enabled(), "tiles": S.board}


@app.get("/api/geojson")
def api_geojson(force: str | None = Query(None, enum=list(FORCES)), status: str | None = None):
    return JSONResponse(to_geojson(_filter(force, status)), media_type="application/geo+json")


@app.get("/api/cap")
def api_cap(force: str | None = Query(None, enum=list(FORCES))):
    xml = to_cap(_filter(force, "watch,alert"), sender=f"fourforces-watch.{S.city['id']}", area_name=S.city["name"])
    return Response(xml, media_type="application/xml")


@app.post("/api/refresh")
def api_refresh():
    threading.Thread(target=refresh, daemon=True).start()
    return {"started": True}


@app.get("/healthz")
def healthz():
    return {"ok": True}


demo_mode.IMG_DIR.mkdir(exist_ok=True)
app.mount("/demo-images", StaticFiles(directory=demo_mode.IMG_DIR), name="demo-images")
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")
