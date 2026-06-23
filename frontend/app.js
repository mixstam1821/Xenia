const API = "";
// ── RGB composite guide images ─────────────────────────────────────────────
const RGB_GUIDE_IMAGES = {
  "dust":               "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/dust.png",
  "airmass":            "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/airmass.png",
  "natural_color":      "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/natural_color.jpg",
  "true_color":         "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/true_color.jpg",
  "night_microphysics": "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/night_microphysics.png",
      "day_microphysics": "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/day_microphysics.png",

  "fog":                "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/night_microphysics.png",
  "ash":                "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/ash.png",
  "24h_microphysics":   "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/24h_microphysics.png",
  "cloud_type":           "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/cloud_type.png",
    "cloud_phase":           "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/cloud_phase.jpg",
    "convection":               "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/convection.png",
    "snow":               "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/snow.jpg",
    "fire_temperature":    "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/fire_temperature.jpg",
    "day_severe_storms":               "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/convection.jpg",

};

const RGB_GUIDE_IMAGESx = {
  "dust":               "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/dustx.png",
  "airmass":            "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/airmassx.png",
  "natural_color":      "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/natural_colorx.jpg",
  "true_color":         "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/true_colorx.jpg",
  "night_microphysics": "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/night_microphysicsx.png",
    "day_microphysics": "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/day_microphysicsx.png",

  "fog":                "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/night_microphysicsx.png",
  "ash":                "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/ashx.png",
  "24h_microphysics": "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/24h_microphysicsx.png",
  "cloud_type":           "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/cloud_typex.png",
    "cloud_phase":           "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/cloud_phasex.jpg",
    "snow":               "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/snowx.jpg",
    "fire_temperature":               "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/fire_temperaturex.jpg",
    "convection":               "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/convectionx.png",
    "true_color":      "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/true_colorx.jpg",
    "day_severe_storms":               "https://raw.githubusercontent.com/mixstam1821/Xenia/refs/heads/main/assets0/convectionx.jpg",


};


// ══════════════════════════════════════════════════════════════════════════════
//  STATE
// ══════════════════════════════════════════════════════════════════════════════
const state = {
  file: null,
  dataset: null,
  colormap: "RdYlBu_r",
  vmin: null, vmax: null,
  opacity: 0.85,
  isGlobe: true,
  satBase: false,
  stats: null, bounds: null,
  animFiles: [],
  animSelectMode: false,
  animFrames: [],
  animFrame: 0,
  animPlaying: false,
  animInterval: null,
  rgbComposite: null,
  isRGBMode: false,
  overlaysLoaded: false,
  extraDimSelections: {},
  datasetMeta: {},
  // v4 performance
  currentGeomKey: null,   // last received geom key from backend
  renderAbort: null,      // AbortController for in-flight render
  useCustomColors: false,
  darkBase: true,
  spinning: false,
  spinFrame: null,
  pngUrl: null,
pngBlobUrl: null,
};
let _anyRenderActive = false;


let _resamplingMode = "nearest"; // default: fastest

function toggleResampling() {
  _resamplingMode = _resamplingMode === "nearest" ? "linear" : "nearest";
  const btn = document.getElementById("resample-btn");
  btn.textContent = _resamplingMode === "nearest" ? "⬡ Nearest" : "◈ Linear";
  btn.classList.toggle("active", _resamplingMode === "linear");
  // Apply immediately to active layer
  const activeLyr = _layerId(_activeSlot);
  if (map.getLayer(activeLyr)) {
    map.setPaintProperty(activeLyr, "raster-resampling", _resamplingMode);
  }
  const inactiveLyr = _layerId(_inactiveSlot());
  if (map.getLayer(inactiveLyr)) {
    map.setPaintProperty(inactiveLyr, "raster-resampling", _resamplingMode);
  }
}
function toggleSidebar() {
  const sb  = document.getElementById('sidebar');
  const btn = document.getElementById('sidebar-toggle');
  sb.classList.toggle('collapsed');
  btn.classList.toggle('collapsed');
  btn.textContent = sb.classList.contains('collapsed') ? '▶' : '◀';
}
// ══════════════════════════════════════════════════════════════════════════
//  TIMESTAMP OVERLAY
// ══════════════════════════════════════════════════════════════════════════

function _parseTimestampFromFilename(name) {
  // FCI L1c: _OPE_20260616184007_20260616184935_ → scan start
  let m = name.match(/_OPE_(\d{14})_(\d{14})/);
  if (m) {
    const s = m[1];
    return `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)} ${s.slice(8,10)}:${s.slice(10,12)} UTC`;
  }

  // LSASAF / general: delimiter before 14-digit, anything after
  m = name.match(/[_,](\d{14})(?:[_,.]|$)/);
  if (m) {
    const s = m[1];
    return `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)} ${s.slice(8,10)}:${s.slice(10,12)} UTC`;
  }

  // With T separator
  m = name.match(/(\d{8})T(\d{4,6})Z?/);
  if (m) {
    const d = m[1], t = m[2].slice(0,4);
    return `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6)} ${t.slice(0,2)}:${t.slice(2)} UTC`;
  }

  return null;
}
function showTimestampOverlay({ label = "", timestamp = "", frameInfo = "" } = {}) {
  const overlay = document.getElementById("timestamp-overlay");
  const labelEl = document.getElementById("ts-overlay-label");
  const valueEl = document.getElementById("ts-overlay-value");
  const frameEl = document.getElementById("ts-overlay-frame");

  if (!timestamp) {
    overlay.style.display = "none";
    return;
  }

  labelEl.textContent = label || "Observation time";
  valueEl.textContent = timestamp;

  if (frameInfo) {
    frameEl.textContent = frameInfo;
    frameEl.style.display = "";
  } else {
    frameEl.style.display = "none";
  }

  overlay.style.display = "";
}

function clearTimestampOverlay() {
  document.getElementById("timestamp-overlay").style.display = "none";
}

// ══════════════════════════════════════════════════════════════════════════════
//  COLORMAPS
// ══════════════════════════════════════════════════════════════════════════════
const CMAPS = [
  { name: "RdYlBu_r", stops: ["#313695","#4575b4","#74add1","#abd9e9","#ffffbf","#fdae61","#f46d43","#d73027","#a50026"] },
  { name: "viridis",  stops: ["#440154","#3b528b","#21918c","#5ec962","#fde725"] },
  { name: "plasma",   stops: ["#0d0887","#7e03a8","#cc4778","#f89540","#f0f921"] },
  { name: "gray",     stops: ["#000000","#ffffff"] },
  { name: "hot",      stops: ["#000000","#ff0000","#ffff00","#ffffff"] },
  { name: "coolwarm", stops: ["#3b4cc0","#f7f7f7","#b40426"] },
  { name: "turbo",    stops: ["#30123b","#1be4b8","#a0fd3e","#fb7a22","#7a0403"] },
  { name: "YlOrRd",  stops: ["#ffffcc","#fed976","#fd8d3c","#e31a1c","#800026"] },
  { name: "inferno",  stops: ["#000004","#420a68","#932667","#dd513a","#fca50a","#f8fa0e"] },
  { name: "cividis",  stops: ["#00204d","#31446b","#666870","#9b9b74","#d1c94c","#ffea46"] },
];


const BASE_TILES = {
  osm:  "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  sat:  "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  dark: "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
};

function _swapBaseTiles(key) {
  if (!map.getSource("base-tiles")) {
    // first call — source doesn't exist yet, fall back to full style swap
    // (only happens before map is fully loaded, shouldn't occur in practice)
    return;
  }
  map.getSource("base-tiles").setTiles([BASE_TILES[key]]);
}


function drawCmapSwatch(canvas, stops) {
  const ctx  = canvas.getContext("2d");
  const grad = ctx.createLinearGradient(0, 0, canvas.width, 0);
  stops.forEach((c, i) => grad.addColorStop(i / (stops.length - 1), c));
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
}


function toggleDarkBase() {
  state.darkBase = !state.darkBase;
  if (state.darkBase) state.satBase = false;
  document.getElementById("dark-btn").classList.toggle("active",  state.darkBase);
  document.getElementById("sat-btn").classList.toggle("active",  false);
  document.getElementById("dark-btn").textContent = "🌑 Dark";
  document.getElementById("sat-btn").textContent  = "🛰 Satellite base";
  _swapBaseTiles(state.darkBase ? "dark" : "osm");
}

function buildCmaps() {
  const row = document.getElementById("cm-row");
  CMAPS.forEach(cm => {
    const wrap = document.createElement("div");
    wrap.className = "cm-swatch" + (cm.name === state.colormap ? " active" : "");
    wrap.title = cm.name;
    const c = document.createElement("canvas");
    c.width = 28; c.height = 18;
    drawCmapSwatch(c, cm.stops);
    wrap.appendChild(c);
    wrap.onclick = () => {
      state.colormap = cm.name;
      state.useCustomColors = false;
      document.querySelectorAll(".cm-swatch").forEach(s => s.classList.remove("active"));
      wrap.classList.add("active");
      // ── STEP 2: instant recolor via /api/recolor if geom is cached ──
      _recolorIfPossible();
    };
    row.appendChild(wrap);
  });
}

// ══════════════════════════════════════════════════════════════════════════════
//  STEP 2: INSTANT RECOLOR (no full re-render when colormap/vmin/vmax change)
// ══════════════════════════════════════════════════════════════════════════════
let _recolorDebounce = null;

async function _recolorIfPossible() {
  // Only if we have a cached geom key from a previous render
  if (!state.currentGeomKey || state.isRGBMode) return;

  clearTimeout(_recolorDebounce);
  _recolorDebounce = setTimeout(async () => {
    const geomKey = state.currentGeomKey;
    currentRawArray = await _loadRawArray(geomKey);

    const vmin    = document.getElementById("vmin").value || "";
    const vmax    = document.getElementById("vmax").value || "";

    const customColors = state.useCustomColors
    ? document.getElementById("custom-colors-input").value.trim()
    : "";

    const params  = new URLSearchParams({
      geom_key: geomKey,
      colormap:  state.colormap,
      ...(vmin ? { vmin } : {}),
      ...(vmax ? { vmax } : {}),
      ...(customColors ? { custom_colors: customColors } : {}),

    });

    try {
      showLoading(true, "Recoloring…");
      const res = await fetch(`${API}/api/recolor?${params}`);
      if (!res.ok) {
        // Geom not in server cache (server restarted?) — fall back to full render
        showLoading(false);
        renderDataset();
        return;
      }
      const bounds  = res.headers.get("X-Bounds").split(",").map(Number);
      const hVmin   = parseFloat(res.headers.get("X-Vmin")) || null;
      const hVmax   = parseFloat(res.headers.get("X-Vmax")) || null;
      const blob    = await res.blob();
      const imgUrl  = URL.createObjectURL(blob);
      _lastImgUrl   = imgUrl;
      state.bounds  = bounds;
      currentBounds = bounds;
      _addMapLayer(imgUrl, bounds);
      currentImageData = await _loadImageData(imgUrl);
      showCacheBadge("⚡ recolored");
      if (currentStats) {
        const vminVal = parseFloat(document.getElementById("vmin").value) || hVmin || currentStats.p2;
        const vmaxVal = parseFloat(document.getElementById("vmax").value) || hVmax || currentStats.p98;
        drawColorbar(state.colormap, vminVal, vmaxVal, currentStats.long_name || state.dataset);
      }
    } catch(e) {
      console.warn("Recolor failed:", e);
    } finally {
      showLoading(false);
    }
  }, 80);  // 80ms debounce — feels instant








}
function applyCustomColors() {
  const raw = document.getElementById("custom-colors-input").value.trim();
  if (!raw) { _recolorIfPossible(); return; }
  // Validate JSON
  try {
    const parsed = JSON.parse(raw.replace(/'/g, '"')); // tolerate single quotes
    // Rebuild with double quotes for backend
    document.getElementById("custom-colors-input").value = JSON.stringify(parsed, null, 0);
    state.useCustomColors = true;
  } catch(e) {
    alert("Invalid JSON: " + e.message); return;
  }
  state.currentGeomKey ? _recolorIfPossible() : renderDataset();
}

// Hook vmin / vmax inputs to also trigger recolor
document.addEventListener("DOMContentLoaded", () => {
  ["vmin", "vmax"].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      let t;
      el.addEventListener("input", () => {
        clearTimeout(t);
        t = setTimeout(_recolorIfPossible, 400);
      });
    }
  });
});

// ══════════════════════════════════════════════════════════════════════════════
//  STEP 1: STOP RENDER BUTTON
// ══════════════════════════════════════════════════════════════════════════════
function _setRendering(active) {
  _anyRenderActive = active;
  document.getElementById("stop-btn").classList.toggle("visible", active);
  document.getElementById("render-btn").disabled = active;
  document.getElementById("rgb-render-btn").disabled = active;
  _setDatasetListLocked(active);
}

function _setRenderingRGB(active) {
  _anyRenderActive = active;
  document.getElementById("rgb-stop-btn").classList.toggle("visible", active);
  document.getElementById("rgb-render-btn").disabled = active;
  document.getElementById("render-btn").disabled = active;
  _setDatasetListLocked(active);
}


function stopRender() {
  if (state.renderAbort) {
    state.renderAbort.abort();
    state.renderAbort = null;
  }
  // Tell backend to stop too
  fetch(`${API}/api/cancel_render`, { method: "POST" }).catch(() => {});
  _setRendering(false);
  showLoading(false);
}
function showCacheBadge(text) {
  const b = document.getElementById("cache-badge");
  b.textContent = text || "⚡ cached";
  b.classList.add("visible");
  clearTimeout(b._timer);
  b._timer = setTimeout(() => b.classList.remove("visible"), 3000);
}


function _setDatasetListLocked(locked) {
  const datasetList = document.getElementById("dataset-list");
  const fileList    = document.getElementById("file-list");
  const overlay     = document.getElementById("render-lock-overlay");

  if (locked) {
    datasetList && (datasetList.style.opacity = "0.4");
    fileList    && (fileList.style.opacity    = "0.4");

    // Block ALL clicks at capture phase — fires before any onclick
    if (!window._renderLockHandler) {
      window._renderLockHandler = e => {
        const inDS   = datasetList && datasetList.contains(e.target);
        const inFile = fileList    && fileList.contains(e.target);
        if (inDS || inFile) { e.stopImmediatePropagation(); e.preventDefault(); }
      };
      document.addEventListener("click", window._renderLockHandler, true);
    }

    if (!overlay) {
      const el = document.createElement("div");
      el.id = "render-lock-overlay";
      el.style.cssText = "font-size:10px;color:var(--warn);text-align:center;padding:4px 0;letter-spacing:.04em";
      el.textContent = "⏳ rendering — wait before switching";
      const body = document.getElementById("card-datasets")?.querySelector(".card-body");
      body?.insertAdjacentElement("afterbegin", el);
    }
  } else {
    datasetList && (datasetList.style.opacity = "");
    fileList    && (fileList.style.opacity    = "");

    if (window._renderLockHandler) {
      document.removeEventListener("click", window._renderLockHandler, true);
      window._renderLockHandler = null;
    }
    overlay?.remove();
  }
}
 
function stopRenderRGB() {
  if (state.renderAbort) {
    state.renderAbort.abort();
    state.renderAbort = null;
  }
  fetch(`${API}/api/cancel_render`, { method: "POST" }).catch(() => {});
  _setRenderingRGB(false);
  showLoading(false);
}

// ══════════════════════════════════════════════════════════════════════════════
//  MAP INIT
// ══════════════════════════════════════════════════════════════════════════════
const OSM_STYLE = {
  version: 8,
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
  sources: {
    osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap" }
  },
  layers: [{ id: "osm-bg", type: "raster", source: "osm" }],
};

const SAT_STYLE = {
  version: 8,
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
  sources: {
    sat: { type: "raster", tiles: ["https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"], tileSize: 256, attribution: "© Esri" }
  },
  layers: [{ id: "sat-bg", type: "raster", source: "sat" }],
};


const DARK_STYLE = {
  version: 8,
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
  sources: {
    carto: {
      type: "raster",
      tiles: ["https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© CARTO © OpenStreetMap"
    }
  },
  layers: [{ id: "carto-bg", type: "raster", source: "carto" }],
};



// Remove OSM_STYLE, SAT_STYLE, DARK_STYLE constants entirely.
// Replace the map = new maplibregl.Map(...) call with:

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
    sources: {
      "base-tiles": {
        type: "raster",
        tiles: [BASE_TILES.osm],
        tileSize: 256,
        attribution: "© OpenStreetMap",
      }
    },
    layers: [{ id: "base-layer", type: "raster", source: "base-tiles" }],
  },
  center: [20, 40],
  zoom: 3,
});

map.addControl(new maplibregl.NavigationControl(), "top-left");
map.addControl(new maplibregl.ScaleControl(), "bottom-left");

function applyGlobeFog() {
  try {
    map.setFog({
      color: "#0d0f14",
      "high-color": "#1a2040",
      "horizon-blend": 0.06,
      "space-color": "#000005",
      "star-intensity": 0.18,
    });
  } catch(e) {}
}
function removeGlobeFog() {
  try { map.setFog(null); } catch(e) {}
}

map.on("style.load", () => {
  try { map.setProjection({ type: state.isGlobe ? "globe" : "mercator" }); } catch(e) {}
  if (state.isGlobe) applyGlobeFog(); else removeGlobeFog();

  // Defer slightly — style.load can fire before the style is fully queryable
  setTimeout(() => {
    if (_lastImgUrl && state.bounds) _addMapLayer(_lastImgUrl, state.bounds);
    _restoreOverlays();
  }, 0);
});

function toggleProjection() {
  state.isGlobe = !state.isGlobe;
  document.getElementById("tooltip").style.display = "none";

  if (!state.isGlobe && state.spinning) {
    state.spinning = false;
    document.getElementById("spin-btn").classList.remove("active");
    if (state.spinFrame) { cancelAnimationFrame(state.spinFrame); state.spinFrame = null; }
  }

  try { map.setProjection({ type: state.isGlobe ? "globe" : "mercator" }); } catch(e) {}

  const btn = document.getElementById("globe-btn");
  btn.classList.toggle("active", state.isGlobe);
  btn.textContent = state.isGlobe ? "🌍 Globe" : "🗺 Mercator";
  if (state.isGlobe) applyGlobeFog(); else removeGlobeFog();
  // No setStyle call — layers survive
}

document.getElementById("globe-btn").classList.add("active");

function toggleSatelliteBase() {
  state.satBase  = !state.satBase;
  if (state.satBase) state.darkBase = false;
  document.getElementById("sat-btn").classList.toggle("active",  state.satBase);
  document.getElementById("dark-btn").classList.toggle("active", false);
  document.getElementById("sat-btn").textContent  = state.satBase ? "🛰 Satellite" : "🛰 Satellite base";
  document.getElementById("dark-btn").textContent = "🌑 Dark";
  _swapBaseTiles(state.satBase ? "sat" : "osm");
}

// ══════════════════════════════════════════════════════════════════════════════
//  TOOLTIP
// ══════════════════════════════════════════════════════════════════════════════
let currentImageData = null;
let currentBounds    = null;
let currentStats     = null;
let _lastImgUrl      = null;

map.on("mousemove", e => {
  const tt = document.getElementById("tooltip");
  if (!currentRawArray || !currentBounds || state.isRGBMode) { tt.style.display = "none"; return; }

  const { lng, lat } = e.lngLat;

  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) { tt.style.display = "none"; return; }

  if (!_isOnGlobeVisible(e.point, e.lngLat)) { tt.style.display = "none"; return; }

  const [west, south, east, north] = currentBounds;
  if (lng < west || lng > east || lat < south || lat > north) { tt.style.display = "none"; return; }


  const px = (lng - west) / (east - west);

  function latToMercY(latDeg) {
    const latR = Math.max(-85.05, Math.min(85.05, latDeg)) * Math.PI / 180;
    return Math.log(Math.tan(Math.PI / 4 + latR / 2));
  }
  const mercN  = latToMercY(north);
  const mercS  = latToMercY(south);
  const mercPt = latToMercY(lat);
  const py     = 1 - (mercPt - mercS) / (mercN - mercS);

  const { rows, cols, data } = currentRawArray;
  const ix = Math.floor(px * cols);
  const iy = Math.floor(py * rows);
  if (ix < 0 || ix >= cols || iy < 0 || iy >= rows) { tt.style.display = "none"; return; }

  const value = data[iy * cols + ix];
  if (!Number.isFinite(value)) { tt.style.display = "none"; return; }

  let val = value.toFixed(3);
  if (currentStats && currentStats.units) val += " " + currentStats.units;

  document.getElementById("tt-name").textContent  = state.dataset || "";
  document.getElementById("tt-val").textContent   = val;
  document.getElementById("tt-coord").textContent = `${lat.toFixed(3)}°N  ${lng.toFixed(3)}°E`;
  tt.style.display = "block";
  tt.style.left = (e.point.x + 14) + "px";
  tt.style.top  = (e.point.y - 10) + "px";
});
map.on("mouseleave", () => { document.getElementById("tooltip").style.display = "none"; });

// ══════════════════════════════════════════════════════════════════════════════
//  COLORBAR
// ══════════════════════════════════════════════════════════════════════════════
function drawColorbar(cmName, vmin, vmax, label) {
  const canvas = document.getElementById("cb-canvas");
  canvas.width = canvas.offsetWidth || 180;

  // Only use custom colors if the flag is set
  if (state.useCustomColors) {
    const custom = document.getElementById("custom-colors-input").value.trim();
    if (custom) {
      try {
        const obj   = JSON.parse(custom);
        const stops = Object.entries(obj)
          .sort((a, b) => parseFloat(a[0]) - parseFloat(b[0]))
          .map(x => x[1]);
        drawCmapSwatch(canvas, stops);
        document.getElementById("cb-min").textContent  = vmin != null ? Number(vmin).toFixed(3) : "";
        document.getElementById("cb-max").textContent  = vmax != null ? Number(vmax).toFixed(3) : "";
        document.getElementById("cb-name").textContent = "Custom";
        document.getElementById("colorbar").style.display = "block";
        return;
      } catch(e) {}
    }
  }

  // Normal preset colormap
  const cm = CMAPS.find(c => c.name === cmName) || CMAPS[0];
  drawCmapSwatch(canvas, cm.stops);
  document.getElementById("cb-min").textContent  = vmin != null ? Number(vmin).toFixed(3) : "";
  document.getElementById("cb-max").textContent  = vmax != null ? Number(vmax).toFixed(3) : "";
  document.getElementById("cb-name").textContent = label || cmName;
  document.getElementById("colorbar").style.display = "block";
}

let currentRawArray = null; // Float32Array
let currentRawShape = null; // {rows, cols}

async function _loadRawArray(geomKey) {
  try {
    const res = await fetch(`${API}/api/render_raw?geom_key=${geomKey}`);
    if (!res.ok) return null;
    const buf = await res.arrayBuffer();
    const dv = new DataView(buf);
    const rows = dv.getUint32(0, true);
    const cols = dv.getUint32(4, true);
    const floatData = new Float32Array(buf, 8);
    return { rows, cols, data: floatData };
  } catch(e) {
    console.warn("raw array load failed:", e);
    return null;
  }
}

// ══════════════════════════════════════════════════════════════════════════════
//  MAP LAYER HELPERS (A/B swap for smooth transitions)
// ══════════════════════════════════════════════════════════════════════════════
let _activeSlot = "a";

function _sourceId(slot) { return `mtg-source-${slot}`; }
function _layerId(slot)  { return `mtg-layer-${slot}`;  }
function _inactiveSlot() { return _activeSlot === "a" ? "b" : "a"; }

function _addMapLayer(imgUrl, bounds) {
  const src = _sourceId("a");
  const lyr = _layerId("a");
  // PNG batch mode has its own opacity slider (png-opacity), separate from
  // the main dataset opacity slider (state.opacity). Use whichever one
  // actually applies, or every frame load here would silently reset
  // opacity back to state.opacity and ignore the PNG slider.
  const layerOpacity = _pngIsAnimBatch
    ? (parseFloat(document.getElementById("png-opacity").value) / 100)
    : state.opacity;
  const coords = [
    [bounds[0], bounds[3]], [bounds[2], bounds[3]],
    [bounds[2], bounds[1]], [bounds[0], bounds[1]],
  ];
  if (!map.getSource(src)) {
    map.addSource(src, { type: "image", url: imgUrl, coordinates: coords });
    map.addLayer({
      id: lyr, type: "raster", source: src,
      paint: { "raster-opacity": layerOpacity, "raster-fade-duration": 300, "raster-resampling": _resamplingMode },
    });
  } else {
    map.getSource(src).updateImage({ url: imgUrl, coordinates: coords });
    map.setPaintProperty(lyr, "raster-opacity", layerOpacity);
  }
  const inactLyr = _layerId(_inactiveSlot());
  if (map.getLayer(inactLyr)) map.setPaintProperty(inactLyr, "raster-opacity", 0);
  _activeSlot = "a";

  // ── always push overlays above raster layers ──
  ["overlay-countries", "overlay-coasts"].forEach(id => {
    if (map.getLayer(id)) map.moveLayer(id);
  });
}

function _swapMapLayer(imgUrl, bounds) {
  const nextSlot = _inactiveSlot();
  const nextSrc  = _sourceId(nextSlot);
  const nextLyr  = _layerId(nextSlot);
  const curLyr   = _layerId(_activeSlot);
  const coords   = [
    [bounds[0], bounds[3]], [bounds[2], bounds[3]],
    [bounds[2], bounds[1]], [bounds[0], bounds[1]],
  ];
  if (!map.getSource(nextSrc)) {
    map.addSource(nextSrc, { type: "image", url: imgUrl, coordinates: coords });
    map.addLayer({
      id: nextLyr, type: "raster", source: nextSrc,
      paint: { "raster-opacity": 0, "raster-fade-duration": 0, "raster-resampling": _resamplingMode },
    });
  } else {
    map.getSource(nextSrc).updateImage({ url: imgUrl, coordinates: coords });
  }
  if (map.getLayer(curLyr)) map.moveLayer(nextLyr);

  // NEW: keep overlays above both raster layers
  ["overlay-countries", "overlay-coasts"].forEach(id => {
    if (map.getLayer(id)) map.moveLayer(id);
  });

  const FADE = 180;
  map.setPaintProperty(nextLyr, "raster-fade-duration", FADE);
  map.setPaintProperty(curLyr,  "raster-fade-duration", FADE);
  map.setPaintProperty(nextLyr, "raster-opacity", state.opacity);
  map.setPaintProperty(curLyr,  "raster-opacity", 0);
  _activeSlot = nextSlot;
}

function _loadImageData(imgUrl) {
  return new Promise(resolve => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = img.width; c.height = img.height;
      c.getContext("2d").drawImage(img, 0, 0);
      resolve(c.getContext("2d").getImageData(0, 0, c.width, c.height));
    };
    img.onerror = () => resolve(null);
    img.src = imgUrl;
  });
}
function animStop() {
  if (state.animPlaying) animPlayPause();
  _showAnimFrame(0);
}
// ══════════════════════════════════════════════════════════════════════════════
//  FILES  (v4: improved display, search, file picker)
// ══════════════════════════════════════════════════════════════════════════════
let _allFiles = [];

async function refreshFiles() {
  try {
    const res = await fetch(`${API}/api/files`);
    _allFiles = await res.json();
    renderFileList();
  } catch(e) { console.error("refreshFiles error", e); }
}
async function setDataDir() {
  const input = document.getElementById("data-dir-input");
  const path = input.value.trim();
  if (!path) return;
  try {
    const res = await fetch(`${API}/api/set_data_dir`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed");
    document.getElementById("data-dir-label").textContent = "📁 " + data.data_dir;
    input.value = "";
    refreshFiles();
  } catch(e) {
    alert("Could not set data directory:\n" + e.message);
  }
}

// On startup, show current data dir
fetch(`${API}/api/get_data_dir`)
  .then(r => r.json())
  .then(d => { document.getElementById("data-dir-label").textContent = "📁 " + d.data_dir; })
  .catch(() => {});
  
function _fmtDate(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toISOString().slice(0, 16).replace("T", " ");
}

function renderFileList() {
  const el       = document.getElementById("file-list");
  const query    = (document.getElementById("file-search")?.value || "").toLowerCase().trim();
  const filtered = query
    ? _allFiles.filter(f => f.path.toLowerCase().includes(query))
    : _allFiles;

  document.getElementById("file-count").textContent =
    filtered.length < _allFiles.length
      ? `${filtered.length} / ${_allFiles.length}`
      : `${_allFiles.length} file${_allFiles.length !== 1 ? "s" : ""}`;

  if (!filtered.length) {
    el.innerHTML = `<div class="empty-msg">${query ? "No matches" : "No .nc files in data/"}</div>`;
    return;
  }

  el.innerHTML = "";
  filtered.forEach(f => {
    const isAnimSel = state.animFiles.includes(f.path);
    const item = document.createElement("div");
    item.className = "file-item"
      + (f.path === state.file && !state.animSelectMode ? " active" : "")
      + (isAnimSel ? " selected-anim" : "");

    item.innerHTML = `
      <div class="file-item-row">
        <span class="sel-check" style="display:${state.animSelectMode ? 'inline' : 'none'}">${isAnimSel ? "✓" : "○"}</span>
        <span class="file-name" title="${f.path}">${f.path}</span>
      </div>
      <div class="file-meta">
        <span class="file-size">${f.size_mb} MB</span>
        <span class="file-date">${_fmtDate(f.mtime)}</span>
      </div>`;

    item.onclick = () => {
      if (state.animSelectMode) toggleAnimFile(f.path);
      else selectFile(f.path);
    };
    el.appendChild(item);
  });
}

// Handle file picked from local disk (not uploaded — just reference for display)
function handleFilePick(input) {
  const file = input.files[0];
  if (!file) return;
  // Show a notice — backend can't access local FS paths, but we show the name
  alert(`Local file: "${file.name}"\n\nTo use local files, copy them to the data/ directory configured in MTG_DATA_DIR, then click ↺ refresh.`);
  input.value = "";
}

function _findTimeDim() {
  const meta = state.datasetMeta[state.dataset];
  if (!meta || !meta.extra_dims) return null;

  const TIME_PATTERNS = [
    /^time/i,
    /^year/i,
    /^month/i,
    /^day/i,
    /^hour/i,
    /^date/i,
    /^step/i,
    /^forecast/i,
    /^valid/i,
    /^lead/i,
    /^reftime/i,
    /^t$/i,
  ];

  // First: exact time-like name
  for (const pat of TIME_PATTERNS) {
    const found = meta.extra_dims.find(d => pat.test(d.name));
    if (found) return found;
  }

  // Fallback: any extra dim with values that look like years (1900–2100)
  // or ISO date strings
  const found = meta.extra_dims.find(d => {
    if (!d.values || !d.values.length) return false;
    const v = String(d.values[0]);
    return (
      /^\d{4}$/.test(v) && parseInt(v) >= 1900 && parseInt(v) <= 2100  // bare year
      || /^\d{4}-\d{2}/.test(v)   // ISO date
      || /^\d{4}\d{2}\d{2}/.test(v) // compact date
    );
  });
  return found || null;
}

map.on("click", async (e) => {
  if (state.isRGBMode || !state.file || !state.dataset) return;
  const timeDim = _findTimeDim();
  if (!timeDim || !currentBounds) return;

  const [west, south, east, north] = currentBounds;
  const { lng, lat } = e.lngLat;
  if (lng < west || lng > east || lat < south || lat > north) return;

  // Compute ix, iy exactly like the tooltip does
  const px = (lng - west) / (east - west);
  function latToMercY(latDeg) {
    const latR = Math.max(-85.05, Math.min(85.05, latDeg)) * Math.PI / 180;
    return Math.log(Math.tan(Math.PI / 4 + latR / 2));
  }
  const mercN = latToMercY(north);
  const mercS = latToMercY(south);
  const mercPt = latToMercY(lat);
  const py = 1 - (mercPt - mercS) / (mercN - mercS);

  const { rows, cols } = currentRawArray;
  const ix = Math.floor(px * cols);
  const iy = Math.floor(py * rows);
  if (ix < 0 || ix >= cols || iy < 0 || iy >= rows) return;

  // Convert (ix, iy) cell CENTER back to lat/lng — same cell the tooltip reads
  const cellLng = west + (ix + 0.5) / cols * (east - west);
  function mercYToLat(y) { return (2 * Math.atan(Math.exp(y)) - Math.PI/2) * 180 / Math.PI; }
  const cellMercY = mercN - (iy + 0.5) / rows * (mercN - mercS);
  const cellLat = mercYToLat(cellMercY);

  showTimeseries(timeDim.name, cellLat, cellLng);
});

let _tsChart = null;

async function showTimeseries(timeDimName, lat, lon) {
  const panel = document.getElementById("timeseries-panel");
  const title = document.getElementById("ts-title");

  const otherDims = { ...state.extraDimSelections };
  delete otherDims[timeDimName];

  try {
    const res = await fetch(`${API}/api/timeseries`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filepath: state.file,
        dataset: state.dataset,
        lat, lon,
        time_dim: timeDimName,
        extra_dims: otherDims,
      }),
    });

    if (!res.ok) {
      // e.g. geostationary file — not supported, ignore silently
      return;
    }

    const data = await res.json();
    panel.style.display = "block";
    title.textContent = `${lat.toFixed(2)}°N, ${lon.toFixed(2)}°E`;
    renderTimeseriesChart(data.labels, data.values);
  } catch(e) {
    // network error — ignore
  }
}
function _isOnGlobeDisk(point) {
  if (!state.isGlobe) return true; // mercator: whole canvas is the map
  const canvas = map.getCanvas();
  const dpr = window.devicePixelRatio || 1;
  const cx = canvas.width  / (2 * dpr);
  const cy = canvas.height / (2 * dpr);
  const r  = Math.min(cx, cy) * 0.98;
  const dx = point.x - cx, dy = point.y - cy;
  return (dx*dx + dy*dy) <= r*r;
}
function _isOnGlobeVisible(point, lngLat) {
  if (!state.isGlobe) return true;
  try {
    const reprojected = map.project(lngLat);
    const dx = reprojected.x - point.x;
    const dy = reprojected.y - point.y;
    return (dx*dx + dy*dy) < 4; // within ~2px round-trip tolerance
  } catch(e) {
    return false;
  }
}
function renderTimeseriesChart(labels, values) {
  const el = document.getElementById("ts-chart");
  if (!_tsChart) _tsChart = echarts.init(el, null, { renderer: "canvas" });

  const n = labels.length;
  const maxTicks = 6;
  const step = Math.max(1, Math.ceil(n / maxTicks));

  _tsChart.setOption({
    backgroundColor: "transparent",
    grid: { left: 46, right: 14, top: 4, bottom: 42 },
    dataZoom: [
    {
      type: "inside",
      xAxisIndex: 0,
      zoomOnMouseWheel: true,
      moveOnMouseWheel: true,
      moveOnMouseMove: false
    }
  ],
    xAxis: {
      type: "category",
      data: labels,
      axisLine:  { lineStyle: { color: "rgba(255,255,255,0.25)" } },
      axisTick:  { lineStyle: { color: "rgba(255,255,255,0.25)" } },
      axisLabel: {
        color: "#aab0c0",
        fontSize: 9,
        rotate: 30,
        interval: (index) => index % step === 0,
        formatter: (val) => {
          if (typeof val === "string" && val.includes("T")) {
            const [d, t] = val.split("T");
            return d.slice(5) + "\n" + t.slice(0,5);
          }
          return val;
        },
      },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      axisLine:  { show: false },
      axisTick:  { show: false },
      axisLabel: { color: "#aab0c0", fontSize: 10 },
      splitLine: { lineStyle: { color: "rgba(255,255,255,0.06)" } },
    },
    tooltip: {
      trigger: "axis",
      backgroundColor: "rgba(13,15,20,.92)",
      borderColor: "rgba(255,255,255,0.08)",
      textStyle: { color: "#e2e4ea", fontSize: 11 },
    },
    series: [{
      type: "line",
      data: values,
      smooth: true,
      symbol: "none",
      connectNulls: false,
      lineStyle: { color: "#FFD900", width: 2 },
      areaStyle: { color: "rgba(255, 244, 96, 0.15)" },
    }],
  });
}



function closeTimeseries() {
  document.getElementById("timeseries-panel").style.display = "none";
  if (_tsChart) { _tsChart.dispose(); _tsChart = null; }
}

async function selectFile(path) {
  // Kill any in-flight render immediately
  if (state.renderAbort) {
    state.renderAbort.abort();
    state.renderAbort = null;
  }
  _setRendering(false);
  _stopAllDimPlay();

  state.file = path;

  const fname = path.split(/[\\/]/).pop();
  const ts    = _parseTimestampFromFilename(fname);
  showTimestampOverlay({
    label: "Selected file",
    timestamp: ts || "",
  });
  state.dataset = null;
  state.currentGeomKey = null;
  state.extraDimSelections = {};
  state._dimValues = {};
  state.datasetMeta = {};
  const existing = document.getElementById("card-extra-dims");
  if (existing) existing.remove();
  renderFileList();
  showLoading(true, "Reading datasets…");
  _clearDimFrameCache();
// Give backend a moment if a render was just cancelled
await new Promise(r => setTimeout(r, 300));

let dsets = null;
for (let attempt = 1; attempt <= 2; attempt++) {
  const datasetAbort = new AbortController();
  const datasetTimeout = setTimeout(() => datasetAbort.abort(), 20000);
  try {
    const res = await fetch(
      `${API}/api/datasets?filepath=${encodeURIComponent(path)}`,
      { signal: datasetAbort.signal }
    );
    clearTimeout(datasetTimeout);
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
    dsets = await res.json();
    break; // success
  } catch(e) {
    clearTimeout(datasetTimeout);
    if (e.name === "AbortError" && attempt < 2) {
      showLoading(true, "Backend busy, retrying…");
      await new Promise(r => setTimeout(r, 2000));
      continue;
    }
    if (e.name === "AbortError") {
      alert("Backend still busy after retry.\n\nSolutions:\n• Wait a few seconds and click the file again\n• Restart the server\n• Use --workers 2 when starting uvicorn");
    } else {
      alert("Failed to read datasets:\n" + e.message);
    }
    return;
  } finally {
    showLoading(false);
  }
}

if (!dsets) return;

try {
  renderDatasetList(dsets);
  document.getElementById("card-datasets").style.display = "";
  document.getElementById("card-render").style.display   = "";
  state.isRGBMode = false;
  loadComposites(path);
  loadFileInfo(path);

} catch(e) {
  alert("Failed to render dataset list:\n" + e.message);
}
}



const GLOBE_SPIN_DEG_PER_SEC = 4; // adjust speed here

function _spinStep(prevTime) {
  if (!state.spinning) return;
  const now = performance.now();
  const dt  = prevTime ? (now - prevTime) / 1000 : 0;
  const center = map.getCenter();
  center.lng += GLOBE_SPIN_DEG_PER_SEC * dt;
  if (center.lng > 180) center.lng -= 360;
  map.setCenter(center);
  state.spinFrame = requestAnimationFrame(() => _spinStep(now));
}

function toggleGlobeSpin() {
  state.spinning = !state.spinning;
  const btn = document.getElementById("spin-btn");
  btn.classList.toggle("active", state.spinning);

  if (state.spinning) {
    if (!state.isGlobe) {
      toggleProjection();
    }
    _spinWasActive = false;
    _spinStep(null);
  } else {
    _spinWasActive = false;
    if (state.spinFrame) {
      cancelAnimationFrame(state.spinFrame);
      state.spinFrame = null;
    }
  }
}

// Pause the spin animation during user interaction, resume after release
let _spinWasActive = false;

["mousedown", "touchstart", "wheel"].forEach(evt => {
  map.on(evt, () => {
    if (state.spinning && state.spinFrame) {
      _spinWasActive = true;
      cancelAnimationFrame(state.spinFrame);
      state.spinFrame = null;
    }
  });
});

["mouseup", "touchend", "dragend", "wheel"].forEach(evt => {
  map.on(evt, () => {
    if (state.spinning && _spinWasActive && !state.spinFrame) {
      _spinWasActive = false;
      // small delay so MapLibre's own inertia/snap finishes first
      setTimeout(() => { if (state.spinning) _spinStep(null); }, 150);
    }
  });
});



// ══════════════════════════════════════════════════════════════════════════════
//  DATASET LIST + EXTRA DIMS
// ══════════════════════════════════════════════════════════════════════════════
function renderDatasetList(dsets) {
  const el = document.getElementById("dataset-list");
  el.innerHTML = "";
  if (!dsets.length) { el.innerHTML = '<div class="empty-msg">No renderable datasets</div>'; return; }

  state.datasetMeta = {};
  dsets.forEach(d => {
    const obj  = typeof d === "object" ? d : { name: d, extra_dims: [] };
    const name = obj.name;
    state.datasetMeta[name] = obj;

    const b = document.createElement("div");
    b.className = "ds-badge" + (name === state.dataset ? " active" : "");
    b.title = obj.shape && obj.shape.length ? `shape: [${obj.shape.join(", ")}]` : "";
    const extraCount = (obj.extra_dims || []).length;
    b.innerHTML = extraCount > 0
      ? `${name} <span style="font-size:9px;opacity:.6">[+${extraCount}D]</span>`
      : name;

    b.onclick = () => {
      state.dataset = name;
      state.extraDimSelections = {};
      state.currentGeomKey = null;
      document.querySelectorAll(".ds-badge").forEach(x => x.classList.remove("active"));
      b.classList.add("active");
      renderExtraDimControls(obj.extra_dims || []);
      _clearDimFrameCache();
    };
    el.appendChild(b);
  });

  if (state.dataset && state.datasetMeta[state.dataset]) {
    renderExtraDimControls(state.datasetMeta[state.dataset].extra_dims || []);
  }
}


async function loadFileInfo(filepath) {
  document.getElementById("card-fileinfo").style.display = "";
  const body = document.getElementById("fileinfo-body");
  body.innerHTML = '<div class="empty-msg">Loading…</div>';
  try {
    const res  = await fetch(`${API}/api/inspect?filepath=${encodeURIComponent(filepath)}`);
    const data = await res.json();
    const ga   = data.global_attrs || {};
    const rows = [
      ["Title",      ga.title      || "—"],
      ["Product",    ga.product_id || ga["product-id"] || "—"],
      ["Platform",   ga.platform   || ga.spacecraft_id || "—"],
      ["Coverage",   ga.coverage   || "—"],
      ["Start",      ga.time_coverage_start || "—"],
      ["End",        ga.time_coverage_end   || "—"],
      ["Created",    ga.date_created        || "—"],
      ["Institution",ga.institution         || "—"],
      ["Dims",       Object.entries(data.dimensions || {}).map(([k,v])=>`${k}:${v}`).join(" | ")],
      ["Variables",  Object.keys(data.variables || {}).length + " vars"],
    ];
    body.innerHTML = rows.map(([k,v]) => `
      <div style="display:flex;gap:6px;padding:3px 0;border-bottom:1px solid var(--border)">
        <span style="color:var(--muted);min-width:70px;flex-shrink:0">${k}</span>
        <span style="word-break:break-all;color:var(--text)">${String(v).slice(0,80)}</span>
      </div>`).join("");
  } catch(e) {
    body.innerHTML = `<div class="empty-msg">Error: ${e.message}</div>`;
  }
}



async function forceReset() {
  if (!confirm("Force restart the backend? In-flight renders will be cancelled and the page will reload.")) return;
 
  try {
    fetch(`${API}/api/force_restart`, { method: "POST" }).catch(() => {});
  } catch(e) {}
 
  if (state.renderAbort) { state.renderAbort.abort(); state.renderAbort = null; }
  _clearDimFrameCache();
  state.currentGeomKey = null;
  _setDatasetListLocked(false);   // unlock in case it was locked
 
  showLoading(true, "Restarting backend…");
 
  // Wait a beat before polling so the old process has time to exec
  await new Promise(r => setTimeout(r, 1500));
 
  let attempts = 0;
  const poll = setInterval(async () => {
    attempts++;
    try {
      const res = await fetch(`${API}/api/cache_info`, { cache: "no-store" });
      if (res.ok) {
        clearInterval(poll);
        location.reload();
      }
    } catch(e) {
      // still restarting — keep waiting
    }
    if (attempts > 90) {   // 90 × 1 s = 90 s timeout
      clearInterval(poll);
      showLoading(false);
      alert("Backend did not come back within 90 s.\nCheck server logs / process manager.");
    }
  }, 1000);
}


function renderExtraDimControls(extraDims) {
  const existing = document.getElementById("card-extra-dims");
  if (existing) existing.remove();
  if (!extraDims || !extraDims.length) return;

  const card = document.createElement("div");
  card.className = "card"; card.id = "card-extra-dims";
  card.innerHTML = `
    <div class="card-header" style="display:flex;justify-content:space-between;align-items:center">
      <span>Dimension slices</span>
      <span style="font-size:10px;color:var(--muted)">release → render</span>
    </div>
    <div class="card-body" id="extra-dims-body"></div>`;

  document.getElementById("card-datasets").insertAdjacentElement("afterend", card);
  const body = document.getElementById("extra-dims-body");
  state.extraDimSelections = {};
  state._dimValues = state._dimValues || {};
  state._dimPlayState = {};

  extraDims.forEach(dim => {
    state.extraDimSelections[dim.name] = 0;
    state._dimValues[dim.name] = dim.values || [];
    state._dimPlayState[dim.name] = { playing: false, interval: null };

    const labelId  = `edim-label-${dim.name}`;
    const sliderId = `edim-slider-${dim.name}`;
    const playBtnId = `edim-play-${dim.name}`;
    const firstVal = (dim.values && dim.values.length) ? dim.values[0] : "0";

    const row = document.createElement("div");
    row.style.cssText = "margin-bottom:10px";
    row.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <span style="font-size:11px;color:var(--text);font-family:monospace">${dim.name}</span>
        <span id="${labelId}" style="font-size:11px;color:var(--accent);text-align:right;max-width:170px;word-break:break-all">${firstVal} <span style="opacity:.5">[0/${dim.size-1}]</span></span>
      </div>
      <div style="display:flex;align-items:center;gap:6px">
        <button id="${playBtnId}"
          style="flex-shrink:0;width:26px;height:26px;border-radius:5px;
                 border:1px solid var(--border);background:var(--bg);
                 color:var(--text);font-size:13px;cursor:pointer;
                 display:flex;align-items:center;justify-content:center;
                 transition:border-color .15s,color .15s"
          title="Play/Stop along ${dim.name}"
          onclick="toggleDimPlay('${dim.name}', ${dim.size})">▶</button>
        <input id="${sliderId}" type="range" min="0" max="${dim.size - 1}" value="0"
               style="flex:1;accent-color:var(--accent)"
               oninput="onExtraDimInput('${dim.name}', this.value)"
               onchange="onExtraDimChange('${dim.name}', this.value)">
      </div>`;
    body.appendChild(row);
  });
}


function toggleDimPlay(dimName, dimSize) {
  const ps  = state._dimPlayState[dimName];
  const btn = document.getElementById(`edim-play-${dimName}`);
  if (ps.playing) {
    clearInterval(ps.interval);
    ps.playing = false; ps.interval = null;
    btn.textContent = "▶";
    btn.style.borderColor = "var(--border)";
    btn.style.color = "var(--text)";
  } else {
    ps.playing = true;
    btn.textContent = "⏹";
    btn.style.borderColor = "var(--accent)";
    btn.style.color = "var(--accent)";
    ps.interval = setInterval(() => {
      const slider = document.getElementById(`edim-slider-${dimName}`);
      if (!slider) { clearInterval(ps.interval); return; }
      const next = (state.extraDimSelections[dimName] + 1) % dimSize;
      slider.value = next;
      onExtraDimInput(dimName, next);
      state.extraDimSelections[dimName] = next;
      renderDimFrame(dimName, next);
    }, 1200);
  }
}

function _stopAllDimPlay() {
  if (!state._dimPlayState) return;
  Object.entries(state._dimPlayState).forEach(([name, ps]) => {
    if (ps.playing) { clearInterval(ps.interval); ps.playing = false; ps.interval = null; }
  });
}


function onExtraDimInput(dimName, val) {
  const idx = parseInt(val);
  state.extraDimSelections[dimName] = idx;
  const lbl = document.getElementById(`edim-label-${dimName}`);
  if (lbl) {
    const vals  = (state._dimValues || {})[dimName] || [];
    const coord = vals[idx] !== undefined ? vals[idx] : String(idx);
    const max   = vals.length ? vals.length - 1 : idx;
    lbl.innerHTML = `${coord} <span style="opacity:.5">[${idx}/${max}]</span>`;
  }
}

let _extraDimRenderTimer = null;
function onExtraDimChange(dimName, val) {
  const idx = parseInt(val);
  state.extraDimSelections[dimName] = idx;
  clearTimeout(_extraDimRenderTimer);
  _extraDimRenderTimer = setTimeout(() => {
    if (state.file && state.dataset) renderDimFrame(dimName, idx);
  }, 60);
}

async function renderDimFrame(dimName, idx) {
  const key = _dimFrameKey(dimName, idx);
  const cached = _dimFrameCache.get(key);
  if (cached) {
    _swapMapLayer(cached.url, cached.bounds);
    currentBounds = cached.bounds;
    state.bounds   = cached.bounds;
    state.currentGeomKey = cached.geomKey;
    currentRawArray = cached.rawArray;
    if (cached.statsHeaders) {
      drawColorbar(state.colormap, cached.statsHeaders.vmin, cached.statsHeaders.vmax,
                    (currentStats && currentStats.long_name) || state.dataset);
    }
    return;
  }

  // Not cached — fetch silently (no loading overlay, no full renderDataset())
  if (state.renderAbort) state.renderAbort.abort();
  state.renderAbort = new AbortController();
  const signal = state.renderAbort.signal;

  try {
    const vmin    = document.getElementById("vmin").value || "";
    const vmax    = document.getElementById("vmax").value || "";
    const quality = "normal";
    const customColors = state.useCustomColors
      ? document.getElementById("custom-colors-input").value.trim()
      : "";

    const params = new URLSearchParams({
      filepath: state.file, dataset: state.dataset,
      colormap: state.colormap, quality,
      extra_dims: JSON.stringify(state.extraDimSelections),
      ...(vmin ? { vmin } : {}),
      ...(vmax ? { vmax } : {}),
      ...(customColors ? { custom_colors: customColors } : {}),
    });

    const res = await fetch(`${API}/api/render?${params}`, { signal });
    if (!res.ok) return;

    const bounds  = res.headers.get("X-Bounds").split(",").map(Number);
    const hVmin   = parseFloat(res.headers.get("X-Vmin")) || null;
    const hVmax   = parseFloat(res.headers.get("X-Vmax")) || null;
    const geomKey = res.headers.get("X-GeomKey") || null;

    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);

    let rawArray = geomKey ? await _loadRawArray(geomKey) : null;
    if (!rawArray && geomKey) {
      await new Promise(r => setTimeout(r, 500));
      rawArray = await _loadRawArray(geomKey);
    }
    const frame = {
      url, bounds, geomKey, rawArray,
      statsHeaders: { vmin: hVmin, vmax: hVmax },
    };
    _dimFrameCache.set(key, frame);

    _swapMapLayer(url, bounds);
    currentBounds = bounds;
    state.bounds  = bounds;
    state.currentGeomKey = geomKey;
    currentRawArray = rawArray;

  } catch(e) {
    if (e.name !== "AbortError") console.warn("dim frame render failed:", e);
  } finally {
    state.renderAbort = null;
  }
}


const _dimFrameCache = new Map();

function _dimFrameKey(dimName, idx) {
  const vmin = document.getElementById("vmin").value || "auto";
  const vmax = document.getElementById("vmax").value || "auto";
  return `${state.file}|${state.dataset}|${dimName}|${idx}|${state.colormap}|${vmin}|${vmax}`;
}

function _clearDimFrameCache() {
  _dimFrameCache.forEach(f => URL.revokeObjectURL(f.url));
  _dimFrameCache.clear();
}


// ══════════════════════════════════════════════════════════════════════════════
//  RENDER  (v4: AbortController + cache awareness)
// ══════════════════════════════════════════════════════════════════════════════
async function renderDataset() {
  if (!state.file || !state.dataset) { alert("Select a file and dataset first."); return; }
  if (_anyRenderActive) return;

  // Cancel any in-flight request
  if (state.renderAbort) state.renderAbort.abort();
  state.renderAbort = new AbortController();
  const signal = state.renderAbort.signal;

  _setRendering(true);
  showLoading(true, "Rendering…");

  try {
    const vmin    = document.getElementById("vmin").value || "";
    const vmax    = document.getElementById("vmax").value || "";
    const quality = "normal";
    const edims   = state.extraDimSelections || {};
    const customColors = state.useCustomColors
    ? document.getElementById("custom-colors-input").value.trim()
    : "";

    const params  = new URLSearchParams({
      filepath: state.file, dataset: state.dataset,
      colormap: state.colormap, quality,
      ...(vmin ? { vmin } : {}),
      ...(vmax ? { vmax } : {}),
      ...(customColors ? { custom_colors: customColors } : {}),

    });
    if (Object.keys(edims).length > 0) params.set("extra_dims", JSON.stringify(edims));

    const res = await fetch(`${API}/api/render?${params}`, { signal });
    if (!res.ok) {
      const e = await res.json();
      if (res.status === 409) {
      await fetch(`${API}/api/cancel_render`, { method: "POST" });
      await new Promise(r => setTimeout(r, 800));
      _setRenderingRGB(false);
      showLoading(false);
      state.renderAbort = null;
      renderRGB();
      return;
    }
      throw new Error(e.detail || "Render failed");
    }
    const bounds    = res.headers.get("X-Bounds").split(",").map(Number);
    const hVmin     = parseFloat(res.headers.get("X-Vmin")) || null;
    const hVmax     = parseFloat(res.headers.get("X-Vmax")) || null;
    const geomKey   = res.headers.get("X-GeomKey") || null;
    const cached    = res.headers.get("X-Cached") || "0";

    // Store geom key for instant recolor
    state.currentGeomKey = geomKey;
    // Small delay — geom cache write and HTTP response are nearly simultaneous
    await new Promise(r => setTimeout(r, 150));
    currentRawArray = await _loadRawArray(geomKey);
    // Retry once if cache miss due to race
    if (!currentRawArray && geomKey) {
      await new Promise(r => setTimeout(r, 500));
      currentRawArray = await _loadRawArray(geomKey);
    }

    currentBounds = bounds;
    const fname = (state.file || "").split(/[\\/]/).pop();
  showTimestampOverlay({
    label: state.dataset || "Dataset",
    timestamp: res.headers.get("X-Timestamp") || _parseTimestampFromFilename(fname) || "",
  });
    state.bounds  = bounds;

    const blob   = await res.blob();
    const imgUrl = URL.createObjectURL(blob);
    _lastImgUrl  = imgUrl;

    _addMapLayer(imgUrl, bounds);
    currentImageData = await _loadImageData(imgUrl);



    if (cached !== "0") showCacheBadge(cached === "1" ? "⚡ full cache" : cached === "geom" ? "⚡ geom cache" : "⚡ " + cached);

    await fetchStats(hVmin, hVmax);

  } catch(e) {
    if (e.name === "AbortError") {
      // User stopped render — no error shown
    } else {
      showRenderError(e.message);
    }
  } finally {
    _setRendering(false);
    showLoading(false);
    state.renderAbort = null;
  }
}

function showRenderError(msg) {
  const existing = document.getElementById("render-error-panel");
  if (existing) existing.remove();
  const panel = document.createElement("div");
  panel.id = "render-error-panel";
  panel.style.cssText = `
    position:absolute; top:12px; left:50%; transform:translateX(-50%);
    background:rgba(224,90,90,.95); border:1px solid rgba(255,120,120,.6);
    border-radius:8px; padding:10px 14px; z-index:200; max-width:480px;
    font-size:12px; color:#fff; backdrop-filter:blur(4px);
    display:flex; flex-direction:column; gap:6px;`;
  const inspectUrl = state.file ? `${API}/api/inspect?filepath=${encodeURIComponent(state.file)}` : null;
  panel.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px">
      <strong>Render error</strong>
      <button onclick="this.closest('#render-error-panel').remove()"
              style="background:none;border:none;color:#fff;font-size:14px;cursor:pointer;padding:0;line-height:1">✕</button>
    </div>
    <div style="font-family:monospace;font-size:11px;white-space:pre-wrap;word-break:break-all">${msg}</div>
    ${inspectUrl ? `<a href="${inspectUrl}" target="_blank"
        style="color:#ffe;font-size:11px;text-decoration:underline">
        🔍 Inspect file structure</a>` : ""}`;
  document.getElementById("map-wrap").appendChild(panel);
  setTimeout(() => panel.remove(), 20000);
}

async function fetchStats(hintVmin, hintVmax) {
  try {
    const params = new URLSearchParams({ filepath: state.file, dataset: state.dataset });
    const edims = state.extraDimSelections || {};
    if (Object.keys(edims).length > 0) params.set("extra_dims", JSON.stringify(edims));
    const res    = await fetch(`${API}/api/stats?${params}`);
    const data   = await res.json();
    currentStats = data; state.stats = data;
    const vmin = parseFloat(document.getElementById("vmin").value) || hintVmin || data.p2  || data.min;
    const vmax = parseFloat(document.getElementById("vmax").value) || hintVmax || data.p98 || data.max;
    document.getElementById("stats-grid").innerHTML = `
      <div class="stat-item"><div class="stat-label">min</div><div class="stat-val">${data.min}</div></div>
      <div class="stat-item"><div class="stat-label">max</div><div class="stat-val">${data.max}</div></div>
      <div class="stat-item"><div class="stat-label">mean</div><div class="stat-val">${data.mean}</div></div>
      <div class="stat-item"><div class="stat-label">units</div><div class="stat-val">${data.units || "—"}</div></div>
      <div class="stat-item"><div class="stat-label">p2/p98</div><div class="stat-val">${data.p2} / ${data.p98}</div></div>
      <div class="stat-item"><div class="stat-label">valid px</div><div class="stat-val">${(data.valid_px/1e6).toFixed(1)}M / ${(data.total_px/1e6).toFixed(1)}M</div></div>
      <div class="stat-item" style="grid-column:1/-1"><div class="stat-label">shape</div>
        <div class="stat-val">${data.shape.join(" × ")}</div></div>
      ${data.source === 'geom_cache' ? '<div class="stat-item" style="grid-column:1/-1"><div class="stat-label">source</div><div class="stat-val" style="color:var(--accent2);font-size:11px">⚡ from cache</div></div>' : ''}
    `;
    document.getElementById("card-stats").style.display = "";
    drawColorbar(state.colormap, vmin, vmax, data.long_name || state.dataset);
  } catch(e) { console.warn("stats failed", e); }
}

function setOpacity(val) {
  state.opacity = val / 100;
  document.getElementById("opacity-val").textContent = val + "%";
  const activeLyr = _layerId(_activeSlot);
  if (map.getLayer(activeLyr)) map.setPaintProperty(activeLyr, "raster-opacity", state.opacity);
}

function setRGBOpacity(val) {
  state.opacity = val / 100;
  document.getElementById("rgb-opacity-val").textContent = val + "%";
  const activeLyr = _layerId(_activeSlot);
  if (map.getLayer(activeLyr)) map.setPaintProperty(activeLyr, "raster-opacity", state.opacity);
}

// ══════════════════════════════════════════════════════════════════════════════
//  ANIMATION
// ══════════════════════════════════════════════════════════════════════════════
function toggleAnimSelectMode() {
  state.animSelectMode = !state.animSelectMode;
  const btn = document.getElementById("anim-select-btn");
  btn.textContent = state.animSelectMode ? "✕ cancel" : "🎞 multi";
  btn.classList.toggle("warn", state.animSelectMode);
  document.getElementById("anim-selected-panel").style.display = state.animSelectMode ? "" : "none";
  if (!state.animSelectMode) { state.animFiles = []; }
  renderFileList();
}

function toggleAnimFile(path) {
  const idx = state.animFiles.indexOf(path);
  if (idx === -1) state.animFiles.push(path); else state.animFiles.splice(idx, 1);
  document.getElementById("anim-count-label").textContent = state.animFiles.length + " files selected";
  document.getElementById("anim-prep-btn").disabled = state.animFiles.length < 2;
  renderFileList();
}

function clearAnimSelection() {
  state.animFiles = [];
  document.getElementById("anim-count-label").textContent = "0 files selected";
  document.getElementById("anim-prep-btn").disabled = true;
  renderFileList();
}
function useCustomComposite() {
  const name = document.getElementById("custom-composite-input").value.trim();
  if (!name) return;
  state.rgbComposite = name;
  document.querySelectorAll(".comp-btn").forEach(b => b.classList.remove("active"));
  document.getElementById("rgb-render-btn").disabled = false;
  document.getElementById("rgb-selected-label").textContent = `Selected (custom): ${name}`;
}
// Frame blob cache: filepath → {url, bounds}
const _animFrameCache = new Map();

async function prepareAnimation() {
  if (!state.dataset) { alert("Select a dataset first, then use multi-select."); return; }
  if (state.animFiles.length < 2) { alert("Select at least 2 files."); return; }

  showLoading(true, "Preparing animation…");
  try {
    const infoRes = await fetch(`${API}/api/animation_info`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filepaths: state.animFiles, dataset: state.dataset,
        colormap: state.colormap,
        vmin: parseFloat(document.getElementById("vmin").value) || null,
        vmax: parseFloat(document.getElementById("vmax").value) || null,
      }),
    });
    if (!infoRes.ok) { const e = await infoRes.json(); throw new Error(e.detail); }
    const info = await infoRes.json();

    const vmin = parseFloat(document.getElementById("vmin").value) || info.vmin;
    const vmax = parseFloat(document.getElementById("vmax").value) || info.vmax;

    state.animFrames = [];
    for (let i = 0; i < state.animFiles.length; i++) {
      const fp = state.animFiles[i];
      showLoading(true, `Rendering frame ${i+1}/${state.animFiles.length}…`);

      // Check blob cache first
      const cacheKey = `${fp}|${state.dataset}|${state.colormap}|${vmin}|${vmax}`;
      if (_animFrameCache.has(cacheKey)) {
        state.animFrames.push(_animFrameCache.get(cacheKey));
        continue;
      }

      try {
        const params = new URLSearchParams({
          filepath: fp, dataset: state.dataset, colormap: state.colormap,
          ...(vmin != null ? { vmin } : {}),
          ...(vmax != null ? { vmax } : {}),
        });
        const res = await fetch(`${API}/api/render_frame?${params}`);
        if (!res.ok) { state.animFrames.push({ filepath: fp, error: true }); continue; }
        const bounds = res.headers.get("X-Bounds").split(",").map(Number);
        const blob   = await res.blob();
        const url    = URL.createObjectURL(blob);
        const frame  = { filepath: fp, url, bounds };
        _animFrameCache.set(cacheKey, frame);
        state.animFrames.push(frame);
      } catch(e) {
        state.animFrames.push({ filepath: fp, error: true });
      }
    }

    const validFrames = state.animFrames.filter(f => !f.error);
    if (!validFrames.length) throw new Error("All frames failed to render.");

    drawColorbar(state.colormap, vmin, vmax, state.dataset);
    state.animFrame = 0;
    document.getElementById("anim-progress").max   = state.animFrames.length - 1;
    document.getElementById("anim-progress").value = 0;
    document.getElementById("anim-label").textContent = `1/${state.animFrames.length}`;
    document.getElementById("anim-bar").style.display = "flex";
    _showAnimFrame(0);

    if (info.bounds) {
      map.fitBounds([[info.bounds[0], info.bounds[1]], [info.bounds[2], info.bounds[3]]], { padding: 40 });
    }
    toggleAnimSelectMode();
  } catch(e) {
    alert("Animation prep failed:\n" + e.message);
  } finally {
    showLoading(false);
  }
}

function _showAnimFrame(idx) {
  const frame = state.animFrames[idx];
  if (!frame || frame.error) return;
  _addMapLayer(frame.url, frame.bounds);   // existing line
  state.animFrame = idx;                   // existing line
  document.getElementById("anim-progress").value = idx;          // existing
  document.getElementById("anim-label").textContent = `${idx+1}/${state.animFrames.length}`; // existing

  // ── NEW: timestamp overlay ──
  const ts = _parseTimestampFromFilename(frame.filepath || "");
  showTimestampOverlay({
    label: state.isRGBMode
      ? (state.rgbComposite || "RGB").replace(/_/g," ")
      : (state.dataset || ""),
    timestamp: ts || "",
    frameInfo: `Frame ${idx + 1} / ${state.animFrames.length}`,
  });
}

function animPlayPause() {
  state.animPlaying = !state.animPlaying;
  const btn = document.getElementById("anim-play-btn");
  btn.textContent = state.animPlaying ? "⏸" : "▶";
  btn.classList.toggle("active", state.animPlaying);
  if (state.animPlaying) {
    const fps = Math.max(1, parseInt(document.getElementById("anim-fps").value) || 2);
    state.animInterval = setInterval(() => {
      const next = (state.animFrame + 1) % state.animFrames.length;
      _showAnimFrame(next);
    }, 1000 / fps);
  } else {
    clearInterval(state.animInterval);
  }
}

function animStep(dir) {
  if (state.animPlaying) animPlayPause();
  const next = Math.max(0, Math.min(state.animFrames.length - 1, state.animFrame + dir));
  _showAnimFrame(next);
}

function updateOverlayColor(name, color) {
  const layerId = `overlay-${name}`;
  if (map.getLayer(layerId)) {
    map.setPaintProperty(layerId, "line-color", color);
  }
  // Update the default in OVERLAY_SOURCES so re-add uses the picked color
  OVERLAY_SOURCES[name].paint["line-color"] = color;
}

function animSeek(val) {
  if (state.animPlaying) animPlayPause();
  _showAnimFrame(parseInt(val));
}

function closeAnimation() {
  if (state.animPlaying) animPlayPause();
  document.getElementById("anim-bar").style.display = "none";
  state.animFrames = [];
  state.isRGBMode = false;
  clearTimestampOverlay();   // ← add this
}

// ══════════════════════════════════════════════════════════════════════════════
//  DOWNLOAD
// ══════════════════════════════════════════════════════════════════════════════
async function loadCollections() {
  try {
    const res  = await fetch(`${API}/api/collections`);
    const data = await res.json();
    const sel  = document.getElementById("dl-collection");
    Object.keys(data).forEach(name => {
      const opt = document.createElement("option");
      opt.value = name; opt.textContent = name;
      sel.appendChild(opt);
    });
  } catch(e) {}
}

async function startDownload() {
  const collection = document.getElementById("dl-collection").value;
  const start      = document.getElementById("dl-start").value;
  const end        = document.getElementById("dl-end").value;
  const limit      = parseInt(document.getElementById("dl-limit").value) || 2;
  if (!start || !end) { alert("Set start and end time."); return; }
  document.getElementById("dl-btn").disabled = true;
  document.getElementById("dl-progress").style.display = "";
  document.getElementById("dl-status").textContent = "Queuing…";
  const res = await fetch(`${API}/api/download`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ collection, start, end, limit }),
  });
  const { job_id } = await res.json();
  pollDownload(job_id);
}

function pollDownload(job_id) {
  const interval = setInterval(async () => {
    const res = await fetch(`${API}/api/download/${job_id}`);
    const job = await res.json();
    const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
    document.getElementById("dl-bar").style.width = pct + "%";
    document.getElementById("dl-status").textContent =
      job.status === "complete" ? `✓ Done — ${job.done} files downloaded` :
      job.status === "error"    ? `✗ Error: ${job.error}` :
      `${job.done}/${job.total || "?"} — ${job.last || "…"}`;
    if (job.status === "complete" || job.status === "error") {
      clearInterval(interval);
      document.getElementById("dl-btn").disabled = false;
      if (job.status === "complete") refreshFiles();
    }
  }, 1200);
}

// ══════════════════════════════════════════════════════════════════════════════
//  RGB COMPOSITES
// ══════════════════════════════════════════════════════════════════════════════
async function loadComposites(filepath) {
  const isFciL1c = filepath.toUpperCase().includes("FCI") &&
                   (filepath.toUpperCase().includes("1C") || filepath.toUpperCase().includes("L1C")) &&
                   !filepath.toUpperCase().includes("L2");

  if (!isFciL1c) {
    document.getElementById("card-rgb").style.display = "none";
    return;
  }

  document.getElementById("card-rgb").style.display = "";
  const grid = document.getElementById("composite-list");
  grid.innerHTML = '<div class="empty-msg" style="grid-column:1/-1">Loading…</div>';
  document.getElementById("rgb-render-btn").disabled = true;
  document.getElementById("custom-composite-input").value = "";
  document.getElementById("rgb-selected-label").textContent = "";

  try {
    const res  = await fetch(`${API}/api/composites?filepath=${encodeURIComponent(filepath)}`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    grid.innerHTML = "";
    state.rgbComposite = null;
    Object.entries(data).forEach(([id, label]) => {
      const btn = document.createElement("button");
      btn.className = "comp-btn"; btn.textContent = label; btn.title = id;
      btn.onclick = () => {
        state.rgbComposite = id;
        document.querySelectorAll(".comp-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById("rgb-render-btn").disabled = false;
        document.getElementById("custom-composite-input").value = "";
        document.getElementById("rgb-selected-label").textContent = "";
      };
      grid.appendChild(btn);
    });
    if (!Object.keys(data).length) {
      grid.innerHTML = '<div class="empty-msg" style="grid-column:1/-1">No composites available</div>';
    }
  } catch(e) {
    grid.innerHTML = `<div class="empty-msg" style="grid-column:1/-1">Error: ${e.message}</div>`;
  }
}

function showRGBGuide() {
  const panel = document.getElementById("rgb-guide-panel");
  const img   = document.getElementById("rgb-guide-img");
  const noImg = document.getElementById("rgb-guide-no-img");
  const title = document.getElementById("rgb-guide-title");
  const guideBtn = document.getElementById("rgb-guide-btn");
  if (!panel) return;

  const isVisible = panel.style.display === "flex";
  if (isVisible) { closeRGBGuide(); return; }

  const name = state.rgbComposite || "";
  const url  = RGB_GUIDE_IMAGES[name];
  title.textContent = name.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  if (url) {
    img.src             = url;
    img.style.display   = "block";
    noImg.style.display = "none";
  } else {
    img.style.display   = "none";
    noImg.style.display = "block";
  }

  // Position below the map controls using getBoundingClientRect
  if (guideBtn) {
    const mapWrap = document.getElementById("map-wrap");
    const btnRect  = guideBtn.getBoundingClientRect();
    const wrapRect = mapWrap.getBoundingClientRect();
    panel.style.top = (btnRect.bottom - wrapRect.top + 8) + "px";
    guideBtn.classList.add("active");
  } else {
    panel.style.top = "220px";
  }

  panel.style.display = "flex";
}
function closeRGBGuide() {
  const panel    = document.getElementById("rgb-guide-panel");
  const guideBtn = document.getElementById("rgb-guide-btn");
  if (panel) panel.style.display = "none";
  if (guideBtn) guideBtn.classList.remove("active");
}


async function renderRGB() {
  if (!state.file || !state.rgbComposite) { alert("Select a file and a composite first."); return; }
  
  // ── reset any stuck state before starting ──
  if (_anyRenderActive) {
    await fetch(`${API}/api/cancel_render`, { method: "POST" }).catch(() => {});
    await new Promise(r => setTimeout(r, 400));
    _setRendering(false);
    _setRenderingRGB(false);
  }

  // Cancel any in-flight request (same pattern as renderDataset)
  if (state.renderAbort) state.renderAbort.abort();
  state.renderAbort = new AbortController();
  const signal = state.renderAbort.signal;

  _setRenderingRGB(true);
  // Sync RGB opacity slider with current state
  const rgbOpacitySlider = document.getElementById("rgb-opacity");
  if (rgbOpacitySlider) {
    rgbOpacitySlider.value = Math.round(state.opacity * 100);
    document.getElementById("rgb-opacity-val").textContent = Math.round(state.opacity * 100) + "%";
  }
  // Show composite guide image while rendering
  const _guideImg = document.getElementById("loading-composite-img");
  const _guideUrl = RGB_GUIDE_IMAGESx[state.rgbComposite];
  if (_guideImg) {
    if (_guideUrl) {
      _guideImg.src = _guideUrl;
      _guideImg.style.display = "block";
    } else {
      _guideImg.style.display = "none";
    }
  }
  showLoading(true, `Rendering ${state.rgbComposite}…`);
  try {
    const quality = "normal";
    const params  = new URLSearchParams({ filepath: state.file, composite: state.rgbComposite, quality });
    const res = await fetch(`${API}/api/render_rgb?${params}`, { signal });
    if (!res.ok) {
      const e = await res.json();
      if (res.status === 409) {
      // Backend busy — cancel it and retry once after a short wait
      await fetch(`${API}/api/cancel_render`, { method: "POST" });
      await new Promise(r => setTimeout(r, 800));
      // retry
      _setRendering(false);
      showLoading(false);
      state.renderAbort = null;
      renderDataset();
      return;
    }
      throw new Error(e.detail || "RGB render failed");
    }
    const bounds  = res.headers.get("X-Bounds").split(",").map(Number);
    currentBounds = bounds; state.bounds = bounds; state.isRGBMode = true;
    // after: currentBounds = bounds;
    const fname = (state.file || "").split(/[\\/]/).pop();
      showTimestampOverlay({
        label: (state.rgbComposite || "RGB").replace(/_/g, " "),
        timestamp: res.headers.get("X-Timestamp") || _parseTimestampFromFilename(fname) || "",
      });
    const blob   = await res.blob();
    const imgUrl = URL.createObjectURL(blob);
    _lastImgUrl  = imgUrl;
    _addMapLayer(imgUrl, bounds);
    currentImageData = null; currentStats = null;

    document.getElementById("colorbar").style.display = "none";
    // Show the RGB guide button now that a composite is rendered
    const guideBtn = document.getElementById("rgb-guide-btn");
    if (guideBtn) guideBtn.style.display = "";
    document.getElementById("card-stats").style.display = "none";
  } catch(e) {
    if (e.name === "AbortError") {
      // User stopped render — no error shown
    } else {
      alert("RGB render error:\n" + e.message);
    }
  } finally {
    _setRenderingRGB(false);
    if (_guideImg) _guideImg.style.display = "none";
    showLoading(false);
    state.renderAbort = null;
  }
}
// ══════════════════════════════════════════════════════════════════════════════
//  MAP OVERLAYS
// ══════════════════════════════════════════════════════════════════════════════
const OVERLAY_SOURCES = {
  countries: {
    url: "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson",
    paint: { "line-color": "#424242", "line-width": 0.8 },
  },
  coasts: {
    url: "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_coastline.geojson",
    paint: { "line-color": "#424242", "line-width": 0.8 },
  },
};

// Cache fetched GeoJSON to avoid re-downloading on style swap
const _overlayGeojsonCache = {};

async function toggleOverlay(name, enable) {
  const layerId  = `overlay-${name}`;
  const sourceId = `overlay-src-${name}`;
  if (!enable) {
    if (map.getLayer(layerId))   map.removeLayer(layerId);
    if (map.getSource(sourceId)) map.removeSource(sourceId);
    return;
  }
  showLoading(true, `Loading ${name} overlay…`);
  try {
    const cfg = OVERLAY_SOURCES[name];
    if (!_overlayGeojsonCache[name]) {
      const resp = await fetch(cfg.url);
      if (!resp.ok) throw new Error(`Failed to fetch ${name} overlay`);
      _overlayGeojsonCache[name] = await resp.json();
    }
    const geojson = _overlayGeojsonCache[name];
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, { type: "geojson", data: geojson });
    }
    if (!map.getLayer(layerId)) {
      map.addLayer({ id: layerId, type: "line", source: sourceId, paint: cfg.paint });
    }
  } catch(e) {
    alert(`Overlay error: ${e.message}`);
    document.getElementById(`overlay-${name}`).checked = false;
  } finally {
    showLoading(false);
  }
}

function _restoreOverlays() {
  ["countries", "coasts"].forEach(name => {
    const chk = document.getElementById(`overlay-${name}`);
    if (chk && chk.checked) toggleOverlay(name, true);
  });
}

// ══════════════════════════════════════════════════════════════════════════════
//  UTILS
// ══════════════════════════════════════════════════════════════════════════════
function setLatest3h() {
  const now = new Date(), minus3 = new Date(now - 3 * 60 * 60 * 1000);
  document.getElementById("dl-end").value   = now.toISOString().slice(0, 16);
  document.getElementById("dl-start").value = minus3.toISOString().slice(0, 16);
}

function showLoading(v, msg) {
  const el = document.getElementById("loading-overlay");
  el.style.display = v ? "flex" : "none";
  if (msg) document.getElementById("loading-msg").textContent = msg;
}

function toggleCard(header) {
  header.closest(".card").classList.toggle("collapsed");
}



map.on("load", () => {
  _restoreOverlays();
});

// ══════════════════════════════════════════════════════════════════════════════
//  INIT
// ══════════════════════════════════════════════════════════════════════════════
(function initStarfield() {
  const canvas = document.getElementById("star-canvas");
  const ctx    = canvas.getContext("2d");
  let W, H, stars = [], shoots = [];

  function resize() {
  const wrap = document.getElementById("map-wrap");
  W = canvas.width  = wrap.offsetWidth;
  H = canvas.height = wrap.offsetHeight;
}
new ResizeObserver(resize).observe(document.getElementById("map-wrap"));
  resize();

  // Static stars
  for (let i = 0; i < 220; i++) {
    stars.push({ x: Math.random(), y: Math.random(), r: Math.random() * 1.2 + 0.2, a: Math.random() * 0.6 + 0.2 });
  }

  // Shooting star factory
  function spawnShoot() {
    const x = Math.random() * W;
    const y = Math.random() * H * 0.5;
    shoots.push({ x, y, vx: 3 + Math.random() * 4, vy: 1.5 + Math.random() * 2,
      life: 1, len: 60 + Math.random() * 80 });
  }
  // Spawn 1-2 every 8-20 s
  function scheduleShoot() {
    const count = Math.random() < 0.4 ? 2 : 1;
    for (let i = 0; i < count; i++) setTimeout(spawnShoot, i * 300);
    setTimeout(scheduleShoot, 8000 + Math.random() * 12000);
  }
  scheduleShoot();

  function draw() {
    // Only draw when globe is visible and no satellite / dark base covers it
    const show = state.isGlobe;
    canvas.style.opacity = show ? "1" : "0";

    ctx.clearRect(0, 0, W, H);
    if (!show) { requestAnimationFrame(draw); return; }

    // Static stars
    stars.forEach(s => {
      ctx.beginPath();
      ctx.arc(s.x * W, s.y * H, s.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255,255,255,${s.a})`;
      ctx.fill();
    });

    // Shooting stars
    shoots = shoots.filter(s => s.life > 0);
    shoots.forEach(s => {
      const tail = s.len * s.life;
      const grd  = ctx.createLinearGradient(s.x - s.vx * tail / s.vx, s.y - s.vy * tail / s.vy, s.x, s.y);
      grd.addColorStop(0, "rgba(255, 217, 0, 0)");
      grd.addColorStop(1, `rgba(255, 217, 0,${s.life * 0.9})`);
      ctx.beginPath();
      ctx.moveTo(s.x - (s.vx / Math.hypot(s.vx, s.vy)) * tail,
                 s.y - (s.vy / Math.hypot(s.vx, s.vy)) * tail);
      ctx.lineTo(s.x, s.y);
      ctx.strokeStyle = grd;
      ctx.lineWidth   = 1.5;
      ctx.stroke();
      s.x    += s.vx;
      s.y    += s.vy;
      s.life -= 0.018;
    });
    requestAnimationFrame(draw);
  }
  draw();
})();
buildCmaps();
refreshFiles();
loadCollections();

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".card").forEach(card => {
    const header = card.querySelector(".card-header.collapsible");
    if (header && header.textContent.includes("Download")) card.classList.add("collapsed");
  });
});

const now = new Date(), minus1 = new Date(now - 24*60*60*1000);
document.getElementById("dl-end").value   = now.toISOString().slice(0,16);
document.getElementById("dl-start").value = minus1.toISOString().slice(0,16);

// ══════════════════════════════════════════════════════════════════════════════
//  PNG IMAGE OVERLAY  — client-side only, no backend needed
//  Full Meteosat disk PNGs are already reprojected to Web Mercator by satpy,
//  so we just need to supply the correct geographic bounding box.
// ══════════════════════════════════════════════════════════════════════════════

const _PNG_PRESETS = {
  // FCI / MTG-I full disk: satpy default output after kd_tree resample to WGS84
  // Covers roughly ±81° lat/lon from sub-satellite point at 0°E
  fulldisk: { west: -81,  south: -81,  east: 81,  north: 81,  label: "FCI full disk" },

  // MSG / SEVIRI full disk — slightly tighter than FCI due to older instrument
  seviri:   { west: -77,  south: -77,  east: 77,  north: 77,  label: "SEVIRI full disk" },

  // Europe subregion — typical for rapid-scan or subsetted products
  europe:   { west: -25,  south: 25,   east: 50,  north: 75,  label: "Europe" },

  // True global — for reprocessed or mosaic products
  global:   { west: -180, south: -90,  east: 180, north: 90,  label: "Global" },
};

let _pngSourceId    = "png-overlay-src";
let _pngLayerId     = "png-overlay-layer";
let _pngBlobUrl     = null;
let _pngCurrentPreset = "fulldisk";  // default preset
let _pngManualOpen  = false;

// Apply a preset and highlight the active button
function setPngPreset(key) {
  const p = _PNG_PRESETS[key];
  if (!p) return;
  _pngCurrentPreset = key;
  document.getElementById("png-west").value  = p.west;
  document.getElementById("png-south").value = p.south;
  document.getElementById("png-east").value  = p.east;
  document.getElementById("png-north").value = p.north;

  // Visual feedback on which preset is active
  Object.keys(_PNG_PRESETS).forEach(k => {
    const btn = document.getElementById(`preset-${k}`);
    if (btn) btn.classList.toggle("active", k === key);
  });

  const statusEl = document.getElementById("png-status");
  statusEl.textContent = `Bounds: ${p.west}, ${p.south}, ${p.east}, ${p.north}  (${p.label})`;
  statusEl.style.color = "var(--muted)";
  statusEl.style.display = "block";
}

function togglePngManual() {
  _pngManualOpen = !_pngManualOpen;
  document.getElementById("png-bounds-manual").style.display = _pngManualOpen ? "" : "none";
}

function handlePngUpload(input) {
  const file = input.files[0];
  if (!file) return;

  if (_pngBlobUrl) { URL.revokeObjectURL(_pngBlobUrl); _pngBlobUrl = null; }
  _pngBlobUrl = URL.createObjectURL(file);

  const nameEl = document.getElementById("png-file-name");
  nameEl.textContent = `${file.name}  (${(file.size / 1024 / 1024).toFixed(1)} MB)`;
  nameEl.style.display = "block";

  // Read image dimensions and append
  const img = new Image();
  img.onload = () => {
    nameEl.textContent += `  —  ${img.width} × ${img.height} px`;

    // Auto-detect preset from filename heuristics
    const fn = file.name.toLowerCase();
    if (fn.includes("fci") || fn.includes("mtg"))      setPngPreset("fulldisk");
    else if (fn.includes("seviri") || fn.includes("msg")) setPngPreset("seviri");
    else if (fn.includes("glob"))                        setPngPreset("global");
    else                                                 setPngPreset("fulldisk"); // safe default
  };
  img.src = _pngBlobUrl;

  document.getElementById("png-render-btn").disabled = false;
  document.getElementById("png-status").style.display = "none";
}

function setPngOpacity(val) {
  document.getElementById("png-opacity-val").textContent = val + "%";
  if (map.getLayer(_pngLayerId)) {
    map.setPaintProperty(_pngLayerId, "raster-opacity", val / 100);
  }
  // Batch mode (multiple PNGs loaded as animation frames) renders onto the
  // anim crossfade layer, not _pngLayerId — update that live too, or the
  // slider visually moves but nothing changes until the next renderPng() call.
  if (_pngIsAnimBatch) {
    const activeLyr = _layerId(_activeSlot);
    if (map.getLayer(activeLyr)) map.setPaintProperty(activeLyr, "raster-opacity", val / 100);
  }
}

// NOTE: renderPng() lives below — this earlier single-image-only version
// was dead code (the second definition silently shadowed it in JS, same
// as the _reproject_rgb_bands duplicate in the Python backend). Removed
// to avoid confusion; nothing here was actually running.

function removePng() {
  if (_pngIsAnimBatch) {
    closeAnimation();          // existing function: stops play, hides anim-bar, clears state.animFrames
    state.isRGBMode = false;
  } else {
    _removePngLayer();
  }
  document.getElementById("png-remove-btn").style.display = "none";
  const statusEl = document.getElementById("png-status");
  statusEl.textContent = "Overlay removed.";
  statusEl.style.color = "var(--muted)";
  statusEl.style.display = "block";
}
function _removePngLayer() {
  if (map.getLayer(_pngLayerId))   map.removeLayer(_pngLayerId);
  if (map.getSource(_pngSourceId)) map.removeSource(_pngSourceId);
}

// Re-place PNG after any style swap (globe ↔ mercator, base layer change)
map.on("style.load", () => {
  if (_pngBlobUrl && document.getElementById("png-remove-btn").style.display !== "none") {
    setTimeout(renderPng, 80);
  }
});


// ══════════════════════════════════════════════════════════════════════════
//  PNG MULTI-FRAME STATE  (new)
// ══════════════════════════════════════════════════════════════════════════
let _pngFrames = [];      // [{name, url, file}, ...] sorted
let _pngFrameIdx = 0;
let _pngIsAnimBatch = false; // true when >1 file uploaded this batch

// Natural sort: "2_x" before "10_x" (plain string sort would do the opposite)
function _naturalSort(a, b) {
  const re = /(\d+)/g;
  const ax = a.name.split(re), bx = b.name.split(re);
  const n = Math.max(ax.length, bx.length);
  for (let i = 0; i < n; i++) {
    const av = ax[i] || "", bv = bx[i] || "";
    const an = parseInt(av, 10), bn = parseInt(bv, 10);
    if (!isNaN(an) && !isNaN(bn)) {
      if (an !== bn) return an - bn;
    } else if (av !== bv) {
      return av < bv ? -1 : 1;
    }
  }
  return 0;
}

function handlePngUpload(input) {
  const files = Array.from(input.files || []);
  if (!files.length) return;

  // Revoke any previous batch's object URLs before building a new one
  _pngFrames.forEach(f => URL.revokeObjectURL(f.url));
  _pngFrames = [];
  _pngFrameIdx = 0;

  const sorted = files.map(f => ({ name: f.name, file: f })).sort(_naturalSort);
  _pngFrames = sorted.map(f => ({ name: f.name, url: URL.createObjectURL(f.file) }));
  _pngIsAnimBatch = _pngFrames.length > 1;

  // Keep existing single-image variables in sync so renderPng()/preset
  // auto-detect logic keeps working unchanged for the single-file case.
  _pngBlobUrl = _pngFrames[0].url;

  const nameEl = document.getElementById("png-file-name");
  if (_pngIsAnimBatch) {
    nameEl.textContent = `${_pngFrames.length} frames \u2014 ${_pngFrames[0].name} \u2026 ${_pngFrames[_pngFrames.length-1].name}`;
    nameEl.style.display = "block";
  } else {
    nameEl.textContent = `${files[0].name}  (${(files[0].size / 1024 / 1024).toFixed(1)} MB)`;
    nameEl.style.display = "block";
  }

  // Auto-detect preset from the first filename, same heuristic as before
  const fn = _pngFrames[0].name.toLowerCase();
  if (fn.includes("fci") || fn.includes("mtg"))         setPngPreset("fulldisk");
  else if (fn.includes("seviri") || fn.includes("msg")) setPngPreset("seviri");
  else if (fn.includes("glob"))                          setPngPreset("global");
  else                                                    setPngPreset("fulldisk");

  document.getElementById("png-render-btn").disabled = false;
  document.getElementById("png-render-btn").textContent =
    _pngIsAnimBatch ? `🌍 Place ${_pngFrames.length} frames on globe` : "🌍 Place on globe";
  document.getElementById("png-status").style.display = "none";
}


function renderPng() {
  if (!_pngFrames.length) { alert("Choose a PNG file first."); return; }

  const west  = parseFloat(document.getElementById("png-west").value);
  const south = parseFloat(document.getElementById("png-south").value);
  const east  = parseFloat(document.getElementById("png-east").value);
  const north = parseFloat(document.getElementById("png-north").value);
  const opacity = parseFloat(document.getElementById("png-opacity").value) / 100;

  if ([west, south, east, north].some(isNaN)) { alert("Check bounds — all four must be numbers."); return; }
  if (west >= east)   { alert("West must be less than East.");   return; }
  if (south >= north) { alert("South must be less than North."); return; }

  const bounds = [west, south, east, north];

  if (!_pngIsAnimBatch) {
    // ── existing single-image path, unchanged ──
    const coords = [[west, north], [east, north], [east, south], [west, south]];
    _removePngLayer();
    try {
      map.addSource(_pngSourceId, { type: "image", url: _pngBlobUrl, coordinates: coords });
      map.addLayer({
        id: _pngLayerId, type: "raster", source: _pngSourceId,
        paint: { "raster-opacity": opacity, "raster-fade-duration": 400, "raster-resampling": _resamplingMode },
      });
      ["overlay-countries", "overlay-coasts"].forEach(id => { if (map.getLayer(id)) map.moveLayer(id); });
      map.fitBounds([[west, south], [east, north]], { padding: 40, duration: 1000 });

      const statusEl = document.getElementById("png-status");
      statusEl.textContent = `✓ Placed — bounds [${west}, ${south}, ${east}, ${north}]`;
      statusEl.style.color = "var(--accent2)";
      statusEl.style.display = "block";
      document.getElementById("png-remove-btn").style.display = "";
    } catch(e) {
      alert("Failed to place PNG:\n" + e.message);
    }
    return;
  }

  // ── batch path: drive the existing anim-bar with PNG frames ──
  // Build frames in the same shape _showAnimFrame()/animPlayPause()/animStep() expect.
  state.animFrames = _pngFrames.map(f => ({ filepath: f.name, url: f.url, bounds }));
  state.animFrame  = 0;
  state.isRGBMode  = true; // PNG overlays carry no scalar data — disable tooltip/colorbar lookups

  document.getElementById("anim-progress").max   = state.animFrames.length - 1;
  document.getElementById("anim-progress").value = 0;
  document.getElementById("anim-label").textContent = `1/${state.animFrames.length}`;
  document.getElementById("anim-bar").style.display = "flex";

  // Hide the scalar colorbar — these are RGB/composite PNGs, not single-band data
  document.getElementById("colorbar").style.display = "none";

  _showAnimFrame(0);
  map.fitBounds([[west, south], [east, north]], { padding: 40, duration: 1000 });

  const statusEl = document.getElementById("png-status");
  statusEl.textContent = `✓ ${state.animFrames.length} frames loaded — use the animation bar below the map`;
  statusEl.style.color = "var(--accent2)";
  statusEl.style.display = "block";
  document.getElementById("png-remove-btn").style.display = "";

  // Apply the chosen opacity to whichever map slot is currently active
  const activeLyr = _layerId(_activeSlot);
  if (map.getLayer(activeLyr)) map.setPaintProperty(activeLyr, "raster-opacity", opacity);
}











// Initialise with full-disk preset selected visually on page load
document.addEventListener("DOMContentLoaded", () => {
  setPngPreset("fulldisk");
});
