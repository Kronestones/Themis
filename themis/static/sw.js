const APP_CACHE  = "themis-app-v2";
const TILE_CACHE = "themis-tiles-v1";
const MAX_TILES  = 500;
const APP_SHELL  = ["/", "/static/manifest.json"];

self.addEventListener("install", event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(APP_CACHE).then(cache => cache.addAll(APP_SHELL))
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== APP_CACHE && k !== TILE_CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);

  if (url.hostname.includes("basemaps.cartocdn.com") || url.hostname.includes("tile.openstreetmap.org")) {
    event.respondWith(handleTile(event.request));
    return;
  }

  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(event.request).catch(() =>
        new Response(JSON.stringify({error: "Offline"}), {headers: {"Content-Type": "application/json"}})
      )
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(APP_CACHE).then(c => c.put(event.request, clone));
        }
        return response;
      }).catch(() => caches.match("/"));
    })
  );
});

async function handleTile(request) {
  const cache  = await caches.open(TILE_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const keys = await cache.keys();
      if (keys.length >= MAX_TILES) await cache.delete(keys[0]);
      await cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response(
      '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#1a1a2e"/></svg>',
      {headers: {"Content-Type": "image/svg+xml"}}
    );
  }
}
