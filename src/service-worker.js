/**
 * MooOS Service Worker — Offline-First Strategy
 *
 * Strategy:
 * - App Shell (HTML, CSS, JS): Cache-First → Load instantly, even offline
 * - API calls to localhost:8000: Network-First → Always try live data,
 *   fall back to last cached response if offline
 * - Images/assets: Cache-First with network fallback
 */

const CACHE_NAME = "mooos-v1";
const API_CACHE_NAME = "mooos-api-v1";
const BACKEND_BASE = "http://localhost:8000";

// App shell — static assets to precache immediately on install
const APP_SHELL = [
  "/index.html",
  "/hasil_MooOS.html",
  "/pakan_MooOS.html",
  "/anggota_MooOS.html",
  "/ternak_MooOS.html",
  "/laporan_MooOS.html",
  "/bundle.js",
  "/style.css",
];

// =====================
// INSTALL — cache app shell
// =====================
self.addEventListener("install", (event) => {
  console.log("[SW] Installing MooOS Service Worker...");
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => {
        console.log("[SW] Precaching app shell");
        return cache.addAll(APP_SHELL).catch((err) => {
          // Don't fail install if some pages aren't built yet
          console.warn("[SW] Some shell assets not cached:", err);
        });
      })
      .then(() => self.skipWaiting())
  );
});

// =====================
// ACTIVATE — clean old caches
// =====================
self.addEventListener("activate", (event) => {
  console.log("[SW] Activating MooOS Service Worker...");
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME && key !== API_CACHE_NAME)
          .map((key) => {
            console.log("[SW] Deleting old cache:", key);
            return caches.delete(key);
          })
      )
    ).then(() => self.clients.claim())
  );
});

// =====================
// FETCH — routing logic
// =====================
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Only handle GET requests
  if (event.request.method !== "GET") return;

  // --- Strategy A: API calls (localhost:8000) → Network-First with cache fallback ---
  if (url.origin === BACKEND_BASE) {
    event.respondWith(
      fetch(event.request.clone())
        .then((networkResponse) => {
          // Save a fresh copy to the API cache
          if (networkResponse.ok) {
            const cloned = networkResponse.clone();
            caches.open(API_CACHE_NAME).then((cache) => {
              cache.put(event.request, cloned);
            });
          }
          return networkResponse;
        })
        .catch(() => {
          // Network failed → serve last cached API response
          return caches.match(event.request).then((cached) => {
            if (cached) {
              console.log("[SW] Offline: serving cached API response for", url.pathname);
              return cached;
            }
            // Return a meaningful offline JSON error
            return new Response(
              JSON.stringify({ error: "offline", message: "Koneksi tidak tersedia. Data dari cache terakhir." }),
              {
                status: 503,
                headers: { "Content-Type": "application/json" },
              }
            );
          });
        })
    );
    return;
  }

  // --- Strategy B: App Shell / static assets → Cache-First with network fallback ---
  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) {
          // Serve from cache immediately
          // Also update cache in the background (stale-while-revalidate)
          fetch(event.request)
            .then((fresh) => {
              caches.open(CACHE_NAME).then((cache) => cache.put(event.request, fresh));
            })
            .catch(() => {}); // Silently fail if offline
          return cached;
        }
        // Not in cache → fetch from network and cache it
        return fetch(event.request).then((response) => {
          if (response.ok) {
            const cloned = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, cloned));
          }
          return response;
        });
      })
    );
    return;
  }
});

// =====================
// SYNC — background sync for offline queued actions
// =====================
self.addEventListener("sync", (event) => {
  if (event.tag === "sync-mooos-data") {
    console.log("[SW] Background sync triggered: sync-mooos-data");
    // Placeholder — future: push queued offline writes to backend
    event.waitUntil(Promise.resolve());
  }
});

// =====================
// MESSAGE — manual cache clear from app
// =====================
self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
  if (event.data && event.data.type === "CLEAR_API_CACHE") {
    caches.delete(API_CACHE_NAME).then(() => {
      console.log("[SW] API cache cleared");
    });
  }
});
