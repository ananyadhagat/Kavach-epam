/* API client and sign-in. A signed-in user's JWT access token is sent as
   "Authorization: Bearer". The server checks the token, the role and the
   workspace on every request; hiding a button here is only a convenience.
   In AUTH_MODE=demo (development only) a seeded demo identity can be used instead. */

import { enqueue, flush, loadSnapshot, saveSnapshot } from "./outbox.js";

const BASE = (window.GEOSATYA_CONFIG && window.GEOSATYA_CONFIG.apiBase) || "";
export const API = `${BASE}/api/v1`;
export const session = { config: null, categories: [], users: [], me: null, listeners: new Set() };

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* private mode */ } },
};
export const preference = (key, value) => (value === undefined ? store.get(`geosatya.${key}`) : store.set(`geosatya.${key}`, value));

export class ApiError extends Error {
  constructor(message, status, code) { super(message); this.status = status; this.code = code; }
}

const TOKEN_KEY = "kavach.token";
const authHeaders = () => {
  const token = store.get(TOKEN_KEY);
  if (token) return { Authorization: `Bearer ${token}` };
  return session.me && session.config?.auth_mode === "demo" ? { "X-GeoSatya-Demo-User": session.me.user_id } : {};
};
export const hasToken = () => !!store.get(TOKEN_KEY);
/* Development access (AUTH_MODE=demo, refused by the server in production): no login, a role switcher instead.
   The real JWT sign-in stays in place and is used again with AUTH_MODE=jwt. */
export const devAccess = () => session.config?.auth_mode === "demo" && !hasToken();
export const teamDemo = () => !!session.config?.team_demo && devAccess();
export const defaultDevUser = () => session.users.find((u) => u.role === "SUPERVISOR" && !u.platform_role && !u.workspace_id)
  || session.users.find((u) => u.role === "SUPERVISOR") || session.users[0] || null;

async function parse(response) {
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!response.ok) {
    // The token expired or was signed out elsewhere: forget it and ask to sign in again.
    if (response.status === 401 && store.get(TOKEN_KEY)) { store.set(TOKEN_KEY, null); window.dispatchEvent(new Event("kavach-signed-out")); }
    const detail = Array.isArray(data?.detail) ? data.detail.map((d) => d.msg).join("; ") : data?.detail;
    throw new ApiError(detail || `Request failed (${response.status})`, response.status, data?.code);
  }
  return data;
}

/* Whether the last request reached the server. The phone can be "online" (wifi or
   mobile data) while the server is unreachable; the status bar shows the difference. */
export const connectivity = { serverReachable: true };
function reachable(ok) {
  if (connectivity.serverReachable === ok) return;
  connectivity.serverReachable = ok;
  window.dispatchEvent(new Event("geosatya-connectivity"));
}

export async function api(path, { method = "GET", json, form, headers } = {}) {
  const init = { method, headers: { ...authHeaders(), ...(headers || {}) } };
  if (json !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(json); }
  else if (form) init.body = form;
  let response;
  try { response = await fetch(API + path, init); }
  catch { reachable(false); throw new ApiError("Cannot reach the GeoSatya server. Is it running?", 0, "NETWORK"); }
  reachable(true);
  return parse(response);
}

/* multipart upload with a progress callback (fetch has no upload progress) */
export function upload(path, form, onProgress, headers = {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", API + path);
    for (const [k, v] of Object.entries({ ...authHeaders(), ...headers })) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onerror = () => { reachable(false); reject(new ApiError("Upload failed: cannot reach the server.", 0, "NETWORK")); };
    xhr.onload = () => { reachable(true); parse(new Response(xhr.responseText, { status: xhr.status })).then(resolve, reject); };
    xhr.send(form);
  });
}

const imageCache = new Map();
export async function protectedImage(url) {
  const key = `${session.me?.user_id}|${url}`;
  if (imageCache.has(key)) return imageCache.get(key);
  const response = await fetch(BASE + url, { headers: authHeaders() });
  if (!response.ok) throw new ApiError("Photo unavailable", response.status);
  const objectUrl = URL.createObjectURL(await response.blob());
  imageCache.set(key, objectUrl);
  return objectUrl;
}

/* ------------------------------------------------ offline (worker app) */
export const isNetworkError = (err) => err instanceof ApiError && err.status === 0;

/* GET that falls back to the last copy saved on this device when offline.
   The result carries `offlineSince` when it came from the device. */
export async function cachedGet(path) {
  const user = session.me?.user_id;
  try {
    const data = await api(path);
    if (user) saveSnapshot(user, path, data).catch(() => {});
    return data;
  } catch (err) {
    if (!isNetworkError(err) || !user) throw err;
    const snap = await loadSnapshot(user, path).catch(() => null);
    if (!snap) throw new ApiError("You're offline and this page hasn't been opened on this device before.", 0, "NETWORK");
    return Object.assign(snap.data, { offlineSince: snap.saved_at });
  }
}

/* Send now, or keep it on the device and send it when the connection returns.
   Returns the server response, or {queued: true}. Only network failures queue;
   a refusal from the server (4xx) is shown to the worker straight away. */
export async function sendOrQueue(path, { method = "POST", json, form, idempotencyKey, kind, label, taskId, replaceKey } = {}) {
  const headers = idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {};
  try {
    if (navigator.onLine === false) throw new ApiError("offline", 0, "NETWORK");
    if (form) {
      const fd = new FormData();
      fd.append("payload", form.payload);
      if (form.blob) fd.append("photo", form.blob, form.filename || "photo.jpg");
      return await upload(path, fd, null, headers);
    }
    return await api(path, { method, json, headers });
  } catch (err) {
    if (!isNetworkError(err)) throw err;
    await enqueue({ user: session.me.user_id, kind, label, method, path, json, form, idempotencyKey, taskId, replaceKey });
    return { queued: true };
  }
}

/* Send everything queued for the current user; returns how many were sent. */
export function flushOutbox() {
  if (!session.me) return Promise.resolve(0);
  return flush(session.me.user_id, async (item) => {
    try {
      const data = item.form
        ? await (async () => { const fd = new FormData(); fd.append("payload", item.form.payload);
          if (item.form.blob) fd.append("photo", item.form.blob, item.form.filename || "photo.jpg");
          return upload(item.path, fd, null, item.idempotencyKey ? { "Idempotency-Key": item.idempotencyKey } : {}); })()
        : await api(item.path, { method: item.method, json: item.json, headers: item.idempotencyKey ? { "Idempotency-Key": item.idempotencyKey } : {} });
      return { ok: true, status: 200, data };
    } catch (err) {
      return { ok: false, status: err.status ?? 0, message: err.message };
    }
  });
}

export async function bootstrap() {
  // The app shell must start offline too: reuse the last config if the server can't be reached.
  let config, cats;
  try {
    [config, cats] = await Promise.all([api("/config"), api("/categories")]);
    store.set("geosatya.boot", JSON.stringify({ config, cats }));
  } catch (err) {
    const saved = isNetworkError(err) ? JSON.parse(store.get("geosatya.boot") || "null") : null;
    if (!saved) throw err;
    ({ config, cats } = saved);
    session.offlineStart = true;
  }
  session.config = config;
  session.categories = cats.categories;
  session.authOptions = await api("/auth/options").catch(() => ({ citizen_signup: true }));
  session.users = [];
  session.me = null;
  if (store.get(TOKEN_KEY)) {
    try {
      session.me = await api("/auth/me");
      store.set("kavach.me", JSON.stringify(session.me));
    } catch (err) {
      // Offline: keep the last known user so the worker app still opens; the server decides when back online.
      if (isNetworkError(err)) session.me = JSON.parse(store.get("kavach.me") || "null");
    }
  }
  if (!session.me && config.auth_mode === "demo") {
    try {
      session.users = await api("/demo/users");
      store.set("geosatya.users", JSON.stringify(session.users));
    } catch (err) {
      if (!isNetworkError(err)) throw err;
      session.users = JSON.parse(store.get("geosatya.users") || "[]");
    }
    const saved = store.get("geosatya.demoUser");
    // Development access: no login screen. Reopen the last identity, else start as the civic supervisor.
    // Team live demo: everyone signs in as themselves, so nobody is picked automatically.
    session.me = session.users.find((u) => u.user_id === saved) || (config.team_demo ? null : defaultDevUser());
    if (session.me) store.set("geosatya.demoUser", session.me.user_id);
  }
  await loadContext();
}

/* After a successful sign-in or registration (the server's answer carries the token). */
export async function signedIn(result) {
  store.set("geosatya.demoUser", null);
  store.set(TOKEN_KEY, result.access_token);
  store.set("kavach.me", JSON.stringify(result.user));
  session.me = result.user;
  await loadContext();
  session.listeners.forEach((fn) => fn(session.me));
}

/* The signed-in user's workspace (organization or open event), or null. */
export async function loadContext() {
  session.ctx = null;
  if (!session.me) return;
  try {
    session.ctx = await api("/kavach/me");
    store.set(`kavach.ctx.${session.me.user_id}`, JSON.stringify(session.ctx));
  } catch (err) {
    if (!isNetworkError(err)) { if (err.status === 401 || err.status === 403) signOut(false); return; }
    session.ctx = JSON.parse(store.get(`kavach.ctx.${session.me.user_id}`) || "null");
  }
}

/* Reload the demo identities (after a registration or an invite created a new one). */
export async function refreshUsers() {
  if (session.config?.auth_mode !== "demo") return;
  session.users = await api("/demo/users");
  store.set("geosatya.users", JSON.stringify(session.users));
}

export async function switchUser(userId) {
  let user = session.users.find((u) => u.user_id === userId);
  if (!user) { await refreshUsers().catch(() => {}); user = session.users.find((u) => u.user_id === userId); }
  if (!user) return;
  session.me = user;
  store.set("geosatya.demoUser", userId);
  await loadContext();
  session.listeners.forEach((fn) => fn(user));
}

export function signOut(notify = true) {
  if (store.get(TOKEN_KEY)) api("/auth/logout", { method: "POST" }).catch(() => {}).finally(() => store.set(TOKEN_KEY, null));
  session.me = null;
  session.ctx = null;
  store.set("geosatya.demoUser", null);
  store.set("kavach.me", null);
  if (notify) session.listeners.forEach((fn) => fn(null));
}
export const firstUser = (role) => session.users.find((u) => u.role === role);
export const category = (id) => session.categories.find((c) => c.id === id) || null;
