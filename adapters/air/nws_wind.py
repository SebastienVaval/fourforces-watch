"""NWS wind/tropical/tornado/air-quality alerts (api.weather.gov). No key."""
from adapters import nws

NAME, FORCE = "nws_wind_alerts", "air"


def fetch(city):
    return nws.observations(city, FORCE)
