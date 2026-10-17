// Retirement Plan -- minimal service worker.
//
// Deliberately does NOT cache any page (summary.html, asset.html, the
// /api/* endpoints, ...) -- every one of those reflects this program's
// live database state, and a money dashboard that could show a stale
// balance from a service-worker cache is worse than one that just
// fails to load without a network connection. The only things this
// caches are genuinely static, version-stamped-by-filename assets: the
// app icons and the manifest itself, so "Add to Home Screen" still has
// something to show if the Mac this talks to is briefly unreachable.
//
// Everything else is a plain network pass-through; the only added
// behavior is a friendly offline page instead of the browser's own
// connection-error screen when a page navigation fails outright (the
// Mac this dashboard runs on is off, asleep, or unreachable).

const CACHE_NAME = "retirement-plan-static-v2";
const STATIC_ASSETS = [
  "/manifest.json",
  "/icons/logo.svg",
  "/icons/icon-180.png",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => {}),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n))),
    ),
  );
  self.clients.claim();
});

function isStaticAsset(url) {
  return url.pathname === "/manifest.json" || url.pathname.startsWith("/icons/");
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  if (event.request.method !== "GET" || url.origin !== self.location.origin) {
    return; // never intercept a POST/API write, or a cross-origin request
  }

  if (isStaticAsset(url)) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request)),
    );
    return;
  }

  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() =>
        new Response(
          "<!doctype html><meta charset=utf-8><meta name=viewport content=\"width=device-width, initial-scale=1\">" +
            "<title>Offline</title>" +
            "<body style=\"font-family:-apple-system,sans-serif;max-width:380px;margin:20vh auto;text-align:center;color:#0f172a;padding:0 20px;\">" +
            "<h1 style=\"font-size:18px;\">Can't reach your Mac</h1>" +
            "<p style=\"color:#64748b;font-size:14px;\">This dashboard runs on your own Mac, so it only works while that Mac is on, awake, and reachable. Try again in a moment.</p>" +
            "</body>",
          { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } },
        ),
      ),
    );
    return;
  }

  // Everything else (every *.html tab, every /api/* call) is a plain,
  // uncached pass-through -- always the live network response.
});
