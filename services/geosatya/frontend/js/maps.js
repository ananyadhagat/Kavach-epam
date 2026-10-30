/* Map adapter: Google Maps when GOOGLE_MAPS_BROWSER_KEY is configured and
   loads; otherwise Leaflet + OpenStreetMap. Pages only use this interface. */

import { session } from "./api.js";

export const KINDS = {
  target: { color: "#0A1630", label: "Incident location" },
  me: { color: "#2F6BFF", label: "Your location" },
  simulated: { color: "#7C3AED", label: "Simulated location" },
  exif: { color: "#0E7490", label: "Photo's own GPS" },
  pin: { color: "#EA580C", label: "User-selected location" },
  worker: { color: "#16A34A", label: "Field worker (shared location)" },
};
let googlePromise = null;
let fallbackReason = null;

export const mapProviderName = () => (fallbackReason ? `OpenStreetMap (${fallbackReason})`
  : session.config?.maps?.provider === "google" ? "Google Maps" : "OpenStreetMap");

function loadGoogle(key) {
  googlePromise ||= new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Google Maps took too long to load")), 12000);
    window.gm_authFailure = () => { fallbackReason = "Google key rejected"; reject(new Error("Google Maps rejected the key")); };
    window.__geosatyaGoogleReady = () => { clearTimeout(timer); resolve(window.google.maps); };
    const script = document.createElement("script");
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&loading=async&callback=__geosatyaGoogleReady`;
    script.async = true;
    script.onerror = () => { clearTimeout(timer); reject(new Error("Google Maps failed to load")); };
    document.head.append(script);
  });
  return googlePromise;
}

export async function createMap(el, { center, zoom = 18, onClick } = {}) {
  const cfg = session.config?.maps || {};
  if (cfg.provider === "google" && cfg.google_browser_key && !fallbackReason) {
    try { return googleMap(await loadGoogle(cfg.google_browser_key), el, center, zoom, onClick); }
    catch (err) { fallbackReason ||= err.message; }
  }
  if (!window.L) {
    const note = document.createElement("div");
    note.className = "map-fallback";
    note.textContent = "The map can't load offline. Coordinates are shown beside it.";
    el.replaceChildren(note);
    return { marker() {}, circle() {}, html() {}, line() {}, ids: () => [], remove() {}, fit() {}, setView() {}, destroy() {} };
  }
  return leafletMap(el, center, zoom, onClick);
}

function leafletMap(el, center, zoom, onClick) {
  const map = L.map(el, { scrollWheelZoom: false }).setView(center || [23.2599, 77.4126], zoom);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors" }).addTo(map);
  const layers = new Map();
  if (onClick) map.on("click", (e) => onClick([e.latlng.lat, e.latlng.lng]));
  const drop = (id) => { if (layers.has(id)) { map.removeLayer(layers.get(id)); layers.delete(id); } };
  return {
    marker(id, kind, ll, label) {
      drop(id);
      const color = KINDS[kind].color;
      const layer = (kind === "target" || kind === "pin")
        ? L.marker(ll, { title: label, icon: L.divIcon({ className: "", html: `<span class="pin" style="--pin:${color}"></span>`, iconSize: [26, 36], iconAnchor: [13, 34] }) })
        : L.circleMarker(ll, { radius: 8, color: "#fff", weight: 2, fillColor: color, fillOpacity: 1 });
      layer.bindTooltip(label || KINDS[kind].label).addTo(map);
      layers.set(id, layer);
    },
    circle(id, ll, radius, kind) {
      drop(id);
      layers.set(id, L.circle(ll, { radius, color: KINDS[kind].color, weight: 2, dashArray: kind === "target" ? "6 5" : null,
        fillOpacity: kind === "target" ? 0.1 : 0.12 }).addTo(map));
    },
    /* A custom marker. `html` must be built from escaped text (see esc()). */
    html(id, ll, html, label, onClick, size = 34) {
      drop(id);
      const layer = L.marker(ll, { title: label, icon: L.divIcon({ className: "", html, iconSize: [size, size], iconAnchor: [size / 2, size / 2] }) });
      layer.bindTooltip(label);
      if (onClick) layer.on("click", onClick);
      layers.set(id, layer.addTo(map));
    },
    line(id, points, color, dashed = false, weight = null) {
      drop(id);
      layers.set(id, L.polyline(points, { color, weight: weight || (dashed ? 2 : 5), opacity: dashed ? 0.7 : 0.85, dashArray: dashed ? "6 8" : null }).addTo(map));
    },
    ids: () => [...layers.keys()],
    remove: drop,
    fit(points) {
      const pts = points.filter(Boolean);
      // No animation: a page that re-renders mid-zoom would otherwise destroy the map under a running animation.
      if (pts.length === 1) map.setView(pts[0], 18, { animate: false });
      else if (pts.length > 1) map.fitBounds(L.latLngBounds(pts), { padding: [40, 40], maxZoom: 19, animate: false });
    },
    setView(ll, z) { map.setView(ll, z || map.getZoom(), { animate: false }); },
    destroy() { map.stop(); map.remove(); },
  };
}

function googleMap(maps, el, center, zoom, onClick) {
  const cfg = session.config.maps;
  const map = new maps.Map(el, { center: center ? { lat: center[0], lng: center[1] } : { lat: 23.2599, lng: 77.4126 }, zoom,
    mapId: cfg.google_map_id || undefined, streetViewControl: false, mapTypeControl: false, fullscreenControl: false, gestureHandling: "cooperative" });
  const items = new Map();
  if (onClick) map.addListener("click", (e) => onClick([e.latLng.lat(), e.latLng.lng()]));
  const drop = (id) => { if (items.has(id)) { items.get(id).setMap(null); items.delete(id); } };
  const pos = (ll) => ({ lat: ll[0], lng: ll[1] });
  return {
    marker(id, kind, ll, label) {
      drop(id);
      items.set(id, new maps.Marker({ map, position: pos(ll), title: label || KINDS[kind].label, icon: {
        path: maps.SymbolPath.CIRCLE, scale: kind === "target" || kind === "pin" ? 10 : 8, fillColor: KINDS[kind].color,
        fillOpacity: 1, strokeColor: "#ffffff", strokeWeight: 2 } }));
    },
    circle(id, ll, radius, kind) {
      drop(id);
      items.set(id, new maps.Circle({ map, center: pos(ll), radius, strokeColor: KINDS[kind].color, strokeWeight: 2,
        fillColor: KINDS[kind].color, fillOpacity: kind === "target" ? 0.1 : 0.12, clickable: false }));
    },
    html(id, ll, _html, label, onClick) {  // Google fallback: plain labelled marker
      drop(id);
      const m = new maps.Marker({ map, position: pos(ll), title: label });
      if (onClick) m.addListener("click", onClick);
      items.set(id, m);
    },
    line(id, points, color, dashed = false, weight = null) {
      drop(id);
      items.set(id, new maps.Polyline({ map, path: points.map(pos), strokeColor: color, strokeOpacity: dashed ? 0.6 : 0.85, strokeWeight: weight || (dashed ? 2 : 5) }));
    },
    ids: () => [...items.keys()],
    remove: drop,
    fit(points) {
      const pts = points.filter(Boolean);
      if (pts.length === 1) { map.setCenter(pos(pts[0])); map.setZoom(18); }
      else if (pts.length > 1) { const b = new maps.LatLngBounds(); pts.forEach((p) => b.extend(pos(p))); map.fitBounds(b, 40); }
    },
    setView(ll, z) { map.setCenter(pos(ll)); if (z) map.setZoom(z); },
    destroy() { items.forEach((i) => i.setMap(null)); items.clear(); },
  };
}

/* Escape text for the few places that build marker HTML. */
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function legend(kinds) {
  const wrap = document.createElement("div");
  wrap.className = "legend";
  for (const k of kinds) {
    const item = document.createElement("span"), dot = document.createElement("i");
    dot.style.background = KINDS[k].color;
    item.append(dot, KINDS[k].label);
    wrap.append(item);
  }
  return wrap;
}
