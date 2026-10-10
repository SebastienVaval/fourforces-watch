"""Offline checks that the dashboard shows all four forces coherently and only calls endpoints that exist."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

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


def test_simulated_labels_kept():
    assert JS.count("SIMULATED") >= 8 and "demo_air" in JS
    assert "SIMULATED evacuation order" in HTML


def test_js_endpoints_exist_and_serve():
    import app
    paths = {r.path for r in app.app.routes}
    called = set(re.findall(r"""['"`](/api/[a-z_]+)""", JS))
    assert {"/api/status", "/api/observations", "/api/board", "/api/config", "/api/overlays", "/api/refresh"} <= called
    assert called <= paths, called - paths
    c = TestClient(app.app)  # no lifespan: no background refresh / network
    assert c.get("/").status_code == 200 and 'id="landViewBtn"' in c.get("/").text
    assert c.get("/static/app.js").status_code == 200
    b = c.get("/api/board").json()
    assert "tiles" in b and "demo_mode" in b
    s = c.get("/api/status").json()
    assert "adapters" in s and "ai" in s
    assert c.get("/api/observations").status_code == 200
