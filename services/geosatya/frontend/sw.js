/* GeoSatya service worker: lets the installed app open without a signal.

   - App files (HTML, CSS, JS, icons, Leaflet): network first, cached copy when offline.
   - Map tiles: cached as they are viewed (capped), so a job's map still shows offline.
   - /api/ is never cached here: personal data stays out of the shared cache. The app
     keeps its own per-user snapshot of the worker's tasks (js/outbox.js) and queues
     actions taken offline, sending them when the connection returns. */

const VERSION = "geosatya-v1";
const SHELL = `${VERSION}-shell`, TILES = `${VERSION}-tiles`, MAX_TILES = 400;
const SHELL_FILES = [
  "/", "/index.html", "/styles.css", "/config.js", "/manifest.webmanifest",
  "/icons/icon-192.png", "/icons/icon-512.png", "/icons/maskable-512.png", "/icons/apple-touch-icon.png",
  "/js/app.js", "/js/api.js", "/js/capture.js", "/js/components.js", "/js/live.js", "/js/maps.js", "/js/ui.js", "/js/outbox.js",
  "/js/pages/board.js", "/js/pages/dashboard.js", "/js/pages/history.js", "/js/pages/incident.js", "/js/pages/livemap.js",
  "/js/pages/report.js", "/js/pages/review.js", "/js/pages/settings.js", "/js/pages/tasks.js",
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css", "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((cache) =>
    // One missing file must not stop the app from installing.
    Promise.allSettled(SHELL_FILES.map((url) => cache.add(new Request(url, { cache: "reload" }))))));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

async function networkFirst(request, cacheName, fallbackUrl) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response.ok && (response.type === "basic" || response.type === "cors")) cache.put(request, response.clone());
    return response;
  } catch {
    return (await cache.match(request, { ignoreSearch: true })) || (fallbackUrl && (await cache.match(fallbackUrl)))
      || new Response("Offline", { status: 503, headers: { "Content-Type": "text/plain" } });
  }
}

async function tileCacheFirst(request) {
  const cache = await caches.open(TILES);
  const hit = await cache.match(request);
  if (hit) return hit;
  try {
    const response = await fetch(request);
    if (response.ok || response.type === "opaque") {
      await cache.put(request, response.clone());
      const keys = await cache.keys();
      for (const old of keys.slice(0, Math.max(0, keys.length - MAX_TILES))) await cache.delete(old);
    }
    return response;
  } catch {
    return new Response("", { status: 504 });
  }
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;                         // actions go through the app's outbox
  const url = new URL(request.url);
  if (url.origin === self.location.origin && url.pathname.startsWith("/api/")) return;   // never cache API data
  if (url.hostname.endsWith("tile.openstreetmap.org")) { event.respondWith(tileCacheFirst(request)); return; }
  if (request.mode === "navigate") { event.respondWith(networkFirst(request, SHELL, "/index.html")); return; }
  if (url.origin === self.location.origin || url.hostname === "unpkg.com" || url.hostname.endsWith("googleapis.com")
      || url.hostname.endsWith("gstatic.com")) {
    event.respondWith(networkFirst(request, SHELL));
  }
});
