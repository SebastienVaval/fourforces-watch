"""Reference sites from the county open-data portal (ArcGIS Hub): evacuation bus pickups, hospitals. No key."""
from core.arcgis import layer_observations

NAME, FORCE = "county_gis_land", "land"


def fetch(city: dict):
    return layer_observations(city, FORCE, NAME)
