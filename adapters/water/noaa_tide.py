"""NOAA CO-OPS water level + tide predictions (api.tidesandcurrents.noaa.gov). No key.

Besides the observed level, reports the anomaly vs the astronomical prediction
(storm surge / king-tide excess) and projects the next high tide with it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place

NAME, FORCE = "noaa_tide", "water"
API = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


def _get(c, **params):
    base = {"units": "english", "time_zone": "gmt", "format": "json", "application": "fourforces-watch"}
    r = c.get(API, params={**base, **params})
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"])
    return j


def _parse(t: str) -> datetime:
    return datetime.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def fetch(city: dict) -> list[Observation]:
    cfg = (city.get("water") or {}).get("noaa_tide")
    if not cfg:
        raise SkipAdapter("no noaa_tide in city pack")
    st, datum = cfg["station"], cfg.get("datum", "MLLW")
    now = datetime.now(timezone.utc)
    begin = (now - timedelta(hours=1)).strftime("%Y%m%d %H:%M")
    with client() as c:
        latest = _get(c, station=st, product="water_level", date="latest", datum=datum)
        pred6 = _get(c, station=st, product="predictions", datum=datum, interval="6", begin_date=begin, range=2)
        hilo = _get(c, station=st, product="predictions", datum=datum, interval="hilo", begin_date=begin, range=30)
    return [build(latest, pred6, hilo, cfg, now)]


def build(latest: dict, pred6: dict, hilo: dict, cfg: dict, now: datetime) -> Observation:
    """Pure function (testable offline): NOAA JSON payloads -> one tide Observation."""
    st, datum = cfg["station"], cfg.get("datum", "MLLW")
    meta, row = latest["metadata"], latest["data"][-1]
    t_obs, value = _parse(row["t"]), float(row["v"])
    preds = [(abs((_parse(p["t"]) - t_obs).total_seconds()), float(p["v"])) for p in pred6.get("predictions", [])]
    predicted = min(preds)[1] if preds else None
    anomaly = round(value - predicted, 2) if predicted is not None else 0.0
    p6 = sorted((_parse(p["t"]), float(p["v"])) for p in pred6.get("predictions", []))
    later = [v for t, v in p6 if t >= t_obs + timedelta(minutes=54)]
    trend = None
    if predicted is not None and later:
        trend = "rising" if later[0] > predicted + 0.02 else "falling" if later[0] < predicted - 0.02 else "slack"
    next_high = next((p for p in hilo.get("predictions", []) if p["type"] == "H" and _parse(p["t"]) > now), None)
    projected = round(float(next_high["v"]) + max(anomaly, 0.0), 2) if next_high else None

    minor, watch = cfg.get("minor_flood_ft"), cfg.get("watch_ft", cfg.get("minor_flood_ft"))
    status = "ok"
    if minor is not None and value >= minor:
        status = "alert"
    elif (watch is not None and value >= watch) or (minor is not None and projected is not None and projected >= minor):
        status = "watch"
    level = next((n.split("_")[0] for n in ("major_flood_ft", "moderate_flood_ft", "minor_flood_ft")
                  if cfg.get(n) is not None and value >= cfg[n]), None)
    return Observation(
        force=FORCE, source=NAME,
        place=Place(id=f"noaa-{st}", name=f"{meta['name']} tide gauge (NOAA {st})",
                    lat=float(meta["lat"]), lon=float(meta["lon"])),
        time=_iso(t_obs), measurement="water_level", value=value, unit=f"ft {datum}", threshold=minor, status=status,
        extra={"scope": "area", "coastal_only": True, "predicted": predicted, "anomaly_ft": anomaly, "trend": trend,
               "flood_level": level,
               "thresholds": {k: cfg.get(k) for k in ("watch_ft", "minor_flood_ft", "moderate_flood_ft", "major_flood_ft")},
               "next_high": {"time": _iso(_parse(next_high["t"])), "predicted_ft": float(next_high["v"]),
                             "projected_ft": projected} if next_high else None,
               "tides": [{"time": _iso(_parse(p["t"])), "type": p["type"], "ft": float(p["v"])}
                         for p in hilo.get("predictions", [])[:6]],
               "headline": f"Tide {value:.2f} ft {datum} at {meta['name']}"
                           + (f" ({anomaly:+.2f} ft vs forecast)" if predicted is not None else ""),
               "link": f"https://tidesandcurrents.noaa.gov/stationhome.html?id={st}"},
    )
