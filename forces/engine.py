"""Rule engine: observations -> worst applicable status per neighborhood per force."""
from __future__ import annotations

from core.schema import FORCES, STATUS_RANK, Observation, worst
from forces import air, fire, land, water
from forces.base import fact

RULES = {"water": water, "air": air, "land": land, "fire": fire}


def board(observations: list[Observation], city: dict) -> list[dict]:
    tiles = []
    for mod in RULES.values():
        if hasattr(mod, "annotate"):
            mod.annotate(observations, city)
    for hood in city.get("neighborhoods", []):
        forces = {}
        for force in FORCES:
            rel = [o for o in observations if o.force == force and RULES[force].relevant(o, hood, city)]
            st = getattr(RULES[force], "status_for", None)
            pairs = [(o, st(o, hood, city) if st else o.status) for o in rel]
            known = [(o, s) for o, s in pairs if s != "unknown"]
            hot = sorted(((o, s) for o, s in known if s in ("watch", "alert")), key=lambda p: -STATUS_RANK[p[1]])
            forces[force] = {"status": worst(s for _, s in known) if known else "unknown", "count": len(rel),
                             "reasons": list(dict.fromkeys(fact(o) for o, _ in hot))[:4],
                             "sources": sorted({o.source for o in rel})}
            if hasattr(RULES[force], "context"):
                forces[force]["context"] = RULES[force].context(hood, observations, city)
        tiles.append({"id": hood["id"], "name": hood["name"], "lat": hood["lat"], "lon": hood["lon"],
                      "zone": hood.get("zone"), "status": worst(f["status"] for f in forces.values()), "forces": forces})
    return tiles
