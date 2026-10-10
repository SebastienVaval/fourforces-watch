"""Heat index from the NWS station observation + hourly forecast (api.weather.gov). No key."""
from __future__ import annotations

from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place, to_utc_iso

NAME, FORCE = "nws_heat_index", "fire"


def c_to_f(c):
    return None if c is None else c * 9 / 5 + 32


def heat_index_f(t: float, rh: float) -> float:
    """NWS Rothfusz regression with the standard adjustments."""
    hi = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    if (hi + t) / 2 < 80:
        return hi
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh - 6.83783e-3 * t * t
          - 5.481717e-2 * rh * rh + 1.22874e-3 * t * t * rh + 8.5282e-4 * t * rh * rh - 1.99e-6 * t * t * rh * rh)
    if rh < 13 and 80 <= t <= 112:
        hi -= ((13 - rh) / 4) * ((17 - abs(t - 95)) / 17) ** 0.5
    elif rh > 85 and 80 <= t <= 87:
        hi += ((rh - 85) / 10) * ((87 - t) / 5)
    return hi


def _status(hi, cfg):
    if hi is None:
        return "unknown"
    return "alert" if hi >= cfg["heat_index_alert_f"] else "watch" if hi >= cfg["heat_index_watch_f"] else "ok"


def fetch(city: dict) -> list[Observation]:
    cfg = city.get("fire") or {}
    if not cfg.get("nws_station"):
        raise SkipAdapter("no fire.nws_station in city pack")
    lat, lon = city["nws"]["point"]
    link = f"https://forecast.weather.gov/MapClick.php?lat={lat}&lon={lon}"
    out = []
    with client() as c:
        r = c.get(f"https://api.weather.gov/stations/{cfg['nws_station']}/observations/latest")
        r.raise_for_status()
        j = r.json()
        p = j["properties"]
        t_f = c_to_f((p.get("temperature") or {}).get("value"))
        rh = (p.get("relativeHumidity") or {}).get("value")
        hi = c_to_f((p.get("heatIndex") or {}).get("value"))
        if hi is None and t_f is not None and rh is not None:
            hi = heat_index_f(t_f, rh)
        hi = round(hi) if hi is not None else None
        geo = (j.get("geometry") or {}).get("coordinates") or [lon, lat]
        out.append(Observation(
            force=FORCE, source=NAME,
            place=Place(id=f"nws-{cfg['nws_station']}", name=f"NWS station {cfg['nws_station']}", lat=geo[1], lon=geo[0]),
            time=to_utc_iso(p.get("timestamp")), measurement="heat_index_observed", value=hi, unit="F",
            threshold=cfg["heat_index_watch_f"], status=_status(hi, cfg),
            extra={"scope": "area", "zones": [], "temp_f": round(t_f) if t_f is not None else None,
                   "rh_pct": round(rh) if rh is not None else None,
                   "headline": f"Heat index {hi} F at {cfg['nws_station']}", "link": link},
        ))
        pt = c.get(f"https://api.weather.gov/points/{lat},{lon}")
        if pt.status_code == 200:
            fh = c.get(pt.json()["properties"]["forecastHourly"])
            if fh.status_code == 200:
                best = None
                for per in fh.json()["properties"]["periods"][:12]:
                    tf = per["temperature"] if per.get("temperatureUnit") == "F" else c_to_f(per["temperature"])
                    rhv = (per.get("relativeHumidity") or {}).get("value")
                    if tf is not None and rhv is not None:
                        h = heat_index_f(float(tf), float(rhv))
                        if best is None or h > best[0]:
                            best = (h, per["startTime"])
                if best:
                    hmax = round(best[0])
                    out.append(Observation(
                        force=FORCE, source=NAME, place=Place(id="nws-forecast-hi", name="NWS hourly forecast", lat=lat, lon=lon),
                        time=to_utc_iso(best[1]), measurement="heat_index_forecast_max_12h", value=hmax, unit="F",
                        threshold=cfg["heat_index_watch_f"], status=_status(hmax, cfg),
                        extra={"scope": "area", "zones": [], "observed": False, "peak_time": best[1],
                               "headline": f"Forecast peak heat index {hmax} F around {best[1][11:16]} local", "link": link},
                    ))
    return out
