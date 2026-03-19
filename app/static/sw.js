/**
 * Tasklings -- sw.js
 * Service Worker with:
 *   - Cache-first for static assets (/static/css/, /static/js/, /static/icons/)
 *   - Network-first for API calls (/api/v1/)
 *   - Stale-while-revalidate for HTML pages
 *   - Offline chore-completion queue via IndexedDB
 */

const CACHE_NAME = "tasklings-v1";

const APP_SHELL = [
  "/runlist",
  "/login",
  "/quests",
  "/group-quests",
  "/store",
  "/purchases",
  "/profile",
  "/static/css/main.css",
  "/static/js/app.js",
  "/static/js/sw-register.js",
  "/static/manifest.json",
];

// ---------------------------------------------------------------------------
// Install -- pre-cache app shell
// ---------------------------------------------------------------------------
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

// ---------------------------------------------------------------------------
// Activate -- purge old caches
// ---------------------------------------------------------------------------
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function isStaticAsset(url) {
  return (
    url.pathname.startsWith("/static/css/") ||
    url.pathname.startsWith("/static/js/") ||
    url.pathname.startsWith("/static/icons/") ||
    url.pathname.startsWith("/static/img/")
  );
}

function isApiRequest(url) {
  return url.pathname.startsWith("/api/v1/");
}

function isCompletionPost(request, url) {
  return (
    request.method === "POST" &&
    /^\/api\/v1\/my\/assignments\/[^/]+\/complete$/.test(url.pathname)
  );
}

// Cache-first: serve from cache, fetch in background to update.
async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) {
    // Refresh in background.
    fetch(request)
      .then((resp) => {
        if (resp && resp.ok) {
          caches.open(CACHE_NAME).then((c) => c.put(request, resp));
        }
      })
      .catch(() => {});
    return cached;
  }
  const resp = await fetch(request);
  if (resp && resp.ok) {
    const cache = await caches.open(CACHE_NAME);
    cache.put(request, resp.clone());
  }
  return resp;
}

// Network-first: try network, fall back to cache.
async function networkFirst(request) {
  try {
    const resp = await fetch(request);
    if (resp && resp.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, resp.clone());
    }
    return resp;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw new Error("Offline and no cache available");
  }
}

// Stale-while-revalidate: serve cache immediately, then update from network.
async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);

  const networkFetch = fetch(request)
    .then((resp) => {
      if (resp && resp.ok) cache.put(request, resp.clone());
      return resp;
    })
    .catch(() => null);

  return cached || networkFetch;
}

// ---------------------------------------------------------------------------
// IndexedDB offline queue helpers (self-contained in SW context)
// ---------------------------------------------------------------------------
const DB_NAME = "tasklings-offline-queue";
const STORE_NAME = "completions";
const DB_VERSION = 1;

function openQueueDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, {
          keyPath: "id",
          autoIncrement: true,
        });
      }
    };
    req.onsuccess = (e) => resolve(e.target.result);
    req.onerror = () => reject(req.error);
  });
}

async function enqueueInSW(assignmentId, url) {
  const db = await openQueueDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).add({
      assignmentId,
      url,
      queuedAt: Date.now(),
    });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function getQueuedItems() {
  const db = await openQueueDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function removeFromQueue(id) {
  const db = await openQueueDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function replayQueue() {
  const items = await getQueuedItems();
  const results = { synced: [], dropped: [] };

  for (const item of items) {
    try {
      const resp = await fetch(item.url, { method: "POST" });
      // 200/201 = success; 404/409 = server-side terminal state -- drop both.
      if (resp.ok || resp.status === 404 || resp.status === 409) {
        await removeFromQueue(item.id);
        results.synced.push(item.assignmentId);
      }
      // Other errors (5xx, network) leave the item in the queue for next sync.
    } catch {
      // Still offline -- leave in queue.
    }
  }

  // Notify all open clients so the UI can refresh.
  if (results.synced.length > 0) {
    const clients = await self.clients.matchAll({ type: "window" });
    for (const client of clients) {
      client.postMessage({ type: "chore-synced", synced: results.synced });
    }
  }

  return results;
}

// ---------------------------------------------------------------------------
// Fetch event -- apply routing strategy
// ---------------------------------------------------------------------------
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Only handle same-origin requests.
  if (url.origin !== self.location.origin) return;

  // Static assets: cache-first.
  if (isStaticAsset(url)) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  // API requests.
  if (isApiRequest(url)) {
    if (isCompletionPost(event.request, url)) {
      // Chore completion: network-first; queue on failure.
      event.respondWith(
        fetch(event.request.clone()).catch(async () => {
          const assignmentId = url.pathname.split("/")[5];
          await enqueueInSW(assignmentId, event.request.url);
          // Return a synthetic "queued" response so HTMX doesn't crash.
          return new Response(
            JSON.stringify({ queued: true, assignment_id: assignmentId }),
            {
              status: 202,
              headers: { "Content-Type": "application/json" },
            }
          );
        })
      );
      return;
    }

    // Other API calls: network-first.
    if (event.request.method === "GET") {
      event.respondWith(networkFirst(event.request));
      return;
    }
    // Mutating API calls other than chore completion: network-only.
    return;
  }

  // HTML pages: stale-while-revalidate.
  if (event.request.method === "GET") {
    event.respondWith(staleWhileRevalidate(event.request));
  }
});

// ---------------------------------------------------------------------------
// Background Sync event
// ---------------------------------------------------------------------------
self.addEventListener("sync", (event) => {
  if (event.tag === "chore-completions") {
    event.waitUntil(replayQueue());
  }
});
