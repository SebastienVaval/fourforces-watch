"""US EPA PM2.5 -> AQI (2024 breakpoints), EPA PurpleAir correction, category and status helpers."""
import math

# EPA PM2.5 NAAQS update, effective May 6, 2024 (24-h breakpoints, ug/m3)
_BP = [(0.0, 9.0, 0, 50), (9.1, 35.4, 51, 100), (35.5, 55.4, 101, 150),
       (55.5, 125.4, 151, 200), (125.5, 225.4, 201, 300), (225.5, 325.4, 301, 500)]
CATEGORIES = [(50, "Good"), (100, "Moderate"), (150, "Unhealthy for Sensitive Groups"),
              (200, "Unhealthy"), (300, "Very Unhealthy"), (10_000, "Hazardous")]


def pm25_to_aqi(c):
    if c is None or c < 0:
        return None
    c = math.floor(c * 10 + 1e-9) / 10  # EPA truncates to one decimal
    for lo, hi, ilo, ihi in _BP:
        if c <= hi:
            return round((ihi - ilo) / (hi - lo) * (max(c, lo) - lo) + ilo)
    return 500


def epa_correct(pm_cf1, rh):
    """US EPA nationwide PurpleAir correction (Barkjohn et al. 2021), valid for PA cf_1 <= 343 ug/m3:
    PM2.5 = 0.524 * PA_cf1 - 0.0862 * RH + 5.75. Returns None if an input is missing."""
    if pm_cf1 is None or rh is None:
        return None
    if pm_cf1 > 343:  # EPA 2022 extension for smoke-level concentrations
        return round(2.966 + 0.69 * pm_cf1 + 8.84e-4 * pm_cf1 ** 2, 1)
    return round(max(0.0, 0.524 * pm_cf1 - 0.0862 * rh + 5.75), 1)


def category(aqi):
    if aqi is None:
        return "Unknown"
    return next(name for lim, name in CATEGORIES if aqi <= lim)


def status(aqi, air_cfg):
    if aqi is None:
        return "unknown"
    return "alert" if aqi >= air_cfg.get("aqi_alert", 151) else "watch" if aqi >= air_cfg.get("aqi_watch", 101) else "ok"
