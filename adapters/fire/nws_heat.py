"""NWS heat/red-flag/fire-weather alerts (api.weather.gov). No key."""
from adapters import nws

NAME, FORCE = "nws_heat_fire_alerts", "fire"


def fetch(city):
    return nws.observations(city, FORCE)
