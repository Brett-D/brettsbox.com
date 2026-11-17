/* Service worker for the golf PWA: keeps the app shell available offline so the installed app
   always opens. API calls (/api/golf/*) are never cached; the tee sheet is always live. */
const VERSION = "golf-shell-v7";
const SHELL = [
  "/golf/",
  "/golf/theme.js",
  "/golf/style.css",
  "/golf/app.js",
  "/golf/manifest.webmanifest",
  "/assets/fonts/Inter-Variable.woff2",
  "/golf/icons/icon.svg",
  "/golf/icons/icon-192.png",
  "/golf/icons/icon-512.png",
  "/golf/icons/maskable-512.png",
  "/golf/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith("golf-shell-") && key !== VERSION).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

// Network first, so a new release shows up on the next open; the cached shell is the offline fallback.
self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  const inShell = url.pathname.startsWith("/golf/") || url.pathname === "/assets/fonts/Inter-Variable.woff2";
  if (request.method !== "GET" || url.origin !== self.location.origin || !inShell) return;

  event.respondWith((async () => {
    const cache = await caches.open(VERSION);
    try {
      const response = await fetch(request);
      if (response.ok && response.type === "basic") {
        cache.put(request.mode === "navigate" ? "/golf/" : request, response.clone());
      }
      return response;
    } catch (error) {
      const cached = await cache.match(request.mode === "navigate" ? "/golf/" : request, { ignoreSearch: true });
      if (cached) return cached;
      throw error;
    }
  })());
});
