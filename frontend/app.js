/* =========================================================
   ОАТИ · Геоаналитика — фронтенд (vanilla JS)
   Стиль: Yandex DataLens
   ========================================================= */

const API = '';

const STATUS_ORDER = ['ok', 'warn', 'violation', 'critical', 'pending', 'unknown'];
const STATUS_LABELS = {
  ok: 'Норма', warn: 'Замечание', violation: 'Нарушение',
  critical: 'Критическое', pending: 'На проверке', unknown: 'Неизвестно',
};
// DataLens-палитра
const STATUS_COLORS = {
  ok: '#22c55e', warn: '#f59e0b', violation: '#ef4444',
  critical: '#ec4899', pending: '#3b82f6', unknown: '#9ca3af',
};

/* =========================================================
   STATE
   ========================================================= */
const state = {
  mode: 'points',
  showDistricts: true,
  statusFilter: new Set(STATUS_ORDER),
  districtFilter: new Set(),
  typeFilter: new Set(),
  dateFrom: null,
  dateTo: null,
  loadDebounce: null,
  choroplethMetric: 'density',
  timeseries: null,
  timesliderActive: false,
  timesliderPlaying: false,
  timesliderIndex: 0,
  timesliderTimer: null,
  compareMode: false,
  compareDateFromA: null,
  compareDateToA: null,
  compareDateFromB: null,
  compareDateToB: null,
  useViewportBbox: false,
};

/* =========================================================
   API
   ========================================================= */
function buildQuery(overrides = {}) {
  const p = new URLSearchParams();
  for (const s of state.statusFilter) p.append('statuses', s);
  for (const d of state.districtFilter) p.append('district_ids', d);
  for (const t of state.typeFilter) p.append('types', t);
  const dateFrom = overrides.dateFrom !== undefined ? overrides.dateFrom : state.dateFrom;
  const dateTo = overrides.dateTo !== undefined ? overrides.dateTo : state.dateTo;
  if (dateFrom) p.set('date_from', dateFrom);
  if (dateTo) p.set('date_to', dateTo);
  if (state.useViewportBbox && !overrides.skipBbox) {
    const b = map.getBounds();
    p.set('bbox', `${b.getWest()},${b.getSouth()},${b.getEast()},${b.getNorth()}`);
  }
  return p.toString();
}

async function api(path, opts = {}) {
  const r = await fetch(API + path, opts);
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { const j = await r.json(); msg = j.detail || j.message || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

function showLoading(on) {
  document.getElementById('loading').style.display = on ? 'flex' : 'none';
}

/* =========================================================
   КАРТА
   ========================================================= */
const map = L.map('map', {
  center: [55.7558, 37.6173],
  zoom: 10,
  zoomControl: true,
  preferCanvas: true,
});

// === ПОДЛОЖКИ КАРТЫ ===
// Все подложки, доступные пользователю. Каждая — { name, url, attribution, options }
// Для добавления своей (2ГИС/Яндекс с API-ключом) — см. блок в конце этой секции.
const BASE_LAYERS = {
  'voyager': {
    name: 'CARTO Voyager (дашборд)',
    url: 'https://{s}.basemaps.cartocdn.com/voyager/{z}/{x}/{y}{r}.png',
    attribution: '&copy; OpenStreetMap, &copy; CARTO',
    options: { subdomains: 'abcd', maxZoom: 19 },
  },
  'osm': {
    name: 'OpenStreetMap (улицы, дома)',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; OpenStreetMap contributors',
    options: { maxZoom: 19 },
  },
  'positron': {
    name: 'CARTO Positron (лёгкая)',
    url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
    attribution: '&copy; OpenStreetMap, &copy; CARTO',
    options: { subdomains: 'abcd', maxZoom: 19 },
  },
  'osm-hot': {
    name: 'OSM Humanitarian',
    url: 'https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png',
    attribution: '&copy; OpenStreetMap, HOT',
    options: { subdomains: 'abc', maxZoom: 19 },
  },
  'satellite': {
    name: 'Спутник (Esri)',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics',
    options: { maxZoom: 19 },
  },
  // === ДОБАВИТЬ 2ГИС / ЯНДЕКС ===
  // Для коммерческих провайдеров нужен API-ключ. Раскомментируй блок и подставь.
  //
  // '2gis': {
  //   name: '2ГИС',
  //   url: 'https://tile{s}.maps.2gis.com/tiles?x={x}&y={y}&z={z}&v=1.5',
  //   attribution: '&copy; 2ГИС',
  //   options: { subdomains: '0123', maxZoom: 19 },
  // },
  //
  // Яндекс: лучше через официальный JS API (https://yandex.ru/dev/maps/), но
  // для простого raster есть прокси-варианты. Подключение через API:
  // 1. Получить ключ на https://developer.tech.yandex.ru
  // 2. Поставить @yandex/leaflet-yandex-mobile-helper или использовать L.GridLayer
  // 3. Заменить инициализацию map (см. README раздел "Подключение Яндекс Карт")
};

let currentLayerKey = localStorage.getItem('oati_base_layer') || 'voyager';
let currentTileLayer = null;

function applyBaseLayer(key) {
  const cfg = BASE_LAYERS[key];
  if (!cfg) return;
  if (currentTileLayer) map.removeLayer(currentTileLayer);
  currentTileLayer = L.tileLayer(cfg.url, {
    attribution: cfg.attribution,
    ...cfg.options,
  });
  currentTileLayer.addTo(map);
  currentLayerKey = key;
  localStorage.setItem('oati_base_layer', key);
}

applyBaseLayer(currentLayerKey);

const clusterLayer = L.markerClusterGroup({
  showCoverageOnHover: false,
  spiderfyOnMaxZoom: true,
  maxClusterRadius: 60,
  chunkedLoading: true,
});
const markersLayer = L.layerGroup();
const serverClusterLayer = L.layerGroup();
let heatLayer = null;
let districtsGeoLayer = null;

function clearAllMapLayers() {
  clusterLayer.clearLayers();
  markersLayer.clearLayers();
  serverClusterLayer.clearLayers();
  map.removeLayer(clusterLayer);
  map.removeLayer(markersLayer);
  map.removeLayer(serverClusterLayer);
  if (heatLayer) { map.removeLayer(heatLayer); heatLayer = null; }
}

/* =========================================================
   ОКРУГА
   ========================================================= */
async function loadDistrictsLayer() {
  try {
    const geo = await api('/api/districts/geojson');
    districtsGeoLayer = L.geoJSON(geo, {
      style: feature => baseDistrictStyle(feature),
      onEachFeature: (feature, layer) => {
        const p = feature.properties;
        layer.bindTooltip(`${p.code} · ${p.name}`, { sticky: true, direction: 'top' });
        layer.on('click', () => {
          if (state.mode === 'choropleth') return;
          toggleDistrict(p.id);
        });
      },
    });
    if (state.showDistricts) districtsGeoLayer.addTo(map);
  } catch (e) {
    showToast('Не удалось загрузить округа: ' + e.message, 'err');
  }
}

function baseDistrictStyle(feature) {
  const isActive = state.districtFilter.has(feature.properties.id);
  const soloMode = state.districtFilter.size > 0;
  return {
    color: isActive ? '#4070dc' : '#5b8def',
    weight: isActive ? 2.5 : 1.2,
    fillColor: '#5b8def',
    fillOpacity: isActive ? 0.18 : (soloMode ? 0.02 : 0.05),
    opacity: 0.5,
  };
}

function refreshDistrictsStyle() {
  if (!districtsGeoLayer) return;
  districtsGeoLayer.eachLayer(l => l.setStyle(baseDistrictStyle(l.feature)));
}

/* =========================================================
   ОТРИСОВКА КАРТЫ
   ========================================================= */
async function renderMap() {
  clearAllMapLayers();
  switch (state.mode) {
    case 'points':
    case 'clusters':
      await renderPointsOrClusters();
      break;
    case 'heat':
      await renderHeatmap();
      break;
    case 'choropleth':
      await renderChoropleth();
      break;
  }
  if (state.showDistricts && districtsGeoLayer) {
    districtsGeoLayer.bringToFront();
  }
}

async function renderPointsOrClusters() {
  if (state.mode === 'clusters') {
    const zoom = map.getZoom();
    const eps = zoom < 11 ? 0.008 : zoom < 13 ? 0.004 : 0.002;
    const data = await api('/api/objects/cluster?eps=' + eps + '&min_points=3&' + buildQuery());

    for (const c of data.clusters) {
      const size = Math.min(58, Math.max(30, 20 + Math.sqrt(c.count) * 4));
      const icon = L.divIcon({
        className: '',
        html: `<div class="server-cluster" style="background:${c.color};width:${size}px;height:${size}px;">${c.count}</div>`,
        iconSize: [size, size],
        iconAnchor: [size/2, size/2],
      });
      const m = L.marker([c.lat, c.lon], { icon });
      m.on('click', () => {
        map.flyTo([c.lat, c.lon], Math.min(16, map.getZoom() + 2));
      });
      serverClusterLayer.addLayer(m);
    }
    map.addLayer(serverClusterLayer);
    return;
  }

  const geo = await api('/api/objects/geojson?' + buildQuery());
  const features = geo.features || [];

  const markers = features.map(f => {
    const [lon, lat] = f.geometry.coordinates;
    const p = f.properties;
    const icon = L.divIcon({
      className: '',
      html: `<div class="obj-marker" style="background:${p.status_color}"></div>`,
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    });
    const m = L.marker([lat, lon], { icon });
    m.on('click', () => openObjectPopup(m, p.id));
    return m;
  });

  if (markers.length) {
    markers.forEach(m => markersLayer.addLayer(m));
    map.addLayer(markersLayer);
  }
}

async function renderHeatmap() {
  const geo = await api('/api/objects/geojson?' + buildQuery());
  const features = geo.features || [];
  if (!features.length) return;

  const intensity = { critical: 1.0, violation: 0.8, warn: 0.5, pending: 0.4, ok: 0.15, unknown: 0.2 };
  const points = features.map(f => {
    const [lon, lat] = f.geometry.coordinates;
    return [lat, lon, intensity[f.properties.status] ?? 0.5];
  });
  heatLayer = L.heatLayer(points, {
    radius: 30, blur: 24, minOpacity: 0.4, maxZoom: 14,
    gradient: { 0.0:'#3b82f6', 0.3:'#22c55e', 0.5:'#f59e0b', 0.7:'#ef4444', 1.0:'#ec4899' },
  });
  map.addLayer(heatLayer);
}

async function renderChoropleth() {
  if (!districtsGeoLayer) return;
  const data = await api(`/api/objects/choropleth?metric=${state.choroplethMetric}&` + buildQuery());
  const valueByDistrict = {};
  let maxVal = 0;
  for (const row of data.data) {
    valueByDistrict[row.district_id] = row;
    if (row.value > maxVal) maxVal = row.value;
  }

  districtsGeoLayer.eachLayer(layer => {
    const id = layer.feature.properties.id;
    const row = valueByDistrict[id];
    const value = row ? row.value : 0;
    const ratio = maxVal > 0 ? value / maxVal : 0;
    layer.setStyle({
      color: 'white',
      weight: 1.5,
      fillColor: colorScale(ratio),
      fillOpacity: 0.78,
      opacity: 1,
    });
    const valueText = state.choroplethMetric === 'critical_ratio'
      ? (value * 100).toFixed(1) + '%'
      : value.toLocaleString('ru');
    layer.bindTooltip(
      `<b>${layer.feature.properties.code}</b> · ${layer.feature.properties.name}: ${valueText}`,
      { sticky: true, direction: 'top' }
    );
  });
  renderChoroplethLegend(maxVal);
}

function colorScale(ratio) {
  const stops = [
    { r: 219, g: 234, b: 254 },
    { r: 96,  g: 165, b: 250 },
    { r: 251, g: 191, b: 36  },
    { r: 239, g: 68,  b: 68  },
    { r: 236, g: 72,  b: 153 },
  ];
  const idx = Math.min(stops.length - 2, Math.floor(ratio * (stops.length - 1)));
  const t = ratio * (stops.length - 1) - idx;
  const a = stops[idx], b = stops[idx + 1];
  return `rgb(${Math.round(a.r + (b.r - a.r) * t)},${Math.round(a.g + (b.g - a.g) * t)},${Math.round(a.b + (b.b - a.b) * t)})`;
}

function renderChoroplethLegend(maxVal) {
  const legend = document.getElementById('legend');
  const titles = {
    density: 'Плотность объектов',
    violations: 'Число нарушений',
    critical_ratio: 'Доля нарушений',
  };
  const formatMax = state.choroplethMetric === 'critical_ratio'
    ? (maxVal * 100).toFixed(1) + '%'
    : Math.round(maxVal).toLocaleString('ru');

  document.getElementById('legend-body').innerHTML = `
    <div style="font-size:11px;color:var(--text-muted);font-weight:500;margin-bottom:4px">${titles[state.choroplethMetric]}</div>
    <div class="legend-gradient" style="background:linear-gradient(90deg, rgb(219,234,254), rgb(96,165,250), rgb(251,191,36), rgb(239,68,68), rgb(236,72,153))"></div>
    <div class="legend-scale"><span>0</span><span>${formatMax}</span></div>
  `;
  legend.style.display = '';
}

/* =========================================================
   POPUP ОБЪЕКТА
   ========================================================= */
async function openObjectPopup(marker, objectId) {
  try {
    const obj = await api(`/api/objects/${objectId}`);
    marker.bindPopup(popupContent(obj)).openPopup();
  } catch (e) {
    marker.bindPopup(`<div class="popup-card"><h4>Ошибка</h4>${escapeHTML(e.message)}</div>`).openPopup();
  }
}

function popupContent(obj) {
  const fields = [];
  if (obj.type) fields.push(['Тип', obj.type]);
  if (obj.address) fields.push(['Адрес', obj.address]);
  if (obj.district_name) fields.push(['Округ', obj.district_name]);
  if (obj.last_check_date) fields.push(['Проверка', obj.last_check_date]);
  if (obj.inspector) fields.push(['Инспектор', obj.inspector]);
  if (obj.note) fields.push(['Примечание', obj.note]);
  fields.push(['Координаты', `${obj.lat.toFixed(5)}, ${obj.lon.toFixed(5)}`]);

  let history = '';
  if (obj.inspections && obj.inspections.length > 0) {
    history = `
      <div class="history">
        <div class="history-title">История проверок · ${obj.inspections.length}</div>
        ${obj.inspections.slice(0, 6).map(i => `
          <div class="history-item">
            <strong style="color:${STATUS_COLORS[i.status] || '#888'}">${i.check_date}</strong>
            · ${i.status_label}${i.inspector ? ' · ' + escapeHTML(i.inspector) : ''}
            ${i.note ? `<div style="color:var(--text-muted);margin-top:2px">${escapeHTML(i.note)}</div>` : ''}
          </div>
        `).join('')}
      </div>`;
  }

  return `
    <div class="popup-card">
      <h4>${escapeHTML(obj.name)}</h4>
      <div class="status-tag" style="background:${obj.status_color}1a;color:${obj.status_color}">
        <span class="tag-dot" style="background:${obj.status_color}"></span>${obj.status_label}
      </div>
      ${fields.map(([k, v]) => `<div class="field"><span>${k}</span><span>${escapeHTML(v)}</span></div>`).join('')}
      ${history}
    </div>
  `;
}

function escapeHTML(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
  );
}

/* =========================================================
   ФИЛЬТРЫ
   ========================================================= */
function renderStatusFilters(byStatus) {
  const container = document.getElementById('status-filters');
  container.innerHTML = '';
  const keys = STATUS_ORDER.filter(k => byStatus[k]);
  for (const key of keys) {
    const pill = document.createElement('div');
    pill.className = 'status-pill' + (state.statusFilter.has(key) ? '' : ' off');
    pill.innerHTML = `
      <span class="label">
        <span class="dot" style="background:${STATUS_COLORS[key]}"></span>
        ${STATUS_LABELS[key]}
      </span>
      <span class="num">${byStatus[key]}</span>
    `;
    pill.addEventListener('click', () => {
      if (state.statusFilter.has(key)) state.statusFilter.delete(key);
      else state.statusFilter.add(key);
      pill.classList.toggle('off');
      scheduleReload();
    });
    container.appendChild(pill);
  }
  document.getElementById('status-count').textContent = keys.length;
}

function renderDistrictFilters(byDistrict) {
  const container = document.getElementById('district-filters');
  container.innerHTML = '';
  document.getElementById('districts-reset').style.display =
    state.districtFilter.size > 0 ? '' : 'none';

  for (const d of byDistrict) {
    const pill = document.createElement('div');
    const isActive = state.districtFilter.has(d.id);
    pill.className = 'district-pill' + (isActive ? ' solo' : '');
    pill.innerHTML = `
      <span class="label">
        <span class="code">${d.code}</span>
        ${d.name}
      </span>
      <span class="num">${d.count}</span>
    `;
    pill.addEventListener('click', () => toggleDistrict(d.id));
    container.appendChild(pill);
  }
}

function toggleDistrict(id) {
  if (state.districtFilter.has(id)) state.districtFilter.delete(id);
  else state.districtFilter.add(id);
  if (state.mode !== 'choropleth') refreshDistrictsStyle();
  scheduleReload();
}

function renderTypeFilters(byType) {
  const section = document.getElementById('type-section');
  const container = document.getElementById('type-filters');
  container.innerHTML = '';
  const entries = Object.entries(byType);
  if (entries.length === 0) {
    section.style.display = 'none';
    return;
  }
  section.style.display = '';
  const allActive = state.typeFilter.size === 0;
  for (const [t, c] of entries) {
    const pill = document.createElement('div');
    const active = allActive || state.typeFilter.has(t);
    pill.className = 'status-pill' + (active ? '' : ' off');
    pill.innerHTML = `<span class="label">${escapeHTML(t)}</span><span class="num">${c}</span>`;
    pill.addEventListener('click', () => {
      if (state.typeFilter.size === 0) {
        entries.forEach(([k]) => state.typeFilter.add(k));
      }
      if (state.typeFilter.has(t)) state.typeFilter.delete(t);
      else state.typeFilter.add(t);
      if (state.typeFilter.size === entries.length) state.typeFilter.clear();
      scheduleReload();
    });
    container.appendChild(pill);
  }
}

function renderStats(stats) {
  let ok = 0, warn = 0, bad = 0;
  for (const [k, v] of Object.entries(stats.by_status)) {
    if (k === 'ok') ok += v;
    else if (k === 'warn') warn += v;
    else if (k === 'violation' || k === 'critical') bad += v;
  }
  document.getElementById('stat-total').textContent = stats.total.toLocaleString('ru');
  document.getElementById('stat-ok').textContent = ok.toLocaleString('ru');
  document.getElementById('stat-warn').textContent = warn.toLocaleString('ru');
  document.getElementById('stat-bad').textContent = bad.toLocaleString('ru');
  document.getElementById('stat-visible').textContent = stats.visible.toLocaleString('ru');
}

function renderLegend(byStatus) {
  if (state.mode === 'choropleth') return;
  const items = STATUS_ORDER
    .filter(k => byStatus[k])
    .map(k => `<div class="legend-row"><span class="dot" style="background:${STATUS_COLORS[k]}"></span>${STATUS_LABELS[k]}</div>`);
  const legend = document.getElementById('legend');
  document.getElementById('legend-body').innerHTML = `<h4>Условные обозначения</h4>` + items.join('');
  legend.style.display = items.length ? '' : 'none';
}

/* =========================================================
   ГЛАВНАЯ ПЕРЕЗАГРУЗКА
   ========================================================= */
function scheduleReload() {
  clearTimeout(state.loadDebounce);
  state.loadDebounce = setTimeout(reloadData, 150);
}

async function reloadData() {
  showLoading(true);
  try {
    const qs = buildQuery();
    const stats = await api('/api/objects/stats?' + qs);
    renderStats(stats);
    renderDistrictFilters(stats.by_district);
    renderTypeFilters(stats.by_type);
    renderStatusFilters(stats.by_status);
    renderLegend(stats.by_status);

    document.getElementById('empty-state').style.display =
      stats.total === 0 ? '' : 'none';

    if (stats.total > 0) {
      await renderMap();
    } else {
      clearAllMapLayers();
      if (state.mode === 'choropleth') refreshDistrictsStyle();
    }

    if (document.querySelector('.view-analytics').classList.contains('active')) {
      await renderDashboard(stats);
    }
  } catch (e) {
    showToast('Ошибка загрузки: ' + e.message, 'err');
  } finally {
    showLoading(false);
  }
}

/* =========================================================
   ПЕРЕКЛЮЧАТЕЛЬ ПОДЛОЖЕК
   ========================================================= */
(function initBaseLayerSelect() {
  const sel = document.getElementById('base-layer-select');
  if (!sel) return;
  for (const [key, cfg] of Object.entries(BASE_LAYERS)) {
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = cfg.name;
    if (key === currentLayerKey) opt.selected = true;
    sel.appendChild(opt);
  }
  sel.addEventListener('change', e => {
    applyBaseLayer(e.target.value);
    // Слой округов и маркеры на месте, тайлы поменялись
  });
})();

/* =========================================================
   РЕЖИМЫ КАРТЫ
   ========================================================= */
document.querySelectorAll('#map-mode .radio-row').forEach(row => {
  row.addEventListener('click', () => {
    document.querySelectorAll('#map-mode .radio-row').forEach(r => r.classList.remove('active'));
    row.classList.add('active');
    row.querySelector('input').checked = true;
    state.mode = row.dataset.mode;
    document.getElementById('choropleth-options').style.display =
      state.mode === 'choropleth' ? '' : 'none';
    if (state.mode !== 'choropleth') refreshDistrictsStyle();
    scheduleReload();
  });
});

document.getElementById('choropleth-metric').addEventListener('change', e => {
  state.choroplethMetric = e.target.value;
  if (state.mode === 'choropleth') scheduleReload();
});

document.querySelectorAll('.toggle-row').forEach(row => {
  row.addEventListener('click', () => {
    const layer = row.dataset.layer;
    row.classList.toggle('active');
    if (layer === 'districts') {
      state.showDistricts = row.classList.contains('active');
      if (state.showDistricts && districtsGeoLayer) districtsGeoLayer.addTo(map);
      else if (districtsGeoLayer) map.removeLayer(districtsGeoLayer);
    }
  });
});

/* =========================================================
   ДАТЫ
   ========================================================= */
document.getElementById('date-from').addEventListener('change', e => {
  state.dateFrom = e.target.value || null;
  scheduleReload();
});
document.getElementById('date-to').addEventListener('change', e => {
  state.dateTo = e.target.value || null;
  scheduleReload();
});
document.querySelectorAll('[data-quick]').forEach(btn => {
  btn.addEventListener('click', () => {
    const days = +btn.dataset.quick;
    if (days === 0) {
      state.dateFrom = null;
      state.dateTo = null;
      document.getElementById('date-from').value = '';
      document.getElementById('date-to').value = '';
    } else {
      const to = new Date();
      const from = new Date(Date.now() - days * 86400000);
      state.dateFrom = from.toISOString().slice(0, 10);
      state.dateTo = to.toISOString().slice(0, 10);
      document.getElementById('date-from').value = state.dateFrom;
      document.getElementById('date-to').value = state.dateTo;
    }
    scheduleReload();
  });
});

document.getElementById('districts-reset').addEventListener('click', () => {
  state.districtFilter.clear();
  refreshDistrictsStyle();
  scheduleReload();
});

/* =========================================================
   ИМПОРТ
   ========================================================= */
const fileInput = document.getElementById('file-input');
const dropzone = document.getElementById('dropzone');

fileInput.addEventListener('change', e => {
  if (e.target.files[0]) uploadFile(e.target.files[0]);
});
dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('drag'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('drag'));
dropzone.addEventListener('drop', e => {
  e.preventDefault();
  dropzone.classList.remove('drag');
  if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
});

async function uploadFile(file) {
  const fd = new FormData();
  fd.append('file', file);
  const replace = document.getElementById('replace-mode').checked;
  showLoading(true);
  try {
    const res = await api(`/api/import/file?replace=${replace}`, { method: 'POST', body: fd });
    showToast(res.message, 'success');
    await reloadData();
    await fitToData();
  } catch (e) {
    showToast(e.message, 'err');
  } finally {
    showLoading(false);
    fileInput.value = '';
  }
}

document.getElementById('btn-demo').addEventListener('click', async () => {
  const replace = document.getElementById('replace-mode').checked;
  showLoading(true);
  try {
    const res = await api(`/api/import/demo?count=500&replace=${replace}`, { method: 'POST' });
    showToast(res.message, 'success');
    await reloadData();
    await fitToData();
  } catch (e) {
    showToast(e.message, 'err');
  } finally {
    showLoading(false);
  }
});

document.getElementById('btn-template').addEventListener('click', () => {
  window.location.href = '/api/import/template';
});

document.getElementById('btn-export').addEventListener('click', () => {
  window.location.href = '/api/objects/export?' + buildQuery();
});

document.getElementById('btn-clear').addEventListener('click', async () => {
  if (!confirm('Удалить все объекты из базы данных?')) return;
  try {
    await api('/api/objects/', { method: 'DELETE' });
    state.districtFilter.clear();
    state.typeFilter.clear();
    await reloadData();
    showToast('База очищена', 'success');
  } catch (e) {
    showToast(e.message, 'err');
  }
});

/* === Загрузка из data.mos.ru === */
(async function initMosDatasets() {
  try {
    const list = await api('/api/import/mos-datasets');
    const sel = document.getElementById('mos-dataset-select');
    if (!sel) return;
    for (const ds of list) {
      const opt = document.createElement('option');
      opt.value = ds.id;
      opt.textContent = `${ds.name}`;
      opt.title = ds.description || '';
      sel.appendChild(opt);
    }
  } catch (e) { /* silent */ }
})();

document.getElementById('btn-mos-load').addEventListener('click', async () => {
  const datasetId = document.getElementById('mos-dataset-select').value;
  if (!datasetId) {
    showToast('Выберите датасет', 'err');
    return;
  }
  const apiKey = document.getElementById('mos-api-key').value.trim();
  const replace = document.getElementById('replace-mode').checked;
  const params = new URLSearchParams({
    dataset_id: datasetId,
    limit: 500,
    replace: replace,
  });
  if (apiKey) params.set('api_key', apiKey);

  showLoading(true);
  showToast('Загружаю с data.mos.ru, это займёт 30-60 секунд...', 'success');
  try {
    const res = await api('/api/import/mos?' + params, { method: 'POST' });
    showToast(res.message, 'success');
    await reloadData();
    await fitToData();
  } catch (e) {
    showToast(e.message, 'err');
  } finally {
    showLoading(false);
  }
});

async function fitToData() {
  try {
    const geo = await api('/api/objects/geojson?' + buildQuery() + '&limit=10000');
    if (!geo.features.length) return;
    const bounds = L.latLngBounds(geo.features.map(f => [f.geometry.coordinates[1], f.geometry.coordinates[0]]));
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 13 });
  } catch (e) { /* silent */ }
}

/* =========================================================
   ТАБЫ
   ========================================================= */
document.querySelectorAll('.view-tabs .tab').forEach(tab => {
  tab.addEventListener('click', async () => {
    document.querySelectorAll('.view-tabs .tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    const view = tab.dataset.view;
    document.querySelector('.view-map').classList.toggle('active', view === 'map');
    document.querySelector('.view-analytics').classList.toggle('active', view === 'analytics');
    if (view === 'map') {
      setTimeout(() => map.invalidateSize(), 50);
    } else {
      const stats = await api('/api/objects/stats?' + buildQuery());
      await renderDashboard(stats);
    }
  });
});

/* =========================================================
   ДАШБОРД
   ========================================================= */
async function renderDashboard(stats) {
  // KPI плитки
  let ok = 0, warn = 0, bad = 0;
  for (const [k, v] of Object.entries(stats.by_status)) {
    if (k === 'ok') ok += v;
    else if (k === 'warn') warn += v;
    else if (k === 'violation' || k === 'critical') bad += v;
  }
  const total = stats.total;
  document.getElementById('dash-total').textContent = total.toLocaleString('ru');
  document.getElementById('dash-ok').textContent = ok.toLocaleString('ru');
  document.getElementById('dash-warn').textContent = warn.toLocaleString('ru');
  document.getElementById('dash-bad').textContent = bad.toLocaleString('ru');
  document.getElementById('dash-ok-pct').textContent = total ? `${((ok/total)*100).toFixed(1)}% от общего` : '— от общего';
  document.getElementById('dash-warn-pct').textContent = total ? `${((warn/total)*100).toFixed(1)}% от общего` : '— от общего';
  document.getElementById('dash-bad-pct').textContent = total ? `${((bad/total)*100).toFixed(1)}% от общего` : '— от общего';

  // 1. Статусы
  drawBarChart('chart-statuses',
    STATUS_ORDER.filter(k => stats.by_status[k]).map(k => ({
      label: STATUS_LABELS[k],
      value: stats.by_status[k],
      color: STATUS_COLORS[k],
    }))
  );

  // 2. Топ округов по нарушениям
  const violationsData = await api('/api/objects/choropleth?metric=violations');
  drawBarChart('chart-districts',
    violationsData.data
      .filter(d => d.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 12)
      .map(d => ({ label: d.code, value: d.value, color: STATUS_COLORS.violation })),
    { horizontal: true }
  );

  // 3. Типы объектов
  const types = Object.entries(stats.by_type)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10);
  drawBarChart('chart-types',
    types.map(([t, c]) => ({ label: t, value: c, color: STATUS_COLORS.pending })),
    { horizontal: true }
  );

  // 4. Тайм-серия
  const ts = await api('/api/objects/timeseries?bucket=month');
  drawTimelineChart('chart-timeline', ts.data);

  // 5. Прогноз
  await renderForecast();

  // 6. Таблица округов
  const fullDistricts = await api('/api/objects/choropleth?metric=critical_ratio');
  renderDistrictsTable(fullDistricts.data, stats.by_district);

  // 7. Инспекторы
  await renderInspectorsTable();
}

async function renderInspectorsTable() {
  const tbody = document.querySelector('#inspectors-table tbody');
  if (!tbody) return;
  tbody.innerHTML = '';
  try {
    const res = await api('/api/objects/inspectors');
    if (!res.inspectors || !res.inspectors.length) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:24px">
        Нет данных по инспекторам. Импортируйте данные с колонкой «инспектор».
      </td></tr>`;
      return;
    }
    for (const ins of res.inspectors) {
      const tr = document.createElement('tr');
      // Раскраска доли нарушений
      const rate = ins.violation_rate;
      let rateColor = 'var(--status-ok)';
      if (rate >= 40) rateColor = 'var(--status-violation)';
      else if (rate >= 20) rateColor = 'var(--status-warn)';

      const interval = ins.avg_interval_days !== null
        ? `${ins.avg_interval_days} дн`
        : '—';
      const lastCheck = ins.last_check
        ? new Date(ins.last_check).toLocaleDateString('ru-RU')
        : '—';

      tr.innerHTML = `
        <td><strong>${escapeHTML(ins.inspector)}</strong></td>
        <td class="num">${ins.total_checks}</td>
        <td class="num">${ins.unique_objects}</td>
        <td class="num" style="color:var(--status-violation)">${ins.violations}</td>
        <td class="bar-cell">
          <div class="bar" style="width:${Math.min(100, rate) * 0.8}%; background:${rateColor}"></div>
          <span class="bar-text">${rate.toFixed(1)}%</span>
        </td>
        <td class="num">${interval}</td>
        <td>${lastCheck}</td>
      `;
      tbody.appendChild(tr);
    }
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--status-violation)">
      Ошибка загрузки: ${escapeHTML(e.message)}
    </td></tr>`;
  }
}

function roundRect(ctx, x, y, w, h, radii) {
  const [tl, tr, br, bl] = radii;
  ctx.beginPath();
  ctx.moveTo(x + tl, y);
  ctx.lineTo(x + w - tr, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + tr);
  ctx.lineTo(x + w, y + h - br);
  ctx.quadraticCurveTo(x + w, y + h, x + w - br, y + h);
  ctx.lineTo(x + bl, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - bl);
  ctx.lineTo(x, y + tl);
  ctx.quadraticCurveTo(x, y, x + tl, y);
  ctx.closePath();
}

function drawBarChart(canvasId, data, opts = {}) {
  const canvas = document.getElementById(canvasId);
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, rect.width, rect.height);

  if (!data.length) {
    ctx.fillStyle = '#9ca3af';
    ctx.font = '12px Inter';
    ctx.fillText('Нет данных', 10, 20);
    return;
  }

  const max = Math.max(...data.map(d => d.value));
  const pad = { l: opts.horizontal ? 110 : 32, r: 20, t: 8, b: opts.horizontal ? 8 : 50 };
  const W = rect.width - pad.l - pad.r;
  const H = rect.height - pad.t - pad.b;

  if (opts.horizontal) {
    const barH = Math.min(22, H / data.length - 6);
    data.forEach((d, i) => {
      const y = pad.t + i * (H / data.length) + (H / data.length - barH) / 2;
      const w = (d.value / max) * W;
      // фон
      ctx.fillStyle = '#f3f4f6';
      roundRect(ctx, pad.l, y, W, barH, [3, 3, 3, 3]);
      ctx.fill();
      // активный бар
      const grad = ctx.createLinearGradient(pad.l, 0, pad.l + w, 0);
      grad.addColorStop(0, d.color);
      grad.addColorStop(1, d.color + 'cc');
      ctx.fillStyle = grad;
      roundRect(ctx, pad.l, y, Math.max(w, 2), barH, [3, 3, 3, 3]);
      ctx.fill();
      // подписи
      ctx.fillStyle = '#4b5563';
      ctx.font = '500 11px Inter';
      ctx.textBaseline = 'middle';
      ctx.textAlign = 'right';
      const label = d.label.length > 16 ? d.label.slice(0, 15) + '…' : d.label;
      ctx.fillText(label, pad.l - 10, y + barH/2);
      ctx.textAlign = 'left';
      ctx.fillStyle = '#1f2937';
      ctx.font = '600 11px JetBrains Mono';
      ctx.fillText(d.value.toLocaleString('ru'), pad.l + w + 6, y + barH/2);
    });
  } else {
    const barW = W / data.length * 0.55;
    const gap = (W / data.length) * 0.45;
    // сетка
    ctx.strokeStyle = '#f3f4f6';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = pad.t + (H / 4) * i;
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(pad.l + W, y);
      ctx.stroke();
      ctx.fillStyle = '#9ca3af';
      ctx.font = '10px JetBrains Mono';
      ctx.textAlign = 'right';
      ctx.fillText(Math.round(max * (1 - i/4)), pad.l - 6, y + 3);
    }
    data.forEach((d, i) => {
      const x = pad.l + i * (W / data.length) + gap/2;
      const h = (d.value / max) * H;
      const y = pad.t + H - h;
      const grad = ctx.createLinearGradient(0, y, 0, y + h);
      grad.addColorStop(0, d.color);
      grad.addColorStop(1, d.color + 'bb');
      ctx.fillStyle = grad;
      roundRect(ctx, x, y, barW, h, [4, 4, 0, 0]);
      ctx.fill();
      // значение
      ctx.fillStyle = '#1f2937';
      ctx.font = '600 10px JetBrains Mono';
      ctx.textAlign = 'center';
      ctx.fillText(d.value, x + barW/2, y - 5);
      // подпись
      ctx.fillStyle = '#6b7280';
      ctx.font = '500 10px Inter';
      const label = d.label.length > 10 ? d.label.slice(0, 9) + '…' : d.label;
      ctx.save();
      ctx.translate(x + barW/2, pad.t + H + 8);
      ctx.rotate(-Math.PI / 7);
      ctx.textAlign = 'right';
      ctx.fillText(label, 0, 6);
      ctx.restore();
    });
  }
}

function drawTimelineChart(canvasId, data) {
  const canvas = document.getElementById(canvasId);
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, rect.width, rect.height);

  if (!data.length) {
    ctx.fillStyle = '#9ca3af';
    ctx.font = '12px Inter';
    ctx.fillText('Нет проверок с датами', 10, 20);
    return;
  }

  const pad = { l: 40, r: 20, t: 14, b: 32 };
  const W = rect.width - pad.l - pad.r;
  const H = rect.height - pad.t - pad.b;
  const max = Math.max(...data.map(d => d.total));

  // сетка
  ctx.strokeStyle = '#f3f4f6';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (H / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(pad.l + W, y);
    ctx.stroke();
    ctx.fillStyle = '#9ca3af';
    ctx.font = '10px JetBrains Mono';
    ctx.textAlign = 'right';
    ctx.fillText(Math.round(max * (1 - i/4)), pad.l - 6, y + 3);
  }

  const statusKeys = ['ok', 'warn', 'violation', 'critical', 'pending'];
  const barW = Math.max(4, W / data.length - 3);

  data.forEach((d, i) => {
    const x = pad.l + (W / data.length) * i + (W / data.length - barW) / 2;
    let yBase = pad.t + H;
    for (const key of statusKeys) {
      const v = d[key] || 0;
      if (v === 0) continue;
      const h = (v / max) * H;
      ctx.fillStyle = STATUS_COLORS[key];
      ctx.fillRect(x, yBase - h, barW, h);
      yBase -= h;
    }
  });

  const step = Math.ceil(data.length / 10);
  ctx.fillStyle = '#6b7280';
  ctx.font = '500 10px Inter';
  ctx.textAlign = 'center';
  data.forEach((d, i) => {
    if (i % step !== 0) return;
    const x = pad.l + (W / data.length) * i + (W / data.length) / 2;
    const dt = new Date(d.period);
    const label = `${(dt.getMonth() + 1).toString().padStart(2,'0')}.${(dt.getFullYear() % 100).toString().padStart(2,'0')}`;
    ctx.fillText(label, x, pad.t + H + 16);
  });
}

function renderDistrictsTable(ratioData, countData) {
  const tbody = document.querySelector('#districts-table tbody');
  tbody.innerHTML = '';
  // Достанем расширенную статистику по каждому округу
  // ratioData содержит total/bad, нам ещё нужны ok и warn — придётся отдельным запросом

  Promise.all([
    api('/api/objects/stats?district_ids=' + ratioData.map(r => r.district_id).join('&district_ids=')),
    Promise.resolve(ratioData),
  ]).then(([_, ratio]) => {
    // Простой fallback — рисуем то, что есть
    for (const row of ratio) {
      const total = row.total;
      const bad = row.bad;
      const ratioPct = (row.value * 100).toFixed(1);
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="code">${row.code}</td>
        <td>${row.name}</td>
        <td class="num">${total}</td>
        <td class="num" style="color:var(--status-ok)">~${Math.max(0, total - bad)}</td>
        <td class="num" style="color:var(--status-warn)">—</td>
        <td class="num" style="color:var(--status-violation)">${bad}</td>
        <td class="progress-cell">
          <div class="progress-bar" style="width:${Math.min(100, row.value * 100) * 0.8}%"></div>
          <span class="progress-text">${ratioPct}%</span>
        </td>
      `;
      tbody.appendChild(tr);
    }
  });
}

/* =========================================================
   ПРОГНОЗ
   ========================================================= */
async function renderForecast() {
  const metric = document.getElementById('forecast-metric').value;
  try {
    const data = await api(`/api/objects/forecast?horizon_months=6&metric=${metric}`);
    drawForecastChart('chart-forecast', data);
    document.getElementById('forecast-trend').textContent =
      data.warning ? data.warning :
      `Тренд: ${data.trend_direction} (${data.trend_slope >= 0 ? '+' : ''}${data.trend_slope}/мес)`;
  } catch (e) {
    /* silent */
  }
}

document.getElementById('forecast-metric').addEventListener('change', renderForecast);

function drawForecastChart(canvasId, data) {
  const canvas = document.getElementById(canvasId);
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, rect.width, rect.height);

  const hist = data.historical || [];
  const fcst = data.forecast || [];
  if (!hist.length) {
    ctx.fillStyle = '#9ca3af';
    ctx.font = '12px Inter';
    ctx.fillText(data.warning || 'Нет данных', 10, 20);
    return;
  }

  const pad = { l: 40, r: 20, t: 15, b: 30 };
  const W = rect.width - pad.l - pad.r;
  const H = rect.height - pad.t - pad.b;
  const allValues = [...hist.map(d => d.value), ...fcst.map(d => d.upper ?? d.value)];
  const max = Math.max(...allValues, 1);
  const totalPoints = hist.length + fcst.length;
  const stepX = W / Math.max(1, totalPoints - 1);

  // сетка
  ctx.strokeStyle = '#f3f4f6';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (H / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(pad.l + W, y);
    ctx.stroke();
    ctx.fillStyle = '#9ca3af';
    ctx.font = '10px JetBrains Mono';
    ctx.textAlign = 'right';
    ctx.fillText(Math.round(max * (1 - i/4)), pad.l - 6, y + 3);
  }

  // разделитель
  if (fcst.length > 0) {
    const xBoundary = pad.l + (hist.length - 1) * stepX;
    ctx.strokeStyle = '#d1d5db';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(xBoundary, pad.t);
    ctx.lineTo(xBoundary, pad.t + H);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = '#6b7280';
    ctx.font = '500 10px Inter';
    ctx.textAlign = 'left';
    ctx.fillText('прогноз →', xBoundary + 6, pad.t + 12);
  }

  // доверительный интервал
  if (fcst.length > 0) {
    ctx.fillStyle = 'rgba(245, 158, 11, 0.15)';
    ctx.beginPath();
    fcst.forEach((d, i) => {
      const x = pad.l + (hist.length - 1 + i) * stepX;
      const y = pad.t + H - (d.upper / max) * H;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    for (let i = fcst.length - 1; i >= 0; i--) {
      const d = fcst[i];
      const x = pad.l + (hist.length - 1 + i) * stepX;
      const y = pad.t + H - (d.lower / max) * H;
      ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fill();
  }

  // история
  ctx.strokeStyle = '#ef4444';
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  hist.forEach((d, i) => {
    const x = pad.l + i * stepX;
    const y = pad.t + H - (d.value / max) * H;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  ctx.fillStyle = '#ef4444';
  hist.forEach((d, i) => {
    const x = pad.l + i * stepX;
    const y = pad.t + H - (d.value / max) * H;
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = 'white';
    ctx.beginPath();
    ctx.arc(x, y, 1.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#ef4444';
  });

  // прогноз
  if (fcst.length > 0) {
    ctx.strokeStyle = '#f59e0b';
    ctx.lineWidth = 2.5;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    const lastHist = hist[hist.length - 1];
    const xStart = pad.l + (hist.length - 1) * stepX;
    const yStart = pad.t + H - (lastHist.value / max) * H;
    ctx.moveTo(xStart, yStart);
    fcst.forEach((d, i) => {
      const x = pad.l + (hist.length + i) * stepX;
      const y = pad.t + H - (d.value / max) * H;
      ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = '#f59e0b';
    fcst.forEach((d, i) => {
      const x = pad.l + (hist.length + i) * stepX;
      const y = pad.t + H - (d.value / max) * H;
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = 'white';
      ctx.beginPath();
      ctx.arc(x, y, 1.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#f59e0b';
    });
  }

  // подписи
  const allPoints = [...hist, ...fcst];
  const labelStep = Math.ceil(allPoints.length / 8);
  ctx.fillStyle = '#6b7280';
  ctx.font = '500 10px Inter';
  ctx.textAlign = 'center';
  allPoints.forEach((d, i) => {
    if (i % labelStep !== 0) return;
    const x = pad.l + i * stepX;
    const dt = new Date(d.period);
    const label = `${(dt.getMonth() + 1).toString().padStart(2,'0')}.${(dt.getFullYear() % 100).toString().padStart(2,'0')}`;
    ctx.fillText(label, x, pad.t + H + 14);
  });
}

/* =========================================================
   ТАЙМ-СЛАЙДЕР
   ========================================================= */
const tsEl = document.getElementById('timeslider');
const tsSlider = document.getElementById('ts-slider');
const tsCurrent = document.getElementById('ts-current');
const tsChart = document.getElementById('ts-chart');

document.getElementById('ts-open').addEventListener('click', openTimeslider);
document.getElementById('ts-close').addEventListener('click', closeTimeslider);
document.getElementById('ts-play').addEventListener('click', togglePlay);
document.getElementById('ts-step-back').addEventListener('click', () => stepTimeslider(-1));
document.getElementById('ts-step-fwd').addEventListener('click', () => stepTimeslider(1));

async function openTimeslider() {
  try {
    const ts = await api('/api/objects/timeseries?bucket=month&' + buildQuery());
    if (!ts.data.length) {
      showToast('Нет данных с датами для хронологии', 'err');
      return;
    }
    state.timeseries = ts.data;
    state.timesliderActive = true;
    state.timesliderIndex = 0;
    tsEl.style.display = '';
    tsSlider.max = ts.data.length - 1;
    tsSlider.value = 0;
    drawTsChart();
    applyTimesliderFilter();
  } catch (e) {
    showToast(e.message, 'err');
  }
}

function closeTimeslider() {
  state.timesliderActive = false;
  state.timesliderPlaying = false;
  clearInterval(state.timesliderTimer);
  tsEl.style.display = 'none';
  state.dateFrom = document.getElementById('date-from').value || null;
  state.dateTo = document.getElementById('date-to').value || null;
  scheduleReload();
}

function togglePlay() {
  state.timesliderPlaying = !state.timesliderPlaying;
  const btn = document.getElementById('ts-play');
  btn.classList.toggle('playing', state.timesliderPlaying);
  btn.textContent = state.timesliderPlaying ? '⏸' : '▶';
  if (state.timesliderPlaying) {
    state.timesliderTimer = setInterval(() => {
      const next = state.timesliderIndex + 1;
      if (next >= state.timeseries.length) {
        togglePlay();
        return;
      }
      state.timesliderIndex = next;
      tsSlider.value = next;
      applyTimesliderFilter();
      drawTsChart();
    }, 800);
  } else {
    clearInterval(state.timesliderTimer);
  }
}

function stepTimeslider(delta) {
  const n = state.timesliderIndex + delta;
  if (n < 0 || n >= state.timeseries.length) return;
  state.timesliderIndex = n;
  tsSlider.value = n;
  applyTimesliderFilter();
  drawTsChart();
}

tsSlider.addEventListener('input', e => {
  state.timesliderIndex = +e.target.value;
  applyTimesliderFilter();
  drawTsChart();
});

function applyTimesliderFilter() {
  const period = state.timeseries[state.timesliderIndex];
  const dt = new Date(period.period);
  tsCurrent.textContent = dt.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' });
  const from = new Date(dt.getFullYear(), dt.getMonth(), 1);
  const to = new Date(dt.getFullYear(), dt.getMonth() + 1, 0);
  state.dateFrom = from.toISOString().slice(0, 10);
  state.dateTo = to.toISOString().slice(0, 10);
  scheduleReload();
}

function drawTsChart() {
  const ctx = tsChart.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = tsChart.getBoundingClientRect();
  tsChart.width = rect.width * dpr;
  tsChart.height = rect.height * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, rect.width, rect.height);

  if (!state.timeseries || !state.timeseries.length) return;
  const data = state.timeseries;
  const max = Math.max(...data.map(d => d.total));
  const W = rect.width;
  const H = rect.height;
  const barW = W / data.length;
  const statusKeys = ['ok', 'warn', 'violation', 'critical', 'pending'];

  data.forEach((d, i) => {
    const x = i * barW;
    let yBase = H;
    for (const key of statusKeys) {
      const v = d[key] || 0;
      if (!v) continue;
      const h = (v / max) * H;
      ctx.fillStyle = STATUS_COLORS[key];
      ctx.globalAlpha = i === state.timesliderIndex ? 1 : 0.4;
      ctx.fillRect(x + 1, yBase - h, barW - 2, h);
      yBase -= h;
    }
  });
  ctx.globalAlpha = 1;
  const x = state.timesliderIndex * barW + barW / 2;
  ctx.strokeStyle = '#5b8def';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(x, 0);
  ctx.lineTo(x, H);
  ctx.stroke();
}

/* =========================================================
   TOAST
   ========================================================= */
let toastTimer = null;
function showToast(msg, kind) {
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();
  clearTimeout(toastTimer);
  const t = document.createElement('div');
  t.className = 'toast ' + (kind || '');
  t.textContent = msg;
  document.body.appendChild(t);
  toastTimer = setTimeout(() => t.remove(), 3500);
}

/* =========================================================
   ЗУМ / ПАН
   ========================================================= */
let zoomDebounce;
map.on('zoomend', () => {
  if (state.mode !== 'clusters' && !state.useViewportBbox) return;
  clearTimeout(zoomDebounce);
  zoomDebounce = setTimeout(() => {
    if (state.useViewportBbox) reloadData();
    else renderMap();
  }, 300);
});

let moveDebounce;
map.on('moveend', () => {
  if (!state.useViewportBbox) return;
  clearTimeout(moveDebounce);
  moveDebounce = setTimeout(() => reloadData(), 400);
});

/* =========================================================
   BBOX-TOGGLE
   ========================================================= */
document.getElementById('bbox-toggle').addEventListener('click', () => {
  state.useViewportBbox = !state.useViewportBbox;
  document.getElementById('bbox-toggle').classList.toggle('active', state.useViewportBbox);
  showToast(state.useViewportBbox
    ? 'Включено: только видимая область'
    : 'Выключено: все данные');
  scheduleReload();
});

/* =========================================================
   SPLIT VIEW
   ========================================================= */
let mapB = null;
let mapBMarkersLayer = null;
let mapBHeatLayer = null;
let mapBDistrictsLayer = null;
let mapSyncLock = false;

function initMapB() {
  if (mapB) return;
  mapB = L.map('map-b', {
    center: map.getCenter(),
    zoom: map.getZoom(),
    zoomControl: false,
    preferCanvas: true,
  });
  L.tileLayer('https://{s}.basemaps.cartocdn.com/voyager/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; OSM, &copy; CARTO',
    subdomains: 'abcd', maxZoom: 19,
  }).addTo(mapB);
  mapBMarkersLayer = L.layerGroup();

  map.on('move zoom', () => {
    if (mapSyncLock || !mapB) return;
    mapSyncLock = true;
    mapB.setView(map.getCenter(), map.getZoom(), { animate: false });
    mapSyncLock = false;
  });
  mapB.on('move zoom', () => {
    if (mapSyncLock) return;
    mapSyncLock = true;
    map.setView(mapB.getCenter(), mapB.getZoom(), { animate: false });
    mapSyncLock = false;
  });

  api('/api/districts/geojson').then(geo => {
    mapBDistrictsLayer = L.geoJSON(geo, {
      style: () => ({
        color: '#5b8def', weight: 1.2,
        fillColor: '#5b8def', fillOpacity: 0.04,
        opacity: 0.5,
      }),
    });
    if (state.showDistricts) mapBDistrictsLayer.addTo(mapB);
  });
}

async function renderMapB() {
  if (!mapB) return;
  mapBMarkersLayer.clearLayers();
  mapB.removeLayer(mapBMarkersLayer);
  if (mapBHeatLayer) { mapB.removeLayer(mapBHeatLayer); mapBHeatLayer = null; }

  const qs = buildQuery({
    dateFrom: state.compareDateFromB,
    dateTo: state.compareDateToB,
  });
  const geo = await api('/api/objects/geojson?' + qs);
  const features = geo.features || [];

  if (state.mode === 'heat' && features.length) {
    const intensity = { critical: 1.0, violation: 0.8, warn: 0.5, pending: 0.4, ok: 0.15, unknown: 0.2 };
    const points = features.map(f => {
      const [lon, lat] = f.geometry.coordinates;
      return [lat, lon, intensity[f.properties.status] ?? 0.5];
    });
    mapBHeatLayer = L.heatLayer(points, {
      radius: 30, blur: 24, minOpacity: 0.4, maxZoom: 14,
      gradient: { 0.0:'#3b82f6', 0.3:'#22c55e', 0.5:'#f59e0b', 0.7:'#ef4444', 1.0:'#ec4899' },
    });
    mapB.addLayer(mapBHeatLayer);
  } else {
    for (const f of features) {
      const [lon, lat] = f.geometry.coordinates;
      const p = f.properties;
      const icon = L.divIcon({
        className: '',
        html: `<div class="obj-marker" style="background:${p.status_color}"></div>`,
        iconSize: [14, 14], iconAnchor: [7, 7],
      });
      mapBMarkersLayer.addLayer(L.marker([lat, lon], { icon }));
    }
    mapB.addLayer(mapBMarkersLayer);
  }
}

function applyCompareDates() {
  state.compareDateFromA = document.getElementById('cmp-from-a').value || null;
  state.compareDateToA = document.getElementById('cmp-to-a').value || null;
  state.compareDateFromB = document.getElementById('cmp-from-b').value || null;
  state.compareDateToB = document.getElementById('cmp-to-b').value || null;

  const origFrom = state.dateFrom, origTo = state.dateTo;
  state.dateFrom = state.compareDateFromA;
  state.dateTo = state.compareDateToA;
  reloadData().then(() => {
    state.dateFrom = origFrom;
    state.dateTo = origTo;
  });

  if (state.compareDateFromA || state.compareDateToA) {
    document.querySelector('.split-label-a').textContent =
      `A: ${state.compareDateFromA || '…'} → ${state.compareDateToA || '…'}`;
  }
  if (state.compareDateFromB || state.compareDateToB) {
    document.querySelector('.split-label-b').textContent =
      `B: ${state.compareDateFromB || '…'} → ${state.compareDateToB || '…'}`;
  }
  renderMapB();
}

document.getElementById('compare-toggle').addEventListener('click', () => {
  state.compareMode = !state.compareMode;
  document.getElementById('compare-toggle').classList.toggle('active', state.compareMode);
  const main = document.querySelector('.view-map');
  main.classList.toggle('split-active', state.compareMode);
  document.getElementById('compare-panel').style.display = state.compareMode ? '' : 'none';
  document.querySelector('.split-divider').style.display = state.compareMode ? '' : 'none';

  if (state.compareMode) {
    const today = new Date();
    const aFrom = new Date(today.getFullYear(), 0, 1).toISOString().slice(0, 10);
    const aTo = new Date(today.getFullYear(), 5, 30).toISOString().slice(0, 10);
    const bFrom = new Date(today.getFullYear(), 6, 1).toISOString().slice(0, 10);
    const bTo = today.toISOString().slice(0, 10);
    document.getElementById('cmp-from-a').value = aFrom;
    document.getElementById('cmp-to-a').value = aTo;
    document.getElementById('cmp-from-b').value = bFrom;
    document.getElementById('cmp-to-b').value = bTo;
    initMapB();
    setTimeout(() => {
      map.invalidateSize();
      if (mapB) mapB.invalidateSize();
      applyCompareDates();
    }, 100);
  } else {
    setTimeout(() => map.invalidateSize(), 100);
  }
});

document.getElementById('cmp-apply').addEventListener('click', applyCompareDates);

/* =========================================================
   INIT
   ========================================================= */
(async function init() {
  await loadDistrictsLayer();
  await reloadData();
})();
