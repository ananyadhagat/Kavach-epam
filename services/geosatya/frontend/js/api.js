/* API client and demo identity. In demo mode there is no sign-in: the chosen
   demo identity is sent in a header and the server still enforces roles. */

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

const authHeaders = () => (session.me ? { "X-GeoSatya-Demo-User": session.me.user_id } : {});

async function parse(response) {
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!response.ok) {
    const detail = Array.isArray(data?.detail) ? data.detail.map((d) => d.msg).join("; ") : data?.detail;
    throw new ApiError(detail || `Request failed (${response.status})`, response.status, data?.code);
  }
  return data;
}

export async function api(path, { method = "GET", json, form } = {}) {
  const init = { method, headers: authHeaders() };
  if (json !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(json); }
  else if (form) init.body = form;
  let response;
  try { response = await fetch(API + path, init); }
  catch { throw new ApiError("Cannot reach the GeoSatya server. Is it running?", 0, "NETWORK"); }
  return parse(response);
}

/* multipart upload with a progress callback (fetch has no upload progress) */
export function upload(path, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", API + path);
    for (const [k, v] of Object.entries(authHeaders())) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onerror = () => reject(new ApiError("Upload failed: cannot reach the server.", 0, "NETWORK"));
    xhr.onload = () => parse(new Response(xhr.responseText, { status: xhr.status })).then(resolve, reject);
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

export async function bootstrap() {
  const [config, cats] = await Promise.all([api("/config"), api("/categories")]);
  session.config = config;
  session.categories = cats.categories;
  if (config.auth_mode === "demo") {
    session.users = await api("/demo/users");
    const saved = store.get("geosatya.demoUser");
    session.me = session.users.find((u) => u.user_id === saved) || session.users.find((u) => u.role === "CITIZEN") || session.users[0] || null;
  } else {
    session.me = await api("/me");
  }
}

export function switchUser(userId) {
  const user = session.users.find((u) => u.user_id === userId);
  if (!user) return;
  session.me = user;
  store.set("geosatya.demoUser", userId);
  session.listeners.forEach((fn) => fn(user));
}
export const firstUser = (role) => session.users.find((u) => u.role === role);
export const category = (id) => session.categories.find((c) => c.id === id) || null;
