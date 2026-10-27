// Service worker that keeps a copy of the base-map tiles the app has shown, so a
// rehearsed demo still has a map when the venue has no internet.
//
// Network first: online, tiles come from the tile server as usual (normal
// browser caching applies) and a copy is stored. Offline, or when the network
// takes longer than TIMEOUT_MS, the stored copy is used. Nothing is downloaded
// in advance: the OpenStreetMap tile policy forbids bulk downloading, so only
// tiles you actually looked at while rehearsing are available offline.

const CACHE = "s2r-tiles-v1";
const TILE_HOST = "tile.openstreetmap.org";
const MAX_TILES = 3000; // roughly 60 MB
const TIMEOUT_MS = 3000;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  if (new URL(event.request.url).hostname !== TILE_HOST) return;
  event.respondWith(tile(event.request));
});

async function tile(request) {
  const cache = await caches.open(CACHE);
  try {
    const response = await withTimeout(fetch(request), TIMEOUT_MS);
    if (response.ok) {
      await cache.put(request, response.clone());
      trim(cache);
    }
    return response;
  } catch {
    const cached = await cache.match(request);
    if (cached) return cached;
    return Response.error(); // the map shows it as a missing tile and switches to its offline look
  }
}

function withTimeout(promise, ms) {
  return Promise.race([promise, new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), ms))]);
}

async function trim(cache) {
  const keys = await cache.keys(); // oldest first
  await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_TILES)).map((key) => cache.delete(key)));
}
