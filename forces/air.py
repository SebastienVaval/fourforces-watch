"""Air: AirNow (area) / PurpleAir (nearby), NHC storms, NWS wind/tropical/air-quality alerts."""
from forces.base import applies_to

FORCE = "air"


def relevant(o, hood, city) -> bool:
    return applies_to(o, hood, city)
