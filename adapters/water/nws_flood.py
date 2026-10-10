"""NWS flood/coastal-flood/storm-surge alerts (api.weather.gov). No key."""
from adapters import nws

NAME, FORCE = "nws_flood_alerts", "water"


def fetch(city):
    return nws.observations(city, FORCE)
