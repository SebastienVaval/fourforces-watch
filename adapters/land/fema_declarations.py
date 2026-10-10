"""OpenFEMA disaster declarations for the county (fema.gov/api/open). No key."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from adapters.base import SkipAdapter
from core.http import client
from core.schema import Observation, Place, to_utc_iso

NAME, FORCE = "openfema_declarations", "land"
API = "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"


def fetch(city: dict) -> list[Observation]:
    cfg = (city.get("land") or {}).get("fema")
    if not cfg:
        raise SkipAdapter("no fema settings in city pack")
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=cfg.get("lookback_days", 365))).strftime("%Y-%m-%dT00:00:00.000Z")
    flt = f"state eq '{cfg['state']}' and fipsCountyCode eq '{cfg['fips_county']}' and declarationDate ge '{since}'"
    with client(timeout=30) as c:
        r = c.get(API, params={"$filter": flt, "$orderby": "declarationDate desc", "$top": 20,
                               "$select": "disasterNumber,declarationTitle,declarationDate,incidentType,"
                                          "declarationType,incidentBeginDate,incidentEndDate,designatedArea"})
        r.raise_for_status()
        rows = r.json().get("DisasterDeclarationsSummaries", [])
    lat, lon = city["center"]
    out, seen = [], set()
    for row in rows:
        if row["disasterNumber"] in seen:
            continue
        seen.add(row["disasterNumber"])
        end = row.get("incidentEndDate")
        open_ = not end or datetime.fromisoformat(end.replace("Z", "+00:00")) > now - timedelta(days=14)
        out.append(Observation(
            force=FORCE, source=NAME,
            place=Place(id=f"fema-{row['disasterNumber']}", name=row.get("designatedArea") or city["name"], lat=lat, lon=lon),
            time=to_utc_iso(row.get("declarationDate")), measurement=f"FEMA {row.get('declarationType')} declaration",
            value=row.get("incidentType"), threshold="incident open or ended < 14 days ago",
            status="watch" if open_ else "ok",
            extra={"scope": "area", "zones": [],
                   "headline": f"{row.get('declarationTitle')} ({row.get('incidentType')}), FEMA-{row['disasterNumber']}",
                   "incident_end": end, "link": f"https://www.fema.gov/disaster/{row['disasterNumber']}"},
        ))
    return out
