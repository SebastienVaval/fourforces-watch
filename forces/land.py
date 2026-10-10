"""Land: the tile's evacuation zone/order flag, FEMA declarations, earthquakes, NWS land alerts."""
from forces.base import applies_to

FORCE = "land"


def relevant(o, hood, city) -> bool:
    if o.source == "evac_shelters":  # open shelters are information, not a hazard
        return False
    return applies_to(o, hood, city)
