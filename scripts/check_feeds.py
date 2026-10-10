"""Run every adapter once and print what is live / skipped / failing.

    python -m scripts.check_feeds
"""
from collections import Counter

from dotenv import load_dotenv

load_dotenv()

from adapters.base import SkipAdapter, discover  # noqa: E402
from core.city import load_city  # noqa: E402


def main():
    city = load_city()
    print(f"City pack: {city['name']}")
    for mod in discover():
        try:
            obs = mod.fetch(city)
            print(f"  LIVE  {mod.FORCE:5} {mod.NAME:24} {len(obs):4} obs  {dict(Counter(o.status for o in obs))}")
        except SkipAdapter as e:
            print(f"  SKIP  {mod.FORCE:5} {mod.NAME:24} {e}")
        except Exception as e:
            print(f"  FAIL  {mod.FORCE:5} {mod.NAME:24} {type(e).__name__}: {str(e)[:120]}")


if __name__ == "__main__":
    main()
