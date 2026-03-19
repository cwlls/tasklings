/**
 * Tasklings -- sw.js
 * Service Worker for PWA offline support.
 * Expanded in Phase 10 (offline / PWA).
 */

const CACHE_NAME = "tasklings-v1";

self.addEventListener("install", (event) => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(self.clients.claim());
});

// Fetch handler -- pass-through for now; cache strategies added in Phase 10.
self.addEventListener("fetch", (event) => {
    // Pass through all requests during Phase 1-9.
});
