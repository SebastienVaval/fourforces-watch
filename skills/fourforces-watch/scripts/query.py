"""Tiny client for a FourForces Watch server (standard library only).

usage: query.py board [name] | hot [force] | flooded-cameras | tide
"""
import json
import os
import sys
import urllib.request

BASE = os.getenv("FFW_URL", "http://localhost:8000").rstrip("/")


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.load(r)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "board"
    arg = argv[2].lower() if len(argv) > 2 else None
    if cmd == "board":
        tiles = get("/api/board")["tiles"]
        if arg:
            tiles = [t for t in tiles if arg in t["name"].lower() or arg == t["id"]]
        out = [{"name": t["name"], "status": t["status"], "forces": {f: v["status"] for f, v in t["forces"].items()},
                "reasons": [r for v in t["forces"].values() for r in v["reasons"]], "message": t.get("message")}
               for t in tiles]
    elif cmd == "hot":
        out = get("/api/observations?status=watch,alert" + (f"&force={arg}" if arg else ""))
    elif cmd == "flooded-cameras":
        out = [{"camera": c["place"]["name"], "lat": c["place"]["lat"], "lon": c["place"]["lon"],
                "status": c["status"], "simulated": c["extra"].get("simulated", False),
                "ai_check": c["extra"].get("detection")} for c in get("/api/cameras?status=watch,alert")]
    elif cmd == "tide":
        out = get("/api/tide")
    else:
        sys.exit(__doc__)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv)
