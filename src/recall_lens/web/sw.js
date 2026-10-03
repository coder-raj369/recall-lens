// Offline shell: the page opens without a network; checks always need one.
const CACHE = "recall-lens-v1";
const SHELL = ["./", "styles.css", "app.js", "manifest.webmanifest", "icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
});

// Network first, so a new version shows at once; the cache answers only when offline.
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET" || event.request.url.includes("/watches/")) return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
