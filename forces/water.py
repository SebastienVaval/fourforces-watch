"""Water: camera checks + gauges nearby, tide gauge for coastal zones, NWS flood alerts."""
from forces.base import applies_to

FORCE = "water"


def relevant(o, hood, city) -> bool:
    if o.extra.get("coastal_only"):
        return hood.get("zone") in set(city.get("coastal_zones") or [])
    return applies_to(o, hood, city)
