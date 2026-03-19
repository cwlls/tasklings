/**
 * Tasklings -- sw-register.js
 *
 * Registers the service worker and wires up:
 *   - Offline queue replay on reconnect
 *   - Toast notifications when offline completions sync
 *   - HTMX runlist refresh after sync
 */

import { replayQueue, enqueueCompletion } from "./offline-queue.js";

// ---------------------------------------------------------------------------
// Service worker registration
// ---------------------------------------------------------------------------
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/static/sw.js", { scope: "/" })
      .then((reg) => {
        console.debug("SW registered:", reg.scope);

        // Prompt user when an update is waiting.
        reg.addEventListener("updatefound", () => {
          const newWorker = reg.installing;
          newWorker.addEventListener("statechange", () => {
            if (
              newWorker.state === "installed" &&
              navigator.serviceWorker.controller
            ) {
              showToast("App updated. Reload for the latest version.", "info");
            }
          });
        });
      })
      .catch((err) => console.warn("SW registration failed:", err));

    // Listen for messages from the service worker (chore-synced).
    navigator.serviceWorker.addEventListener("message", (event) => {
      if (event.data && event.data.type === "chore-synced") {
        const count = event.data.synced.length;
        showToast(
          `${count} offline chore${count === 1 ? "" : "s"} synced!`,
          "success"
        );
        // Trigger HTMX refresh of the runlist if it's on the page.
        const runlist = document.getElementById("runlist");
        if (runlist && window.htmx) {
          htmx.trigger(runlist, "refresh");
        }
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Online reconnect: replay the offline queue
// ---------------------------------------------------------------------------
window.addEventListener("online", async () => {
  showToast("Back online — syncing...", "info");

  // Request a Background Sync if supported.
  if ("serviceWorker" in navigator && "SyncManager" in window) {
    const reg = await navigator.serviceWorker.ready;
    try {
      await reg.sync.register("chore-completions");
    } catch {
      // Background Sync not available; replay directly.
      await replayDirectly();
    }
  } else {
    await replayDirectly();
  }
});

async function replayDirectly() {
  const { synced } = await replayQueue();
  if (synced.length > 0) {
    const count = synced.length;
    showToast(
      `${count} offline chore${count === 1 ? "" : "s"} synced!`,
      "success"
    );
    const runlist = document.getElementById("runlist");
    if (runlist && window.htmx) {
      htmx.trigger(runlist, "refresh");
    }
  }
}

// ---------------------------------------------------------------------------
// Toast utility (also used by app.js)
// ---------------------------------------------------------------------------
export function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast toast--${type}`;
  toast.textContent = message;
  toast.setAttribute("role", "status");
  container.appendChild(toast);

  // Animate in.
  requestAnimationFrame(() => toast.classList.add("toast--visible"));

  // Auto-remove after 3 s.
  setTimeout(() => {
    toast.classList.remove("toast--visible");
    toast.addEventListener("transitionend", () => toast.remove(), {
      once: true,
    });
  }, 3000);
}

// Export so app.js can import it without duplication.
export { enqueueCompletion };
