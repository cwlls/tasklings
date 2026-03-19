/**
 * Tasklings -- sw-register.js
 * Registers the service worker for PWA offline support.
 * Expanded in Phase 10 (offline / PWA).
 */

if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
        navigator.serviceWorker
            .register("/static/sw.js")
            .then((reg) => console.debug("SW registered:", reg.scope))
            .catch((err) => console.warn("SW registration failed:", err));
    });
}
