/* Offline support for the worker app, kept in this browser's IndexedDB.

   outbox:    actions taken without a connection (accept, arrive, start work,
              location, progress note, completion photo). They are sent in order
              when the connection returns. Completions and progress notes carry an
              Idempotency-Key, so a re-send never files them twice; location
              updates keep their original device time, and only the newest unsent
              one per task is kept (an old position is useless for live tracking).
   snapshots: the last loaded copy of a worker's own task list and task pages,
              so they still open offline. Stored per user.

   Nothing here decides anything: the server still checks every action when it
   arrives (a late arrival or a completion from the wrong place is refused or
   flagged exactly as if it had been sent live). */

const DB = "geosatya-offline", VERSION = 1;
let dbPromise = null;
const listeners = new Set();

function db() {
  dbPromise ||= new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, VERSION);
    req.onupgradeneeded = () => {
      const d = req.result;
      if (!d.objectStoreNames.contains("outbox")) d.createObjectStore("outbox", { keyPath: "id" });
      if (!d.objectStoreNames.contains("snapshots")) d.createObjectStore("snapshots", { keyPath: "key" });
      if (!d.objectStoreNames.contains("results")) d.createObjectStore("results", { keyPath: "id" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

async function tx(store, mode, fn) {
  const d = await db();
  return new Promise((resolve, reject) => {
    const t = d.transaction(store, mode);
    const s = t.objectStore(store);
    let out;
    Promise.resolve(fn(s)).then((v) => { out = v; });
    t.oncomplete = () => resolve(out);
    t.onerror = () => reject(t.error);
  });
}
const all = (store) => tx(store, "readonly", (s) => new Promise((r) => { const q = s.getAll(); q.onsuccess = () => r(q.result); }));
const notify = () => listeners.forEach((fn) => { try { fn(); } catch { /* ignore */ } });

export const onChange = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
export const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

/* item: {user, kind, label, method, path, json?, form?: {payload, blob, filename}, idempotencyKey?, replaceKey?} */
export async function enqueue(item) {
  const entry = { ...item, id: `${Date.now()}-${newKey()}`, created_at: new Date().toISOString() };
  const stale = item.replaceKey ? (await all("outbox")).filter((x) => x.replaceKey === item.replaceKey && x.user === item.user) : [];
  await tx("outbox", "readwrite", (s) => { stale.forEach((x) => s.delete(x.id)); s.put(entry); });
  notify();
  return entry;
}

export async function pending(user) {
  return (await all("outbox")).filter((x) => x.user === user).sort((a, b) => a.id.localeCompare(b.id));
}

export async function results(user) {
  return (await all("results")).filter((x) => x.user === user).sort((a, b) => b.id.localeCompare(a.id));
}
export const clearResult = async (id) => { await tx("results", "readwrite", (s) => s.delete(id)); notify(); };

let flushing = null;
/* Send queued actions in order. `send(item)` performs the request and returns
   {ok, status, data, message}; status 0 means "still offline": stop and retry later. */
export function flush(user, send) {
  flushing ||= (async () => {
    let sent = 0;
    try {
      for (const item of await pending(user)) {
        const r = await send(item);
        if (r.status === 0 || r.status >= 500 || r.status === 429) break;     // offline or server trouble: keep it
        await tx("outbox", "readwrite", (s) => s.delete(item.id));
        await tx("results", "readwrite", (s) => s.put({ id: item.id, user, kind: item.kind, label: item.label, taskId: item.taskId,
          ok: r.ok, status: r.status, message: r.message, data: r.data, sent_at: new Date().toISOString() }));
        sent++;
      }
    } finally { flushing = null; notify(); }
    return sent;
  })();
  return flushing;
}

/* ------------------------------------------------------------ snapshots */
export async function saveSnapshot(user, path, data) {
  await tx("snapshots", "readwrite", (s) => s.put({ key: `${user}|${path}`, data, saved_at: new Date().toISOString() }));
}
export async function loadSnapshot(user, path) {
  return tx("snapshots", "readonly", (s) => new Promise((r) => { const q = s.get(`${user}|${path}`); q.onsuccess = () => r(q.result || null); }));
}
