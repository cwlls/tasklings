/**
 * Tasklings -- app.js
 * Main application module.
 *
 * Responsibilities:
 *   - Lumin counter animation when balance changes after HTMX swap
 *   - HTMX lifecycle hooks (purchase toast, error toast)
 *   - Toast system
 *   - Bottom-nav active-state marking
 */

import { showToast } from "./sw-register.js";

// Re-export so other modules can use without importing sw-register directly.
export { showToast };

// ---------------------------------------------------------------------------
// Lumin counter animation
// ---------------------------------------------------------------------------

/**
 * Animate a numeric counter element from its current displayed value to `target`.
 * @param {HTMLElement} el
 * @param {number} target
 */
function animateCounter(el, target) {
  const start = parseInt(el.textContent.replace(/\D/g, ""), 10) || 0;
  if (start === target) return;

  const duration = 500; // ms
  const startTime = performance.now();

  function step(now) {
    const elapsed = now - startTime;
    const progress = Math.min(elapsed / duration, 1);
    // Ease-out cubic
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = Math.round(start + (target - start) * eased);
    if (progress < 1) {
      requestAnimationFrame(step);
    } else {
      el.textContent = target;
    }
  }

  el.classList.add("lumin-pop");
  el.addEventListener(
    "animationend",
    () => el.classList.remove("lumin-pop"),
    { once: true }
  );

  requestAnimationFrame(step);
}

/**
 * Refresh all elements with [data-lumin-balance] after an HTMX swap
 * that includes a data-new-balance attribute on the swapped fragment root.
 */
function refreshLuminCounters(fragment) {
  const newBalance = fragment
    ? parseInt(fragment.dataset.newBalance, 10)
    : NaN;

  if (!isNaN(newBalance)) {
    document.querySelectorAll("[data-lumin-balance]").forEach((el) => {
      animateCounter(el, newBalance);
    });
  }
}

// ---------------------------------------------------------------------------
// HTMX event hooks
// ---------------------------------------------------------------------------

document.addEventListener("htmx:afterSwap", (event) => {
  const target = event.detail.target;

  // Animate any newly appeared chore item into completed state.
  if (target && target.classList.contains("chore-item--completed")) {
    target.classList.add("check-complete");
    target.addEventListener(
      "animationend",
      () => target.classList.remove("check-complete"),
      { once: true }
    );

    // Spawn lumin burst popup if the item has a lumin value.
    const luminValue = target.dataset.luminValue;
    if (luminValue && parseInt(luminValue, 10) > 0) {
      const popup = document.createElement("div");
      popup.className = "lumin-earned-popup";
      popup.textContent = `+${luminValue} ✨`;
      target.appendChild(popup);
      popup.addEventListener("animationend", () => popup.remove(), { once: true });
    }
  }

  // Balance counter refresh via data attribute on swapped content.
  refreshLuminCounters(event.detail.elt);
});

document.addEventListener("htmx:afterRequest", (event) => {
  const xhr = event.detail.xhr;
  if (!xhr) return;

  // Purchase success toast (store buy endpoint).
  const requestPath = event.detail.pathInfo?.requestPath || "";
  if (requestPath.includes("/buy") && xhr.status === 200) {
    // The item card itself shows the result; no toast needed.
    return;
  }

  // Generic success for sync endpoint.
  if (requestPath.includes("/sync/completions") && xhr.status === 200) {
    try {
      const data = JSON.parse(xhr.responseText);
      if (data.accepted && data.accepted.length > 0) {
        showToast(
          `${data.accepted.length} chore${data.accepted.length === 1 ? "" : "s"} synced`,
          "success"
        );
      }
    } catch {}
  }
});

document.addEventListener("htmx:responseError", (event) => {
  const status = event.detail.xhr?.status;
  if (status === 409) {
    showToast("Action already completed.", "warning");
  } else if (status === 403) {
    showToast("You don't have permission for that.", "danger");
  } else if (status >= 500) {
    showToast("Server error — please try again.", "danger");
  }
});

// ---------------------------------------------------------------------------
// Bottom nav active state
// ---------------------------------------------------------------------------

(function markActiveNavItem() {
  const path = window.location.pathname;
  document.querySelectorAll(".nav-item").forEach((link) => {
    const href = link.getAttribute("href") || "";
    // Mark active if the current path starts with the nav link href
    // (but don't mark "/" active everywhere).
    if (href && href !== "/" && path.startsWith(href)) {
      link.setAttribute("aria-current", "page");
      link.classList.add("active");
    }
  });
})();

// ---------------------------------------------------------------------------
// Offline indicator
// ---------------------------------------------------------------------------

(function setupOfflineIndicator() {
  function updateStatus() {
    const offline = !navigator.onLine;
    document.documentElement.classList.toggle("offline", offline);
    if (offline) {
      showToast("You're offline — completions will sync later.", "warning");
    }
  }

  window.addEventListener("offline", updateStatus);
  // 'online' is handled in sw-register.js to also trigger queue replay.
})();
