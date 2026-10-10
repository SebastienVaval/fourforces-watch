"""US EPA PM2.5 -> AQI conversion (2024 breakpoints) and status helpers."""

_BP = [(0.0, 9.0, 0, 50), (9.1, 35.4, 51, 100), (35.5, 55.4, 101, 150),
       (55.5, 125.4, 151, 200), (125.5, 225.4, 201, 300), (225.5, 325.4, 301, 500)]


def pm25_to_aqi(c):
    if c is None or c < 0:
        return None
    c = round(c, 1)
    for lo, hi, ilo, ihi in _BP:
        if c <= hi:
            return round((ihi - ilo) / (hi - lo) * (c - lo) + ilo)
    return 500


def category(aqi):
    if aqi is None:
        return "Unknown"
    for lim, name in ((50, "Good"), (100, "Moderate"), (150, "Unhealthy for Sensitive Groups"),
                      (200, "Unhealthy"), (300, "Very Unhealthy")):
        if aqi <= lim:
            return name
    return "Hazardous"


def status(aqi, air_cfg):
    if aqi is None:
        return "unknown"
    return "alert" if aqi >= air_cfg.get("aqi_alert", 151) else "watch" if aqi >= air_cfg.get("aqi_watch", 101) else "ok"
