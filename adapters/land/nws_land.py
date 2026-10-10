"""NWS evacuation/civil-emergency/other-land alerts (api.weather.gov). No key."""
from adapters import nws

NAME, FORCE = "nws_land_alerts", "land"


def fetch(city):
    return nws.observations(city, FORCE)
