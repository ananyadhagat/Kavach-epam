/* Small UI toolkit. All dynamic text goes through textContent; no innerHTML. */

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "value") el.value = value;
    else if (key === "checked") el.checked = !!value;
    else if (key === "style" && typeof value === "object") {
      for (const [k, v] of Object.entries(value)) { if (k.startsWith("--")) el.style.setProperty(k, v); else el.style[k] = v; }
    }
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, String(value));
  }
  return append(el, children);
}

export function append(el, children) {
  for (const child of [children].flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

export function clear(el, ...children) {
  el.replaceChildren();
  return append(el, children);
}

const PATHS = {
  dashboard: "M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 3v6h8V3z",
  plus: "M12 5v14M5 12h14",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  tasks: "M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11",
  upload: "M12 16V4M7 9l5-5 5 5M4 20h16",
  queue: "M4 6h16M4 12h10M4 18h7M17 15l3 3-3 3",
  review: "M9 12l2 2 4-4M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z",
  history: "M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2",
  settings: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
  pin: "M12 21s-7-6.5-7-12a7 7 0 0 1 14 0c0 5.5-7 12-7 12zM12 11.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  crosshair: "M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM12 2v4M12 18v4M2 12h4M18 12h4",
  camera: "M4 8h3l2-3h6l2 3h3v11H4zM12 16.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z",
  image: "M4 5h16v14H4zM4 15l4-4 5 5 3-3 4 4M15 9h.01",
  check: "M5 12l5 5 9-10",
  x: "M6 6l12 12M18 6L6 18",
  warn: "M12 3 2 20h20L12 3zM12 10v4M12 17h.01",
  info: "M12 11v6M12 7.5h.01M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18z",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c1-4 4-6 8-6s7 2 8 6",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  arrowRight: "M5 12h14M13 6l6 6-6 6",
  arrowLeft: "M19 12H5M11 6l-6 6 6 6",
  navigate: "M3 11l18-8-8 18-2-8z",
  road: "M8 3 4 21M16 3l4 18M12 4v3M12 10v3M12 16v4",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6",
  droplet: "M12 3s6 7 6 11a6 6 0 0 1-12 0c0-4 6-11 6-11z",
  drain: "M4 8h16M4 12h16M4 16h16M6 4v16M18 4v16",
  bulb: "M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V17h5v-1.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z",
  bench: "M3 10h18M5 10V7h14v3M4 14h16M6 14v5M18 14v5",
  alert: "M12 3 2 20h20L12 3zM12 10v4M12 17h.01",
  dots: "M5 12h.01M12 12h.01M19 12h.01",
  // KAVACH
  medical: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 8v8M8 12h8",
  users: "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21c.8-3.5 3.5-5.5 7-5.5s6.2 2 7 5.5M16 3.5a4 4 0 0 1 0 7.5M18 15.6c2 .8 3.4 2.6 4 5.4",
  shield: "M12 3l8 3v6c0 5-3.5 8.5-8 9.5-4.5-1-8-4.5-8-9.5V6z",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5",
  building: "M4 21V5l8-3v19M12 9l8 3v9M8 8h.01M8 12h.01M8 16h.01M16 14h.01M16 17h.01M2 21h20",
  calendar: "M4 6h16v15H4zM4 10h16M9 3v5M15 3v5",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  zone: "M12 21s-7-6.5-7-12a7 7 0 0 1 14 0c0 5.5-7 12-7 12zM9 9h6M12 6v6",
  logout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10",
  map: "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2zM9 4v14M15 6v14",
  live: "M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM7.8 16.2a6 6 0 0 1 0-8.4M16.2 7.8a6 6 0 0 1 0 8.4M5 19a10 10 0 0 1 0-14M19 5a10 10 0 0 1 0 14",
  key: "M15 9a4 4 0 1 1-3.5 6L4 22M8 18l2 2M6 20l2 2",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM3 12h18M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.5-3.8-9S9.5 5.5 12 3z",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  menu: "M4 7h16M4 12h16M4 17h16",
  copy: "M8 8h12v12H8zM4 16V4h12",
  route: "M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM8 17h7a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h7",
  toilet: "M8 3h8v6H8zM6 9h12v2.5a6 6 0 0 1-12 0zM9.5 20h5M12 17.5V20",
  broom: "M19.5 3.5 12 11M9.2 9.8l5 5-5.2 6.2H3l1.6-5.8zM8 14.5l4 4",
  recycle: "M3 12a9 9 0 0 1 15-6.7M21 3v6h-6M21 12a9 9 0 0 1-15 6.7M3 21v-6h6",
  highway: "M3 18h18M5 18V9M19 18V9M3 9h18M8 9v9M16 9v9M12 9v9",
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3M8 21h8",
  phone: "M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z",
  bell: "M6 8a6 6 0 0 1 12 0c0 7 3 8 3 8H3s3-1 3-8M10 20a2 2 0 0 0 4 0",
  heart: "M12 21s-8-5.2-8-11a4.5 4.5 0 0 1 8-2.8A4.5 4.5 0 0 1 20 10c0 5.8-8 11-8 11z",
  lock: "M6 11h12v9H6zM8 11V8a4 4 0 0 1 8 0v3",
  star: "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z",
  siren: "M7 19v-6a5 5 0 0 1 10 0v6M4 19h16M12 3v2M4.5 7l1.5 1.2M19.5 7 18 8.2",
  share: "M4 12v7h16v-7M12 3v12M7.5 7.5 12 3l4.5 4.5",
  plus2: "M12 5v14M5 12h14",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
};

export function icon(name, size = 18) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  for (const [k, v] of Object.entries({ width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": "1.9", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" })) svg.setAttribute(k, v);
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", PATHS[name] || PATHS.dots);
  svg.append(path);
  return svg;
}

const TONES = {
  pass: ["PASS", "RESOLVED", "APPROVE"],
  review: ["REVIEW_REQUIRED", "AWAITING_VERIFICATION", "NOT_CHECKED", "REQUEST_EVIDENCE", "SIMULATED"],
  fail: ["FAIL", "REJECT"],
  info: ["ASSIGNED", "IN_PROGRESS", "SUBMITTED"],
};
export function tone(status) {
  for (const [name, list] of Object.entries(TONES)) if (list.includes(status)) return name;
  return "";
}

export const label = (s) => String(s ?? "").replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
export const chip = (status, text) => h("span", { class: `chip ${tone(status)}` }, text || label(status));
export const demoTag = () => h("span", { class: "chip demo", title: "Seeded demonstration record, not real field data" }, "Demo");
export const simTag = () => h("span", { class: "chip demo", title: "Made-up coordinates for testing; never real GPS" }, "Simulated");

export function banner(kind, ...content) {
  return h("div", { class: `banner ${kind}`, role: kind === "fail" ? "alert" : null },
    icon({ pass: "check", info: "info", review: "warn", fail: "warn", demo: "info" }[kind] || "info", 18), h("div", {}, ...content));
}

export const kv = (pairs) => h("dl", { class: "kv" }, pairs.filter(Boolean).flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v ?? "—")]));
export const card = (attrs, ...children) => h("section", Object.assign({ class: "card" }, attrs || {}), ...children);
export const button = (text, attrs = {}, iconName) => h("button", Object.assign({ class: "btn", type: "button" }, attrs), iconName ? icon(iconName, 17) : null, text);

export function spinner(text = "Loading…") {
  return h("div", { class: "state", role: "status" }, h("span", { class: "spinner" }), h("span", {}, text));
}
export function loadingScreen(text = "Loading KAVACH") {
  return h("div", { class: "loading-screen", role: "status", "aria-label": text },
    h("img", { src: "icons/kavach-logo-light.webp", alt: "KAVACH", width: 280, height: 89 }), h("div", { class: "bar", "aria-hidden": "true" }));
}
export function emptyState(title, text, action) {
  return h("div", { class: "state" }, icon("image", 30), h("strong", {}, title), text ? h("p", {}, text) : null, action || null);
}
export function errorState(err, retry) {
  return h("div", { class: "state error", role: "alert" }, icon("warn", 30), h("strong", {}, "Something went wrong"),
    h("p", { class: "muted" }, err?.message || String(err)), retry ? button("Try again", { onclick: retry }, "refresh") : null);
}

export function toast(message, kind = "info") {
  const el = h("div", { class: `toast ${kind}`, role: kind === "fail" ? "alert" : "status" }, message);
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), kind === "fail" ? 7000 : 3800);
}

export function fmtTime(isoString, withSeconds = false) {
  if (!isoString) return "—";
  const d = new Date(isoString);
  return isNaN(d) ? isoString : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: withSeconds ? "medium" : "short" });
}
export function fmtAgo(isoString) {
  const s = (Date.now() - new Date(isoString).getTime()) / 1000;
  if (!(s >= 0)) return "";
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
export const fmtCoord = (lat, lon) => (lat == null || lon == null ? "—" : `${Number(lat).toFixed(6)}, ${Number(lon).toFixed(6)}`);
export const fmtM = (m) => (m == null ? "—" : m < 1000 ? `${Number(m).toFixed(m < 10 ? 1 : 0)} m` : `${(m / 1000).toFixed(2)} km`);

/* Ask for a reason before an action that changes authoritative state. */
export function reasonDialog({ title, description, confirmText, required = true, tone: t = "primary" }) {
  return new Promise((resolve) => {
    const area = h("textarea", { rows: 3, maxlength: 1000, id: "reason-input" });
    const error = h("p", { class: "field-error", "aria-live": "polite" });
    const close = (value) => { dialog.close(); dialog.remove(); resolve(value); };
    const dialog = h("dialog", { class: "dialog" },
      h("form", { class: "stack", onsubmit: (e) => {
        e.preventDefault();
        if (required && area.value.trim().length < 5) { error.textContent = "Please give a reason (at least 5 characters)."; area.focus(); return; }
        close(area.value.trim());
      } },
      h("h2", {}, title), description ? h("p", { class: "muted" }, description) : null,
      h("label", { class: "field", for: "reason-input" }, required ? "Reason (saved in the audit trail)" : "Note (optional)", area), error,
      h("div", { class: "row end" }, button("Cancel", { onclick: () => close(null) }),
        h("button", { class: `btn ${t === "danger" ? "danger" : "primary"}`, type: "submit" }, confirmText))));
    document.body.append(dialog);
    dialog.addEventListener("cancel", () => { dialog.remove(); resolve(null); });
    dialog.showModal();
    area.focus();
  });
}

export function pageHead({ crumbs = [], title, subtitle, right = [] }) {
  return h("header", { class: "page-head" },
    h("div", { class: "stack tight" },
      crumbs.length ? h("nav", { class: "crumbs", "aria-label": "Breadcrumb" }, crumbs.map(([t, href], i) =>
        [i ? " / " : "", href ? h("a", { href }, t) : t])) : null,
      h("h1", {}, title), subtitle ? h("p", { class: "muted" }, subtitle) : null),
    right.length ? h("div", { class: "row wrap" }, ...right) : null);
}
