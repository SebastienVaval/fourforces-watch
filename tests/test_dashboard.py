"""Offline checks that the dashboard shows all four forces coherently and only calls endpoints that exist."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text()
JS = (ROOT / "web" / "app.js").read_text()
FORCES = ["water", "air", "land", "fire"]


def test_four_force_views_plus_all():
    for f in FORCES:
        assert f'id="{f}ViewBtn"' in HTML and f'id="{f}Box"' in HTML
        assert f"setView('{f}')" in JS and f"{f}: {{forces: ['{f}']" in JS
    assert 'id="allViewBtn"' in HTML and "function renderLand()" in JS


def test_board_legend_updated_sources_and_chips():
    for i in ("boardLegend", "boardUpdated", "boardSources", "tiles", "bannerAqi", "demoBanner"):
        assert f'id="{i}"' in HTML
    legend = HTML.split('id="boardLegend"')[1].split("</div>")[0]
    assert all(s in legend for s in ("ok", "watch", "alert"))
    assert "chip-${f}" in JS and "badge overall" in JS and "['water', 'air', 'land', 'fire'].map(f =>" in JS
    assert "landCtx(t.forces.land.context)" in JS and "fireCtx(t.forces.fire.context)" in JS
    assert "(t.message || {})[lang]" in JS and all(f'data-lang="{l}"' in HTML for l in ("en", "es", "ht"))


def test_stale_feed_is_labelled_in_the_dashboard():
    assert "function feedPill" in JS and "pill stale" in JS and "v.stale && v.transient" in JS
    assert "stale, last good reading" in JS and "g.stale" in JS
    assert "pill.stale" in (ROOT / "web" / "style.css").read_text()


def test_simulated_labels_kept():
    assert JS.count("SIMULATED") >= 8 and "demo_air" in JS
    assert "SIMULATED evacuation order" in HTML


def test_force_query_schema_and_filter(signed_in):
    """force= stays an optional documented enum and does not 422 unknown values."""
    import app
    from core.schema import FORCES, Observation, Place

    schema = app.app.openapi()
    for path in ("/api/observations", "/api/geojson", "/api/cap"):
        params = {p["name"]: p for p in schema["paths"][path]["get"]["parameters"]}
        assert params["force"]["required"] is False
        assert params["force"]["schema"]["enum"] == list(FORCES)

    obs = [
        Observation(force="water", source="test_force", place=Place(id="w", name="W", lat=1, lon=2),
                    time="2026-10-21T00:00:00Z", measurement="m", status="ok"),
        Observation(force="fire", source="test_force", place=Place(id="f", name="F", lat=1, lon=2),
                    time="2026-10-21T00:00:00Z", measurement="m", status="alert"),
    ]
    app.S.obs["test_force"] = obs
    try:
        c = signed_in
        water = c.get("/api/observations", params={"force": "water", "source": "test_force"})
        assert water.status_code == 200 and [o["place"]["id"] for o in water.json()] == ["w"]
        unknown = c.get("/api/observations", params={"force": "not-a-force", "source": "test_force"})
        assert unknown.status_code == 200 and unknown.json() == []
        assert c.get("/api/geojson", params={"force": "fire"}).status_code == 200
        assert c.get("/api/cap", params={"force": "water"}).status_code == 200
    finally:
        app.S.obs.pop("test_force", None)


def test_js_endpoints_exist_and_serve(signed_in):
    import app
    paths = {r.path for r in app.app.routes}
    called = set(re.findall(r"""['"`](/api/[a-z_]+)""", JS))
    assert {"/api/status", "/api/observations", "/api/board", "/api/config", "/api/overlays", "/api/refresh"} <= called
    assert called <= paths, called - paths
    c = signed_in  # no lifespan: no background refresh / network
    assert c.get("/").status_code == 200 and 'id="landViewBtn"' in c.get("/").text
    assert c.get("/static/app.js").status_code == 200
    b = c.get("/api/board").json()
    assert "tiles" in b and "demo_mode" in b
    s = c.get("/api/status").json()
    assert "adapters" in s and "ai" in s
    assert c.get("/api/observations").status_code == 200
