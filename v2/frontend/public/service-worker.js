/* AI BOT V2 — cache-only service worker.
 *
 * SAFETY CONTRACT (per CLAUDE.md and 16_MOBILE_IPHONE_AND_PWA_READINESS.md):
 *   - This worker NEVER caches mutating responses.
 *   - This worker NEVER performs background sync of trade actions.
 *   - This worker NEVER replays POST/PUT/PATCH/DELETE requests.
 *   - The cache stores read-only static assets only.
 *   - All API responses are passed through to the network without caching.
 */

const STATIC_CACHE = 'aibot-v2-static-v1';
const STATIC_ASSETS = ['/', '/index.html', '/manifest.webmanifest'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => undefined),
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== STATIC_CACHE).map((k) => caches.delete(k))),
    ),
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;

  // Hard rule: only GET requests are eligible for cache-only handling.
  if (req.method !== 'GET') {
    // Pass-through: never cache, never replay, never queue. The browser handles it.
    return;
  }

  const url = new URL(req.url);

  // API responses are always network-only and never cached.
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  event.respondWith(
    caches.match(req).then((hit) => {
      if (hit) return hit;
      return fetch(req)
        .then((res) => {
          // Cache only successful, basic, GET, non-API responses.
          if (res && res.status === 200 && res.type === 'basic' && !url.pathname.startsWith('/api/')) {
            const clone = res.clone();
            caches.open(STATIC_CACHE).then((cache) => cache.put(req, clone)).catch(() => undefined);
          }
          return res;
        })
        .catch(() => caches.match('/index.html'));
    }),
  );
});

// Background sync and push handlers are intentionally NOT registered.
// Per 16_MOBILE_IPHONE_AND_PWA_READINESS.md, push for L4/L5 approvals is
// designed in but disabled in milestone E. No background trade actions ever.
