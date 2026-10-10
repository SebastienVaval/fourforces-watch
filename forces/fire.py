"""Fire: heat index (observed + forecast), FIRMS detections nearby, NWS heat/fire alerts."""
from forces.base import applies_to

FORCE = "fire"


def relevant(o, hood, city) -> bool:
    return applies_to(o, hood, city)
