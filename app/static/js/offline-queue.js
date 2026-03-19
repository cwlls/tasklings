/**
 * Tasklings -- offline-queue.js
 *
 * Client-side IndexedDB queue for offline chore completions.
 * Used by sw-register.js to enqueue when offline and replay on reconnect.
 */

const DB_NAME = "tasklings-offline-queue";
const STORE_NAME = "completions";
const DB_VERSION = 1;

function openDB() {
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

/**
 * Enqueue a chore completion for offline replay.
 * @param {string} assignmentId
 */
export async function enqueueCompletion(assignmentId) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).add({
      assignmentId,
      url: `/api/v1/my/assignments/${assignmentId}/complete`,
      queuedAt: Date.now(),
    });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

/**
 * Return all queued completions.
 * @returns {Promise<Array>}
 */
export async function getQueuedCompletions() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function removeItem(id) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

/**
 * Attempt to replay all queued completions.
 * Successful or terminal (404/409) items are removed from the queue.
 * Returns { synced: string[], failed: string[] }.
 */
export async function replayQueue() {
  const items = await getQueuedCompletions();
  const synced = [];
  const failed = [];

  for (const item of items) {
    try {
      const resp = await fetch(item.url, { method: "POST" });
      if (resp.ok || resp.status === 404 || resp.status === 409) {
        await removeItem(item.id);
        synced.push(item.assignmentId);
      } else {
        failed.push(item.assignmentId);
      }
    } catch {
      failed.push(item.assignmentId);
    }
  }

  return { synced, failed };
}
