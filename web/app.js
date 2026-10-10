// FourForces Watch front-end (vanilla JS + Leaflet)
const COLORS = {unknown: '#64748b', ok: '#22c55e', watch: '#f59e0b', alert: '#ef4444'};
const FORCE_COLORS = {water: '#38bdf8', air: '#a3e635', land: '#f59e0b', fire: '#f87171'};
const LABEL = {water: 'Water', air: 'Air', land: 'Land', fire: 'Fire'};
let STATUS = null, OBS = [], BOARD = null, lang = 'en', markers = {};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmt = iso => iso ? new Date(iso).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—';

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
L.tileLayer('https://{s}.basemap.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
  {attribution: '&copy; OpenStreetMap contributors &copy; CARTO', maxZoom: 19}).addTo(map);
const layers = Object.fromEntries(['water', 'air', 'land', 'fire'].map(f => [f, L.layerGroup().addTo(map)]));
document.querySelectorAll('.layers input[data-force]').forEach(cb => cb.onchange = () =>
  cb.checked ? layers[cb.dataset.force].addTo(map) : map.removeLayer(layers[cb.dataset.force]));
document.getElementById('onlyChecked').onchange = renderMap;

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
    const j = await (await fetch(`/api/cameras/${encodeURIComponent(id)}/check`, {method: 'POST'})).json();
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

function renderMap() {
  Object.values(layers).forEach(l => l.clearLayers()); markers = {};
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
    if (o.extra.scope === 'area' && o.source !== 'noaa_tide' && o.source !== 'nws_heat_index') continue;  // side panel
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

function renderBoard() {
  if (!BOARD) return;
  document.getElementById('tiles').innerHTML = BOARD.tiles.map(t => {
    const badges = ['water', 'air', 'land', 'fire'].map(f =>
      `<div class="badge ${t.forces[f].status}">${LABEL[f]}<small>${t.forces[f].status}</small></div>`).join('');
    const reasons = Object.values(t.forces).flatMap(f => f.reasons).slice(0, 4).map(r => `<li>${esc(r)}</li>`).join('');
    return `<div class="tile ${t.status}"><h3>${esc(t.name)}<span class="small">${esc(t.zone || '')}</span></h3>
      <div class="badges">${badges}</div><div class="msg">${esc((t.message || {})[lang] || '')}</div>
      ${reasons ? `<ul class="reasons">${reasons}</ul>` : ''}<div class="small">message by: ${esc((t.message || {}).by || '')}</div></div>`;
  }).join('');
  const by = BOARD.tiles.map(t => (t.message || {}).by).find(b => b && b !== 'template');
  document.getElementById('msgModel').textContent = by || 'templates (no xAI key)';
}

function renderFeeds() {
  const ai = STATUS.ai;
  document.getElementById('aiStatus').innerHTML = `<h4>AI: ${esc(ai.provider)}</h4>
    Key: <span class="pill ${ai.key_present ? 'ok' : 'skip'}">${ai.key_present ? 'configured' : 'missing (templates + unchecked cameras)'}</span>
    · vision <code>${esc(ai.vision_model)}</code> · text <code>${esc(ai.text_model)}</code> · cameras checked: ${ai.cameras_checked}
    · demo mode: ${STATUS.demo_mode ? 'ON (simulated images)' : 'off'} · last refresh: ${fmt(STATUS.last_refresh)}`;
  document.getElementById('statusRefreshed').textContent = 'page updated ' + fmt(new Date().toISOString());
  const rows = Object.entries(STATUS.adapters).sort((a, b) => a[1].force.localeCompare(b[1].force));
  document.querySelector('#feeds tbody').innerHTML = rows.map(([k, v]) => `<tr><td>${esc(k)}<div class="small">${esc(v.doc || '')}</div></td>
    <td>${esc(v.force)}</td><td><span class="pill ${v.ok ? 'ok' : v.skipped ? 'skip' : 'err'}">${v.ok ? 'live' : v.skipped ? 'needs key / off' : 'error'}</span></td>
    <td>${v.count ?? ''}</td><td>${fmt(v.last_run)}</td><td>${fmt(v.last_ok)}</td><td>${v.ms != null ? v.ms + ' ms' : ''}</td>
    <td class="small">${esc(v.skipped || v.error || '')}</td></tr>`).join('');
}

async function load() {
  const [s, o, b] = await Promise.all(['/api/status', '/api/observations', '/api/board'].map(u => fetch(u).then(r => r.json())));
  const first = !STATUS;
  STATUS = s; OBS = o; BOARD = b;
  document.getElementById('cityName').textContent = s.city.name;
  document.getElementById('demoBanner').classList.toggle('hidden', !s.demo_mode);
  document.getElementById('lastRefresh').textContent = s.last_refresh ? 'updated ' + fmt(s.last_refresh) : 'first refresh running…';
  if (first && s.city.center) map.setView(s.city.center, s.city.zoom || 10);
  renderMap(); renderSide(); renderBoard(); renderFeeds();
  if (!s.last_refresh) setTimeout(load, 4000);
}
document.getElementById('refreshBtn').onclick = async () => {
  await fetch('/api/refresh', {method: 'POST'});
  document.getElementById('lastRefresh').textContent = 'refreshing…';
  setTimeout(load, 8000);
};
load();
setInterval(load, 60000);
