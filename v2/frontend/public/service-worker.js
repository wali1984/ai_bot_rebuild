/* NERVYX ONE — cache-only service worker.
 *
 * SAFETY CONTRACT (per CLAUDE.md and 16_MOBILE_IPHONE_AND_PWA_READINESS.md):
 *   - This worker NEVER caches mutating responses.
 *   - This worker NEVER performs background sync of trade actions.
 *   - This worker NEVER replays POST/PUT/PATCH/DELETE requests.
 *   - The cache stores read-only static assets only.
 *   - All API responses are passed through to the network without caching.
 */

// Bump on any SPA bundle change so the new SW invalidates older caches
// that may still hold a stale built bundle. The activate handler deletes
// every cache whose name differs from STATIC_CACHE on the next page load,
// so changing this constant is sufficient to evict stale assets.
const STATIC_CACHE = 'nervyx-one-static-v2-20260713';
const STATIC_ASSETS = ['/manifest.webmanifest'];

// Hard list of root paths that must never be served from cache. The
// activate handler also deletes them from the current cache so a user
// whose browser cached an older index.html or root document picks up the
// freshly built SPA on the next reload.
const FORCE_NETWORK_ROOT_PATHS = ['/', '/index.html', '/landing', '/landing-legacy'];

function isRealtimePayload(url) {
  const path = url.pathname;
  return (
    path.endsWith('.json') ||
    path.endsWith('.md') ||
    path.startsWith('/operator_runtime/') ||
    path.startsWith('/v2_') ||
    path.startsWith('/dashboards/') ||
    path.startsWith('/production_') ||
    path.startsWith('/active_autonomous_dispatch/') ||
    path.startsWith('/autonomous_governor/') ||
    path.startsWith('/paper_') ||
    path.startsWith('/runtime_') ||
    path.includes('/latest/')
  );
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => undefined),
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // 1. Drop every cache other than the current STATIC_CACHE — this
      //    evicts older static bundles a previous SW version installed.
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((k) => k !== STATIC_CACHE).map((k) => caches.delete(k)),
      );
      // 2. Inside the current cache, force-evict the SPA shell entries so
      //    the next navigation re-fetches index.html from the network and
      //    picks up the freshly hashed asset URLs.
      try {
        const cache = await caches.open(STATIC_CACHE);
        await Promise.all(
          FORCE_NETWORK_ROOT_PATHS.map((path) => cache.delete(path)),
        );
      } catch (_err) {
        // Cache eviction is best-effort; the network-first index handler
        // below will still return fresh HTML for these paths.
      }
      // 3. Take control of all open tabs so the new SW handles their next
      //    fetch immediately, without requiring a manual reload.
      await self.clients.claim();
    })(),
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;

  // Hard rule: only GET requests are eligible for cache-only handling.
  if (req.method !== 'GET') {
    // Pass-through: never cache, never replay, never queue. The browser handles it.
    return;
  }

  const url = new URL(req.url);

  // API and runtime/report payloads are always network-only and never cached.
  if (url.pathname.startsWith('/api/') || isRealtimePayload(url)) {
    event.respondWith(fetch(req, { cache: 'no-store' }));
    return;
  }

  // SPA shell paths are always network-first. We never want to serve a
  // cached older HTML/landing that points at a stale bundle hash. Applies to
  // EVERY navigation (any SPA route refresh), not just the root path list.
  if (req.mode === 'navigate' || FORCE_NETWORK_ROOT_PATHS.includes(url.pathname)) {
    event.respondWith(
      fetch(req, { cache: 'no-store' }).catch(() =>
        caches.match('/index.html'),
      ),
    );
    return;
  }

  // Never cache Vite dev-server module paths — they contain HMR transforms
  // that only work with the exact running server instance.
  const isViteDevPath = (
    url.pathname.startsWith('/src/') ||
    url.pathname.startsWith('/@') ||
    url.pathname.startsWith('/node_modules/') ||
    url.search.includes('?import') ||
    url.search.includes('?t=') ||
    url.search.includes('v=')
  );
  if (isViteDevPath) {
    event.respondWith(fetch(req, { cache: 'no-store' }));
    return;
  }

  event.respondWith(
    fetch(req)
      .then((res) => {
        // Cache only successful, basic, GET, non-API, non-dev responses.
        if (res && res.status === 200 && res.type === 'basic' && !url.pathname.startsWith('/api/')) {
          const clone = res.clone();
          caches.open(STATIC_CACHE).then((cache) => cache.put(req, clone)).catch(() => undefined);
        }
        return res;
      })
      .catch(() => caches.match(req).then((hit) => hit || caches.match('/index.html'))),
  );
});

// Background sync and push handlers are intentionally NOT registered.
// Per 16_MOBILE_IPHONE_AND_PWA_READINESS.md, push for L4/L5 approvals is
// designed in but disabled in milestone E. No background trade actions ever.
