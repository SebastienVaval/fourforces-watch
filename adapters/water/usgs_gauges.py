"""USGS NWIS instantaneous gauge height for canals/streams in the county. No key."""
from __future__ import annotations

from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place, to_utc_iso

NAME, FORCE = "usgs_gauges", "water"
API = "https://waterservices.usgs.gov/nwis/iv/"


def fetch(city: dict) -> list[Observation]:
    cfg = (city.get("water") or {}).get("usgs")
    if not cfg:
        raise SkipAdapter("no usgs in city pack")
    with client(timeout=30) as c:
        r = c.get(API, params={"format": "json", "countyCd": cfg["county_cd"],
                               "parameterCd": cfg.get("parameter_cd", "00065"), "siteStatus": "active", "period": "PT3H"})
        r.raise_for_status()
        series = r.json()["value"]["timeSeries"]
    rise_lim = cfg.get("rapid_rise_ft_3h", 0.5)
    per_site = cfg.get("site_thresholds") or {}
    out = []
    for ts in series:
        si = ts["sourceInfo"]
        vals = [v for v in ts["values"][0]["value"] if v.get("value") not in (None, "")]
        try:
            last, first = float(vals[-1]["value"]), float(vals[0]["value"])
        except (IndexError, ValueError):
            continue
        if last <= -999:
            continue
        site = si["siteCode"][0]["value"]
        rise = round(last - first, 2)
        status, thr = "ok", f"rise > {rise_lim} ft / 3 h"
        if site in per_site:
            thr = per_site[site]
            status = "alert" if last >= thr.get("alert", 1e9) else "watch" if last >= thr.get("watch", 1e9) else "ok"
        if rise >= rise_lim and status == "ok":
            status = "watch"
        geo = si["geoLocation"]["geogLocation"]
        out.append(Observation(
            force=FORCE, source=NAME,
            place=Place(id=f"usgs-{site}", name=si["siteName"].title(), lat=geo["latitude"], lon=geo["longitude"]),
            time=to_utc_iso(vals[-1]["dateTime"]), measurement="gauge_height", value=last,
            unit=ts["variable"]["unit"]["unitCode"], threshold=thr, status=status,
            extra={"rise_3h_ft": rise, "provisional": "P" in vals[-1].get("qualifiers", []),
                   "link": f"https://waterdata.usgs.gov/monitoring-location/{site}/"},
        ))
    return out
