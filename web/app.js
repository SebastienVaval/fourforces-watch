// FourForces Watch front-end (vanilla JS + Leaflet)
const COLORS = {unknown: '#64748b', ok: '#22c55e', watch: '#f59e0b', alert: '#ef4444'};
const FORCE_COLORS = {water: '#38bdf8', air: '#a3e635', land: '#f59e0b', fire: '#f87171'};
const LABEL = {water: 'Water', air: 'Air', land: 'Land', fire: 'Fire'};
let STATUS = null, OBS = [], BOARD = null, lang = 'en', markers = {};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmt = iso => iso ? new Date(iso).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—';

async function apiFetch(url, opts) {
  const r = await globalThis.fetch(url, opts);
  if (r.status === 401) {
    location.assign('/login?next=' + encodeURIComponent(location.pathname + location.search));
    throw new Error('not signed in');
  }
  return r;
}

document.querySelectorAll('.tab').forEach(b => b.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active', x === b));
  document.querySelectorAll('.tabpane').forEach(p => p.classList.toggle('active', p.id === 'tab-' + b.dataset.tab));
  if (b.dataset.tab === 'map') setTimeout(() => map.invalidateSize(), 50);
});
document.querySelectorAll('.lang').forEach(b => b.onclick = () => {
  lang = b.dataset.lang;
  document.querySelectorAll('.lang').forEach(x => x.classList.toggle('active', x === b));
  renderBoard();
});

const map = L.map('map').setView([25.77, -80.25], 10);
const layers = Object.fromEntries(['water', 'air', 'land', 'fire'].map(f => [f, L.layerGroup().addTo(map)]));
const OVERLAYS = {};  // overlay id -> Leaflet layer (filled by initMapLayers)
let fireView = false;

// Basemap: Mapbox when the server has a public MAPBOX_TOKEN (pk.*), else free OSM/CARTO tiles.
const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
function mapboxLayer(style, token) {
  return L.tileLayer(`https://api.mapbox.com/styles/v1/${style}/tiles/512/{z}/{x}/{y}@2x?access_token=${encodeURIComponent(token)}`, {
    tileSize: 512, zoomOffset: -1, maxZoom: 20,
    attribution: '&copy; <a href="https://www.mapbox.com/about/maps/">Mapbox</a> ' + OSM_ATTR +
      ' <a href="https://www.mapbox.com/map-feedback/" target="_blank">Improve this map</a>'});
}
function overlayStyle(m) {
  return f => {
    const v = m.style_field ? f.properties[m.style_field] : null;
    let color = m.color || FORCE_COLORS[m.force] || '#94a3b8';
    if (m.styles && v != null && m.styles[v]) color = m.styles[v];
    if (m.ramp && v != null) for (const [min, c] of m.ramp) if (Number(v) >= min) color = c;
    return {color, weight: 1.5, fillColor: color, fillOpacity: .22, opacity: .9};
  };
}
async function initMapLayers() {
  let cfg = {};
  try { cfg = await (await apiFetch('/api/config')).json(); } catch (e) { /* keep OSM fallback */ }
  const base = {};
  if (cfg.mapbox_token) {
    base['Mapbox ' + cfg.mapbox_style.split('/').pop()] = mapboxLayer(cfg.mapbox_style, cfg.mapbox_token);
    if (cfg.mapbox_style !== 'mapbox/streets-v12') base['Mapbox streets'] = mapboxLayer('mapbox/streets-v12', cfg.mapbox_token);
    base['Mapbox satellite'] = mapboxLayer('mapbox/satellite-streets-v12', cfg.mapbox_token);
  }
  base['OSM / CARTO dark'] = L.tileLayer('https://{s}.basemap.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    {attribution: OSM_ATTR + ' &copy; CARTO', maxZoom: 19});
  Object.values(base)[0].addTo(map);
  const attribution = (cfg.open_data && cfg.open_data.attribution) || '';
  const over = {};
  let metas = [];
  try { metas = await (await apiFetch('/api/overlays')).json(); } catch (e) { /* no overlays */ }
  for (const m of metas) {
    const lyr = L.geoJSON(null, {style: overlayStyle(m), attribution,
      onEachFeature: (f, l) => l.bindPopup(`<div class="popup"><b>${esc(m.name)}</b><br>` +
        Object.entries(f.properties || {}).map(([k, v]) => `${esc(k)}: <b>${esc(v)}</b>`).join('<br>') +
        `<div class="small">${esc(attribution)}</div></div>`)});
    lyr.on('add', async () => {
      if (lyr._loaded) return;
      lyr._loaded = true;
      try { lyr.addData(await (await apiFetch('/api/overlays/' + encodeURIComponent(m.id))).json()); lyr.bringToBack(); }
      catch (e) { lyr._loaded = false; }
    });
    over[`<span class="f ${esc(m.force)}">${esc(LABEL[m.force] || m.force)}</span> ${esc(m.name)}`] = lyr;
    OVERLAYS[m.id] = lyr;
    if (m.default) lyr.addTo(map);
  }
  L.control.layers(base, over, {collapsed: true, position: 'topleft'}).addTo(map);
}
initMapLayers();
document.querySelectorAll('.layers input[data-force]').forEach(cb => cb.onchange = () =>
  cb.checked ? layers[cb.dataset.force].addTo(map) : map.removeLayer(layers[cb.dataset.force]));
document.getElementById('onlyChecked').onchange = renderMap;
document.getElementById('showRefs').onchange = renderMap;

// Fire view: only fire layers (hotspots, stations, cooling centers, heat-island overlay) + fire legend/summary.
const FIRE_OVERLAY = 'mdc_heat_islands';
let savedChecks = null, savedOverlays = [];
const VIEWS = {fire: {forces: ['fire'], overlays: [FIRE_OVERLAY], box: 'fireBox', btn: 'fireViewBtn'},
               air: {forces: ['air'], overlays: [], box: 'airBox', btn: 'airViewBtn'},
               water: {forces: ['water'], overlays: ['mdc_fema_ve', 'mdc_canals'], box: 'waterBox', btn: 'waterViewBtn'},
               land: {forces: ['land'], overlays: ['mdc_surge_zones', 'mdc_evac_routes'], box: 'landBox', btn: 'landViewBtn'}};
const ICON = {water: '💧', air: '🌬', land: '⛰', fire: '🔥'};
let activeView = null;
function setView(name) {
  const boxes = [...document.querySelectorAll('.layers input[data-force]')];
  if (activeView) {  // leave the current view: restore layers and overlays
    boxes.forEach((cb, i) => { cb.checked = savedChecks ? savedChecks[i] : true; cb.onchange(); });
    VIEWS[activeView].overlays.forEach(id => OVERLAYS[id] && map.removeLayer(OVERLAYS[id]));
    savedOverlays.forEach(id => OVERLAYS[id].addTo(map));
    document.getElementById(VIEWS[activeView].btn).classList.remove('active');
    document.getElementById(VIEWS[activeView].box).classList.add('hidden');
  }
  activeView = name === activeView ? null : name;
  fireView = activeView === 'fire';
  if (activeView) {
    const v = VIEWS[activeView];
    savedChecks = boxes.map(cb => cb.checked);
    boxes.forEach(cb => { cb.checked = v.forces.includes(cb.dataset.force); cb.onchange(); });
    document.getElementById('showRefs').checked = true;
    savedOverlays = Object.keys(OVERLAYS).filter(id => map.hasLayer(OVERLAYS[id]));
    savedOverlays.forEach(id => map.removeLayer(OVERLAYS[id]));
    v.overlays.forEach(id => OVERLAYS[id] && OVERLAYS[id].addTo(map));
    document.getElementById(v.btn).classList.add('active');
    document.getElementById(v.box).classList.remove('hidden');
  }
  renderMap(); renderFire(); renderAir(); renderWater(); renderLand();
}
document.getElementById('fireViewBtn').onclick = () => setView('fire');
document.getElementById('airViewBtn').onclick = () => setView('air');
document.getElementById('waterViewBtn').onclick = () => setView('water');
document.getElementById('landViewBtn').onclick = () => setView('land');
document.getElementById('allViewBtn').onclick = () => { if (activeView) setView(activeView); };  // leave any view: all forces

const tide = () => OBS.find(o => o.source === 'noaa_tide');

function cameraPopup(o) {
  const d = o.extra.detection || {}, t = tide();
  const verdict = d.water_on_road === true ? 'water on road' : d.water_on_road === false ? 'no water seen' : 'not checked yet';
  const alerts = OBS.filter(a => a.source === 'nws_alerts' && a.force === 'water')
    .map(a => `<li>${esc(a.measurement)} (until ${fmt(a.extra.ends)})</li>`).join('');
  return `<div class="popup"><b>${esc(o.place.name)}</b><br>
    ${o.extra.simulated ? '<div class="sim">SIMULATED IMAGE (demo)</div>' : ''}
    <img src="${esc(o.extra.image_url)}" alt="camera snapshot" referrerpolicy="no-referrer">
    <div class="small">${esc(o.extra.image_credit || 'Camera: FL511 / Florida DOT (live link, not stored)')}</div>
    <div>Status: <span class="st ${o.status}">${esc(o.status.toUpperCase())}</span>, ${verdict}
      ${d.confidence != null ? `(${Math.round(d.confidence * 100)}%)` : ''}</div>
    ${d.note ? `<div class="small">Grok: ${esc(d.note)}${d.checked_at ? ' · ' + fmt(d.checked_at) : ''}</div>` : ''}
    ${t ? `<div>Tide at Virginia Key: <b>${t.value.toFixed(2)} ft</b> MLLW (<span class="st ${t.status}">${esc(t.status)}</span>)</div>` : ''}
    ${alerts ? `<div>Active NWS alerts:<ul>${alerts}</ul></div>` : '<div class="small">No active NWS flood alerts.</div>'}
    <button onclick="checkCam('${esc(o.place.id)}', this)">Check now with Grok</button></div>`;
}

async function checkCam(id, btn) {
  btn.disabled = true; btn.textContent = 'Asking Grok…';
  try {
    const j = await (await apiFetch(`/api/cameras/${encodeURIComponent(id)}/check`, {method: 'POST'})).json();
    const i = OBS.findIndex(o => o.place.id === id);
    if (i >= 0) OBS[i] = j.camera;
    renderMap(); renderSide();
    markers[id] && markers[id].openPopup();
  } catch (e) { btn.textContent = 'Failed'; }
}
window.checkCam = checkCam;

function popupFor(o) {
  const ex = o.extra || {};
  return `<div class="popup"><b>${esc(o.place.name)}</b><br>${esc(LABEL[o.force])} · ${esc(o.measurement)}<br>
    Value: <b>${esc(o.value)} ${esc(o.unit || '')}</b> · <span class="st ${o.status}">${esc(o.status)}</span>
    ${ex.headline ? '<br>' + esc(ex.headline) : ''}${ex.rise_3h_ft != null ? '<br>3-hour change: ' + ex.rise_3h_ft + ' ft' : ''}
    ${ex.link ? `<br><a href="${esc(ex.link)}" target="_blank" rel="noopener">source</a>` : ''}
    <div class="small">${esc(o.source)} · ${fmt(o.time)}</div></div>`;
}

const REF_COLORS = {mdc_fire_stations: '#f43f5e', mdc_cooling_centers: '#22d3ee', mdc_hospitals: '#e2e8f0', mdc_evac_bus_pickup: '#f59e0b'};

function hotspotPopup(o) {
  const ex = o.extra, ns = ex.nearest_station;
  return `<div class="popup"><b>${esc(ex.simulated ? 'Fire detection (demo)' : o.place.name)}</b><br>
    ${ex.simulated ? '<div class="sim">SIMULATED HOTSPOT (demo)</div>' : ''}
    Confidence: <b>${esc(ex.confidence)}</b> · FRP <b>${esc(o.value)} MW</b><br>
    ${esc(ex.simulated ? 'demo, not a satellite pass' : `${ex.product || ''} ${ex.satellite || ''} · ${ex.daynight === 'N' ? 'night' : 'day'} pass`)}
    · ${fmt(o.time)}<br>
    ${ns ? `Nearest fire station: <b>${esc(ns.name)}</b> (${ns.km} km straight line)<br>` : ''}
    ${ex.note ? `<div class="small">${esc(ex.note)}</div>` : ''}
    ${ex.link ? `<a href="${esc(ex.link)}" target="_blank" rel="noopener">NASA FIRMS map</a>` : ''}
    <div class="small">${esc(o.source)} · Report fires to 911. Not an official warning.</div></div>`;
}

const AQI_CATS = [[50, '#00e400', 'Good'], [100, '#ffff00', 'Moderate'], [150, '#ff7e00', 'Unhealthy for Sensitive Groups'],
  [200, '#ff0000', 'Unhealthy'], [300, '#8f3f97', 'Very Unhealthy'], [1e9, '#7e0023', 'Hazardous']];
const aqiColor = v => v == null ? COLORS.unknown : AQI_CATS.find(c => v <= c[0])[1];

function aqiPopup(o) {
  const ex = o.extra;
  return `<div class="popup"><b>${esc(ex.simulated ? 'AQI sensor (demo)' : o.place.name)}</b><br>
    ${ex.simulated ? '<div class="sim">SIMULATED AQI (demo)</div>' : ''}
    AQI <b style="color:${aqiColor(o.value)}">${esc(o.value)}</b> · ${esc(ex.category || '')}<br>
    <span class="small">${esc(o.measurement)}${ex.pm25_ugm3 != null ? ` · PM2.5 ${esc(ex.pm25_ugm3)} µg/m³` : ''}
    ${ex.network ? ' · ' + esc(ex.network) : ''} · ${fmt(o.time)}</span>
    ${ex.note ? `<div class="small">${esc(ex.note)}</div>` : ''}
    ${ex.link ? `<br><a href="${esc(ex.link)}" target="_blank" rel="noopener">source</a>` : ''}
    <div class="small">Not an official warning. Check airnow.gov.</div></div>`;
}

function renderWater() {
  const box = document.getElementById('waterBox');
  if (activeView !== 'water') return;
  const cams = OBS.filter(o => o.source === 'fl511_cameras'), n = st => cams.filter(c => c.status === st).length;
  const sim = cams.filter(c => c.extra.simulated).length;
  const g = OBS.filter(o => o.source === 'usgs_gauges'), gw = g.filter(o => o.status !== 'ok');
  const t = tide(), al = OBS.filter(o => o.force === 'water' && o.source.startsWith('nws_'));
  const nh = t && t.extra.next_high;
  box.innerHTML = `<h4>Water view</h4>
    ${t ? `<div>Tide (NOAA ${esc(t.place.id.replace('noaa-', ''))}): <b>${t.value.toFixed(2)} ft</b> MLLW <span class="st ${t.status}">${esc(t.status)}</span>
      ${t.extra.trend ? '· ' + esc(t.extra.trend) : ''} · ${t.extra.anomaly_ft >= 0 ? '+' : ''}${t.extra.anomaly_ft} ft vs forecast</div>
      ${nh ? `<div class="small">Next high ${fmt(nh.time)}: ${nh.predicted_ft} ft forecast, ≈ ${nh.projected_ft} ft with today's excess (minor flood ${t.threshold} ft)</div>` : ''}` : '<div class="small">Tide: no data</div>'}
    <div>Cameras: <b>${cams.length}</b> · <span style="color:${COLORS.alert}">${n('alert')} water</span> · <span style="color:${COLORS.watch}">${n('watch')} possible</span>
      · <span style="color:${COLORS.ok}">${n('ok')} dry</span> · ${n('unknown')} not checked${sim ? ` · <span class="sim">${sim} SIMULATED images</span>` : ''}
      ${STATUS && !STATUS.ai.key_present ? '<div class="small">No XAI_API_KEY: cameras stay "not checked".</div>' : ''}</div>
    <div>USGS canal gauges: <b>${g.length}</b>${gw.length ? ` · <span class="st watch">${gw.length} rising fast / above threshold</span>` : ' · none rising fast'}</div>
    <div>NWS flood / coastal / surge alerts: <b>${al.length}</b>${al.map(a => `<div class="small">${esc(a.measurement)}</div>`).join('')}</div>
    <div class="legend"><span><i class="dot grey"></i>camera not checked</span><span><i class="dot ok"></i>dry</span>
      <span><i class="dot watch"></i>possible water</span><span><i class="dot alert"></i>water on road</span>
      <span><i class="dot" style="background:#64748b;outline:2px solid #fde047"></i>SIMULATED image</span>
      <span><i class="dot" style="background:#22c55e;outline:2px solid #38bdf8"></i>tide / USGS gauge</span>
      <span><i class="dot" style="background:#0ea5e9;opacity:.5"></i>FEMA VE zone</span><span><i class="dot" style="background:#22d3ee"></i>canal</span></div>
    <div class="small">Board rule: camera water on road (Grok, ≥ 60% = alert, else watch); tide ≥ ${t ? esc((t.extra.thresholds || {}).watch_ft) : 3} ft = watch,
      ≥ minor flood = alert (coastal zones only); USGS gauge rise ≥ 0.5 ft / 3 h = watch; NWS flood alerts by zone.
      FEMA flood zone is context only. Sources: FL511/FDOT, NOAA CO-OPS, USGS, NWS, Miami-Dade County Open Data.</div>`;
}

function renderAir() {
  const box = document.getElementById('airBox');
  if (activeView !== 'air') return;
  const sens = OBS.filter(o => o.extra.kind === 'aqi_sensor'), sim = sens.filter(o => o.extra.simulated);
  const area = OBS.filter(o => o.extra.kind === 'aqi_area' || o.extra.network === 'AirNow');
  const storms = OBS.filter(o => o.source === 'nhc_storms');
  const wind = OBS.filter(o => o.force === 'air' && o.source.startsWith('nws_'));
  const ad = n => STATUS && STATUS.adapters[n];
  const feed = n => { const a = ad(n); return a ? (a.ok ? `<span class="pill ok">live</span> ${a.count}` : `<span class="pill skip">${esc(needsKey(a.skipped) || 'off')}</span>`) : '—'; };
  box.innerHTML = `<h4>Air view</h4>
    <div>AirNow: ${feed('airnow')} · PurpleAir: ${feed('purpleair')}</div>
    <div>AQI sensors: <b>${sens.length - sim.length}</b> real${sim.length ? ` · <span class="sim">${sim.length} SIMULATED</span>` : ''}
      · of which official AirNow: <b>${area.length}</b></div>
    <div>Tropical systems (NHC): <b>${storms.length}</b>${storms.map(s => `<div class="small">${esc(s.extra.headline || s.place.name)}</div>`).join('')}</div>
    <div>NWS wind / tropical / air alerts: <b>${wind.length}</b></div>
    <div class="legend">${AQI_CATS.map(([lim, c, n], i) => `<span><i class="dot" style="background:${c}"></i>${n} (${i ? AQI_CATS[i - 1][0] + 1 : 0}${lim < 1e9 ? '–' + lim : '+'})</span>`).join('')}
      <span><i class="dot" style="background:#f97316;outline:2px dashed #fde047"></i>SIMULATED</span>
      <span><i class="dot" style="background:#64748b;outline:2px solid #e879f9"></i>storm center</span></div>
    <div class="small">Board rule: tile AQI = median of monitors/sensors within 5 km (worst pollutant each), else the worst AirNow reading city-wide. AQI ≥ 101 = watch, ≥ 151 = alert
      (EPA 2024 PM2.5 breakpoints; PurpleAir EPA-corrected). Storm within 800 km = watch, 300 km = alert.</div>`;
}

function renderLand() {
  const box = document.getElementById('landBox');
  if (activeView !== 'land') return;
  const zones = OBS.filter(o => o.measurement === 'hurricane_evacuation_zone');
  const flagged = zones.filter(o => o.extra.evac_order_flag), sim = flagged.filter(o => o.extra.simulated);
  const shelters = OBS.filter(o => o.source === 'evac_shelters');
  const quakes = OBS.filter(o => o.extra.kind === 'earthquake');
  const fema = OBS.filter(o => o.source === 'openfema_declarations');
  const nws = OBS.filter(o => o.force === 'land' && o.source.startsWith('nws_'));
  const nRef = id => OBS.filter(o => o.extra.layer === id).length;
  box.innerHTML = `<h4>Land view</h4>
    <div>Evacuation order flags: <b>${flagged.length - sim.length}</b> real${sim.length ? ` · <span class="sim">${sim.length} SIMULATED</span>` : ''}
      <span class="small">(county layer; confirm with official channels)</span></div>
    <div>Open shelters: <b>${shelters.length}</b> · evacuation bus pickups: <b>${nRef('mdc_evac_bus_pickup')}</b> · hospitals: <b>${nRef('mdc_hospitals')}</b></div>
    <div>FEMA declarations (365 d): <b>${fema.length}</b>${fema.map(f => `<div class="small">${esc(f.extra.headline || '')}</div>`).join('')}</div>
    <div>Earthquakes (USGS, 30 d): <b>${quakes.length}</b>${quakes.slice(0, 3).map(q => `<div class="small">${esc(q.extra.headline || '')}</div>`).join('')}</div>
    <div>NWS evacuation / civil emergency alerts: <b>${nws.length}</b></div>
    <div class="legend"><span><i class="dot" style="background:#dc2626"></i>surge zone A</span><span><i class="dot" style="background:#f97316"></i>B</span>
      <span><i class="dot" style="background:#facc15"></i>C</span><span><i class="dot" style="background:#22c55e"></i>D</span><span><i class="dot" style="background:#3b82f6"></i>E</span>
      <span><i class="dot" style="background:#e879f9"></i>evacuation route</span><span><i class="dot" style="background:${REF_COLORS.mdc_evac_bus_pickup}"></i>bus pickup</span>
      <span><i class="dot" style="background:${REF_COLORS.mdc_hospitals}"></i>hospital</span></div>
    <div class="small">Board rule: county evacuation order flag = watch (confirm with official channels); open FEMA declaration = watch county-wide;
      earthquake ≥ M4.5 within 50 km = alert, any within 150 km = watch. Shelters, pickups and hospitals are information only.
      Sources: Miami-Dade County Open Data, OpenFEMA, USGS, NWS.</div>`;
}

function renderBoardMeta() {
  if (!STATUS) return;
  document.getElementById('boardUpdated').textContent = fmt(STATUS.last_refresh);
  const by = {};
  Object.values(STATUS.adapters || {}).forEach(a => (by[a.force] = by[a.force] || []).push(
    `${esc(a.name)}${a.ok ? '' : ' <i>(' + esc(a.skipped ? needsKey(a.skipped) || 'off' : 'error') + ')</i>'}`));
  document.getElementById('boardSources').innerHTML = ['water', 'air', 'land', 'fire'].map(f =>
    `<div class="srcline">${ICON[f]} <b>${LABEL[f]}</b>: ${(by[f] || []).join(', ') || '—'}</div>`).join('');
}

function renderFire() {
  const box = document.getElementById('fireBox');
  if (activeView !== 'fire') return;
  const hs = OBS.filter(o => o.extra.kind === 'hotspot'), real = hs.filter(o => !o.extra.simulated);
  const hi = OBS.find(o => o.measurement === 'heat_index_observed'), hf = OBS.find(o => o.measurement === 'heat_index_forecast_max_12h');
  const alerts = OBS.filter(o => o.force === 'fire' && o.source.startsWith('nws_') && o.source !== 'nws_heat_index');
  const nRef = id => OBS.filter(o => o.extra.layer === id).length;
  const firms = STATUS && STATUS.adapters.nasa_firms;
  box.innerHTML = `<h4>Fire view</h4>
    <div>Satellite hotspots (NASA FIRMS, 48 h): <b>${real.length}</b> real${hs.length > real.length ? ` · <span class="sim">${hs.length - real.length} SIMULATED</span>` : ''}
      ${firms && !firms.ok ? `<div class="small">FIRMS: ${esc(firms.skipped || firms.error || 'off')}</div>` : ''}</div>
    <div>Heat index now: <b>${hi ? esc(hi.value) + ' F' : '—'}</b> <span class="st ${hi ? hi.status : 'unknown'}">${hi ? esc(hi.status) : ''}</span>
      · 12 h peak: <b>${hf ? esc(hf.value) + ' F' : '—'}</b> <span class="st ${hf ? hf.status : 'unknown'}">${hf ? esc(hf.status) : ''}</span></div>
    <div>NWS heat / red flag alerts: <b>${alerts.length}</b>${alerts.map(a => `<div class="small">${esc(a.measurement)}</div>`).join('')}</div>
    <div class="legend fire-legend">
      <span><i class="dot" style="background:#dc2626"></i>hotspot, high conf.</span><span><i class="dot" style="background:#f97316"></i>nominal</span>
      <span><i class="dot" style="background:#fbbf24"></i>low</span><span><i class="dot" style="background:#f97316;outline:2px dashed #fde047"></i>SIMULATED</span>
      <span><i class="dot" style="background:${REF_COLORS.mdc_fire_stations}"></i>fire station (${nRef('mdc_fire_stations')})</span>
      <span><i class="dot" style="background:${REF_COLORS.mdc_cooling_centers}"></i>cooling center (${nRef('mdc_cooling_centers')})</span>
      <span><i class="dot" style="background:linear-gradient(90deg,#fde68a,#ef4444,#991b1b)"></i>urban heat island (°F above rural)</span>
    </div>
    <div class="small">Board rule: a hotspot of nominal+ confidence within 15 km of a neighborhood = watch, within 5 km = alert.
      Heat index ≥ 103 F = watch, ≥ 108 F = alert. Sources: NASA FIRMS, NWS, Miami-Dade County Open Data.</div>`;
}

function refPopup(o) {
  const p = o.extra.properties || {};
  return `<div class="popup"><b>${esc(o.place.name)}</b><br>${esc(LABEL[o.force])} · ${esc(o.extra.layer_name || o.measurement)}<br>
    ${Object.entries(p).map(([k, v]) => `<span class="small">${esc(k)}:</span> ${esc(v)}`).join('<br>')}
    ${o.extra.link ? `<br><a href="${esc(o.extra.link)}" target="_blank" rel="noopener">info</a>` : ''}
    <div class="small">Reference site, not a hazard reading · ${esc(o.extra.attribution || o.source)}</div></div>`;
}

function renderMap() {
  Object.values(layers).forEach(l => l.clearLayers()); markers = {};
  const showRefs = document.getElementById('showRefs').checked;
  const onlyChecked = document.getElementById('onlyChecked').checked;
  for (const o of OBS) {
    if (o.place.lat == null || o.place.lon == null) continue;
    if (o.source === 'fl511_cameras') {
      if (onlyChecked && o.status === 'unknown') continue;
      markers[o.place.id] = L.circleMarker([o.place.lat, o.place.lon], {
        radius: o.status === 'unknown' ? 4 : 7, color: o.extra.simulated ? '#fde047' : '#0f172a',
        weight: o.extra.simulated ? 3 : 1, fillColor: COLORS[o.status], fillOpacity: .9})
        .bindPopup(() => cameraPopup(o), {maxWidth: 340}).addTo(layers.water);
      continue;
    }
    if (o.extra.kind === 'aqi_sensor' || o.extra.kind === 'aqi_area') {  // AQI: EPA category colors
      const area = o.extra.kind === 'aqi_area';
      markers[o.place.id] = L.circleMarker([o.place.lat, o.place.lon], {
        radius: area ? 14 : 8, color: o.extra.simulated ? '#fde047' : '#0f172a', weight: o.extra.simulated ? 3 : 1,
        dashArray: o.extra.simulated ? '4 3' : null, fillColor: aqiColor(o.value), fillOpacity: area ? .45 : .9})
        .bindPopup(aqiPopup(o), {maxWidth: 320}).addTo(layers.air);
      continue;
    }
    if (o.source === 'nhc_storms') {  // storm center (NHC), even though it is area-scoped
      L.circleMarker([o.place.lat, o.place.lon], {radius: 11, color: '#e879f9', weight: 3,
        fillColor: COLORS[o.status] || COLORS.unknown, fillOpacity: .8}).bindPopup(popupFor(o)).addTo(layers.air);
      continue;
    }
    if (o.extra.scope === 'area' && o.source !== 'noaa_tide' && o.source !== 'nws_heat_index') continue;  // side panel
    if (o.extra.kind === 'flood_zone') continue;  // per-neighborhood context, shown on the board
    if (o.extra.reference) {  // county open-data reference site: small marker, info only
      if (!showRefs) continue;
      const fc = REF_COLORS[o.extra.layer] || FORCE_COLORS[o.force];
      L.circleMarker([o.place.lat, o.place.lon], {radius: 4, color: '#0f172a', weight: 1,
        fillColor: fc, fillOpacity: .95}).bindPopup(refPopup(o)).addTo(layers[o.force] || layers.land);
      continue;
    }
    if (o.extra.kind === 'hotspot') {  // satellite fire detection (real FIRMS or SIMULATED demo)
      markers[o.place.id] = L.circleMarker([o.place.lat, o.place.lon], {
        radius: Math.min(16, 7 + Math.sqrt(o.value || 1)), color: o.extra.simulated ? '#fde047' : '#7f1d1d',
        weight: o.extra.simulated ? 3 : 2, dashArray: o.extra.simulated ? '4 3' : null,
        fillColor: o.extra.confidence === 'high' ? '#dc2626' : o.extra.confidence === 'nominal' ? '#f97316' : '#fbbf24',
        fillOpacity: .9}).bindPopup(hotspotPopup(o), {maxWidth: 320}).addTo(layers.fire);
      continue;
    }
    L.circleMarker([o.place.lat, o.place.lon], {radius: o.source === 'noaa_tide' ? 10 : 6, color: FORCE_COLORS[o.force],
      weight: 2, fillColor: COLORS[o.status] || COLORS.unknown, fillOpacity: .75})
      .bindPopup(popupFor(o)).addTo(layers[o.force] || layers.land);
  }
}

function renderSide() {
  const t = tide(), tb = document.getElementById('tideBox');
  if (t) {
    const nh = t.extra.next_high;
    tb.innerHTML = `<h4>Tide · Virginia Key (NOAA)</h4><div class="big" style="color:${COLORS[t.status]}">${t.value.toFixed(2)} ft</div>
      <div>MLLW · ${t.extra.anomaly_ft >= 0 ? '+' : ''}${t.extra.anomaly_ft} ft vs forecast · minor flood at ${t.threshold} ft</div>
      ${nh ? `<div class="small">Next high ${fmt(nh.time)}: forecast ${nh.predicted_ft} ft; with today's excess ≈ ${nh.projected_ft} ft</div>` : ''}`;
  } else tb.innerHTML = '<h4>Tide</h4><div class="small">no data</div>';
  const cams = OBS.filter(o => o.source === 'fl511_cameras'), n = s => cams.filter(c => c.status === s).length;
  document.getElementById('camSummary').innerHTML = `<h4>${cams.length} public traffic cameras</h4>
    <span style="color:${COLORS.alert}">● ${n('alert')} water</span> · <span style="color:${COLORS.watch}">● ${n('watch')} possible</span> ·
    <span style="color:${COLORS.ok}">● ${n('ok')} dry</span> · <span style="color:${COLORS.unknown}">● ${n('unknown')} not checked</span>
    ${STATUS && !STATUS.ai.key_present ? '<div class="small">XAI_API_KEY not configured: cameras stay unchecked.</div>' : ''}`;
  const alerts = OBS.filter(o => o.extra.scope === 'area' && o.status !== 'ok' && o.status !== 'unknown');
  document.getElementById('areaAlerts').innerHTML = alerts.length ? alerts.map(a => `<div class="alert-item ${a.status}">
    <b>${esc(LABEL[a.force])}: ${esc(a.measurement)}</b>${esc(a.extra.headline || '')}
    ${a.extra.ends ? `<div class="small">until ${fmt(a.extra.ends)}</div>` : ''}</div>`).join('') : '<div class="small">None right now.</div>';
}

function waterCtx(c) {
  if (!c || !Object.keys(c).length) return '';
  const fz = c.flood_zone, td = c.tide, cam = c.camera, g = c.gauge;
  return `<div class="waterctx">${fz ? `<div>FEMA flood zone <b>${esc(fz.zone)}</b> <span class="small">${esc(fz.meaning || '')}</span></div>` : ''}
    ${td && td.applies ? `<div>Tide <b>${esc(td.ft)} ft</b> ${esc(td.trend || '')}${td.next_high ? ` · next high ${fmt(td.next_high.time)} ≈ ${esc(td.next_high.projected_ft)} ft` : ''}</div>` : ''}
    ${cam ? `<div>Camera <b>${esc(cam.name)}</b> ${cam.km} km: <span class="st ${cam.status}">${esc(cam.verdict)}</span>${cam.simulated ? ' <span class="sim">SIMULATED</span>' : ''}</div>` : ''}
    ${g ? `<div>Gauge <b>${esc(g.name)}</b> ${g.km} km: ${esc(g.ft)} ft (${g.rise_3h_ft >= 0 ? '+' : ''}${esc(g.rise_3h_ft)} ft / 3 h)</div>` : ''}</div>`;
}

function airCtx(c) {
  if (!c || (!c.aqi && !c.nearest_storm)) return '';
  const a = c.aqi;
  return `<div class="airctx">${a ? `<div>AQI <b style="color:${aqiColor(a.aqi)}">${esc(a.aqi)}</b> ${esc(a.category)}
      <span class="small">(${esc(a.source)})</span>${a.simulated ? ' <span class="sim">SIMULATED</span>' : ''}</div>` : ''}
    ${c.nearest_storm ? `<div>Nearest storm: <b>${esc(c.nearest_storm.name)}</b> ${esc(c.nearest_storm.km)} km</div>` : ''}</div>`;
}

function fireCtx(c) {
  if (!c || (!c.nearest_station && !c.cooling_centers)) return '';
  return `<div class="firectx">${c.nearest_station ? `<div>Fire station: <b>${esc(c.nearest_station.name)}</b> ${c.nearest_station.km} km</div>` : ''}
    ${c.cooling_centers ? `<div>Cooling: ${c.cooling_centers.map(x => `<b>${esc(x.name)}</b> ${x.km} km`).join(' · ')}</div>` : ''}
    ${c.nearest_hotspot ? `<div>Nearest hotspot: ${c.nearest_hotspot.km} km${c.nearest_hotspot.simulated ? ' <span class="sim">SIMULATED</span>' : ''}</div>` : ''}</div>`;
}

function landCtx(c) {
  if (!c || (!c.evac_zone && !c.nearest_shelter && !c.nearest_bus_pickup)) return '';
  const z = c.evac_zone;
  return `<div class="landctx">${z ? `<div>Evacuation zone <b>${esc(z.zone)}</b>${z.order_flag ? ' · order flagged (confirm with official channels)' : ''}${z.simulated ? ' <span class="sim">SIMULATED</span>' : ''}</div>` : ''}
    ${c.nearest_shelter ? `<div>Open shelter: <b>${esc(c.nearest_shelter.name)}</b> ${c.nearest_shelter.km} km</div>` : ''}
    ${c.nearest_bus_pickup ? `<div>Evac bus pickup: <b>${esc(c.nearest_bus_pickup.name)}</b> ${c.nearest_bus_pickup.km} km</div>` : ''}</div>`;
}

// Who wrote the messages: Grok's model name, or why templates are showing (server sends message_label).
function msgLabel(board, status) {
  if (board.message_label) return board.message_label;
  const by = board.tiles.map(t => (t.message || {}).by).find(b => b && b !== 'template');
  if (by) return by;
  if (!(status && status.ai && status.ai.key_present)) return 'templates (no xAI key)';
  return board.ai_pending === false ? 'templates (Grok unavailable)' : 'templates (Grok messages loading…)';
}

function renderBoard() {
  if (!BOARD) return;
  document.getElementById('tiles').innerHTML = BOARD.tiles.map(t => {
    const badges = ['water', 'air', 'land', 'fire'].map(f =>
      `<div class="badge chip-${f} ${t.forces[f].status}" title="${esc((t.forces[f].sources || []).join(', '))}">${ICON[f]} ${LABEL[f]}<small>${t.forces[f].status}</small></div>`).join('')
      + `<div class="badge overall ${t.status}">Overall<small>${t.status}</small></div>`;
    const reasons = Object.values(t.forces).flatMap(f => f.reasons).slice(0, 4).map(r => `<li>${esc(r)}</li>`).join('');
    return `<div class="tile ${t.status}"><h3>${esc(t.name)}<span class="small">${esc(t.zone || '')}</span></h3>
      <div class="badges">${badges}</div><div class="msg">${esc((t.message || {})[lang] || '')}</div>
      ${reasons ? `<ul class="reasons">${reasons}</ul>` : ''}${waterCtx(t.forces.water.context)}${airCtx(t.forces.air.context)}${landCtx(t.forces.land.context)}${fireCtx(t.forces.fire.context)}<div class="small">message by: ${esc((t.message || {}).by || '')}</div></div>`;
  }).join('');
  document.getElementById('msgModel').textContent = msgLabel(BOARD, STATUS);
}

const needsKey = msg => { const m = /([A-Z][A-Z0-9_]*_(?:KEY|TOKEN))/.exec(msg || ''); return m ? 'needs ' + m[1] : null; };

function renderFeeds() {
  const ai = STATUS.ai;
  document.getElementById('aiStatus').innerHTML = `<h4>AI: ${esc(ai.provider)}</h4>
    Key: <span class="pill ${ai.key_present ? 'ok' : 'skip'}">${ai.key_present ? 'configured' : 'missing (templates + unchecked cameras)'}</span>
    · vision <code>${esc(ai.vision_model)}</code> · text <code>${esc(ai.text_model)}</code> · cameras checked: ${ai.cameras_checked}
    · demo mode: ${STATUS.demo_mode ? 'ON (simulated images)' : 'off'} · last refresh: ${fmt(STATUS.last_refresh)}`;
  document.getElementById('statusRefreshed').textContent = 'page updated ' + fmt(new Date().toISOString());
  const rows = Object.entries(STATUS.adapters).sort((a, b) => a[1].force.localeCompare(b[1].force));
  document.querySelector('#feeds tbody').innerHTML = rows.map(([k, v]) => `<tr><td>${esc(k)}<div class="small">${esc(v.doc || '')}</div></td>
    <td>${esc(v.force)}</td><td><span class="pill ${v.ok ? 'ok' : v.skipped ? 'skip' : 'err'}">${v.ok ? 'live' : v.skipped ? esc(needsKey(v.skipped) || 'off') : 'error'}</span></td>
    <td>${v.count ?? ''}</td><td>${fmt(v.last_run)}</td><td>${fmt(v.last_ok)}</td><td>${v.ms != null ? v.ms + ' ms' : ''}</td>
    <td class="small">${esc(v.skipped || v.error || '')}</td></tr>`).join('');
}

async function load() {
  const [s, o, b] = await Promise.all(['/api/status', '/api/observations', '/api/board'].map(u => apiFetch(u).then(r => r.json())));
  const first = !STATUS;
  STATUS = s; OBS = o; BOARD = b;
  document.getElementById('cityName').textContent = s.city.name;
  document.getElementById('demoBanner').classList.toggle('hidden', !s.demo_mode);
  document.getElementById('bannerAqi').classList.toggle('hidden', !o.some(x => x.source === 'demo_air'));
  document.getElementById('lastRefresh').textContent = s.last_refresh ? 'updated ' + fmt(s.last_refresh) : 'first refresh running…';
  if (first && s.city.center) map.setView(s.city.center, s.city.zoom || 10);
  renderMap(); renderSide(); renderBoard(); renderBoardMeta(); renderFeeds(); renderFire(); renderAir(); renderWater(); renderLand();
  if (!s.last_refresh) setTimeout(load, 4000);
  else if (b.ai_pending) setTimeout(load, 15000);  // Grok messages / camera checks still landing
}
document.getElementById('refreshBtn').onclick = async () => {
  await apiFetch('/api/refresh', {method: 'POST'});
  document.getElementById('lastRefresh').textContent = 'refreshing…';
  setTimeout(load, 8000);
};
load();
setInterval(load, 60000);
