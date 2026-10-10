"""Reference sites from the county open-data portal (ArcGIS Hub): fire stations, cooling centers. No key."""
from core.arcgis import layer_observations

NAME, FORCE = "county_gis_fire", "fire"


def fetch(city: dict):
    return layer_observations(city, FORCE, NAME)
