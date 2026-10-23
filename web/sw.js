// Bump this version whenever a shell asset changes. Keep updates waiting until
// all old clients close, so one page never mixes modules from different releases.
const CACHE_PREFIX = "process-aquarium-shell-";
const CACHE_NAME = `${CACHE_PREFIX}v1`;
const SHELL = [
  "./", "./aquarium.css", "./app.mjs", "./pwa.mjs",
  "./world.mjs", "./renderer.mjs", "./controls.mjs", "./menu.mjs",
  "./fish.mjs", "./geometry.mjs", "./multiverse.mjs", "./backgrounds.mjs",
  "./tides.mjs", "./intertank.mjs", "./effects.mjs",
  "./manifest.webmanifest", "./icons/icon-180.png",
  "./icons/icon-192.png", "./icons/icon-512.png",
].map(path => new URL(path, self.registration.scope).href);

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(SHELL.map(url => new Request(url, { cache: "reload" })));
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
        await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  const scope = new URL(self.registration.scope);
  // Never intercept API, health checks, uploads, authenticated requests, or
  // other origins. No telemetry, tokens, or query strings enter Cache Storage.
  if (request.method !== "GET" || url.origin !== scope.origin ||
      request.headers.has("Authorization")) return;
  const isHome = request.mode === "navigate" && url.pathname === scope.pathname;
  if (!isHome && (url.search || !SHELL.includes(url.href))) return;
  const key = isHome ? scope.href : url.href;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(key);
    // Only the versioned, precached shell is read here; runtime requests never
    // write responses to the cache. A navigation's ?host= remains in the URL.
    return cached || fetch(request);
  })());
});
