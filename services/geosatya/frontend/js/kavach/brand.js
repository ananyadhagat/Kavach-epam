/* KAVACH brand pieces shared by the public site and the app. */

import { devAccess, session, teamDemo } from "../api.js";
import { clear, h, icon } from "../ui.js";

export const logo = () => h("a", { class: "kbrand", href: "#/home", "aria-label": "KAVACH home" },
  h("img", { class: "brandlogo full", src: "icons/kavach-logo-light.webp", alt: "KAVACH: Civic, Safety, Operations", width: 140, height: 45 }),
  h("img", { class: "brandlogo mark", src: "icons/kavach-mark-light.png", alt: "", width: 34, height: 38 }));

export const PUBLIC_NAV = [
  ["#/home", "Home"], ["#/public-report", "Report an issue"], ["#/track", "Track complaint"], ["#/women", "Women's safety"],
  ["#/solutions/events", "Events"], ["#/solutions/organizations", "Organizations"], ["#/team", "Team"], ["#/about", "About"],
];

/* The "+" entry: three ways into KAVACH, each with an icon, a line and one action. */
export const JOIN_OPTIONS = [
  ["user", "Citizen", "Report problems with a photo and track them.", "#/signup/citizen", "Register as a Citizen"],
  ["tasks", "Field worker", "Needs the worker access code from your department.", "#/signup/worker", "Register as a Field Worker"],
  ["review", "Supervisor", "Account from your administrator + supervisor access code.", "#/signin/supervisor", "Sign in as a Supervisor"],
];

function joinMenu() {
  const panel = h("div", { class: "join-pop", id: "join-pop", role: "dialog", "aria-label": "Join KAVACH", hidden: true },
    JOIN_OPTIONS.map(([ic, title, text, href, action]) => h("div", { class: "join-opt" }, h("span", { class: "join-ico small" }, icon(ic, 20)),
      h("div", { class: "stack tight grow" }, h("strong", {}, title), h("span", { class: "muted" }, text),
        h("a", { class: "btn primary small", href, onclick: () => close() }, action)))),
    h("a", { class: "join-signin", href: "#/signin", onclick: () => close() }, "Already registered? Sign in"));
  const plus = h("button", { class: "plus-btn", type: "button", "aria-label": "Join or sign in", "aria-expanded": "false", "aria-controls": "join-pop",
    onclick: (e) => { e.stopPropagation(); panel.hidden ? openIt() : close(); } }, icon("plus", 22));
  const onDoc = (e) => { if (!panel.contains(e.target) && e.target !== plus) close(); };
  const onKey = (e) => { if (e.key === "Escape") { close(); plus.focus(); } };
  function openIt() { panel.hidden = false; plus.setAttribute("aria-expanded", "true"); document.addEventListener("click", onDoc); document.addEventListener("keydown", onKey); panel.querySelector("a")?.focus(); }
  function close() { panel.hidden = true; plus.setAttribute("aria-expanded", "false"); document.removeEventListener("click", onDoc); document.removeEventListener("keydown", onKey); }
  return h("div", { class: "join-wrap" }, plus, panel);
}

export function renderPublicBar(path) {
  const nav = h("nav", { class: "pubnav", id: "pubnav", "aria-label": "Main" },
    PUBLIC_NAV.map(([href, text]) => h("a", { href, "aria-current": ("#/" + path).startsWith(href) ? "page" : null,
      onclick: () => nav.classList.remove("open") }, text)),
    session.me ? h("a", { class: "btn primary small cta", href: "#/" }, devAccess() ? "Open dashboard" : "Open my workspace")
      : h("a", { class: "btn small cta", href: "#/signin" }, "Sign in"));
  const toggle = h("button", { class: "btn small menu-btn", type: "button", "aria-expanded": "false", "aria-controls": "pubnav",
    onclick: () => { const open = nav.classList.toggle("open"); toggle.setAttribute("aria-expanded", String(open)); } }, icon("menu", 18), "Menu");
  clear(document.getElementById("pubbar"), logo(), toggle, nav, session.me || teamDemo() ? null : joinMenu());
}

export function renderFooter() {
  const col = (title, links) => h("div", {}, h("h4", {}, title), links.map(([href, t]) => h("a", { href }, t)));
  clear(document.getElementById("pubfoot"), h("div", { class: "wrap" },
    h("div", { class: "cols" },
      h("div", { class: "stack" }, logo(),
        h("p", { style: { maxWidth: "340px", fontSize: "14px" } }, "Civic complaints, event operations and women's safety on one platform, with every job checked on the ground."),
        h("div", { class: "contact" }, h("span", {}, "Contact: hello@kavach.example"), h("span", {}, "(placeholder address: set your team's real contact before launch)"))),
      col("Citizens", [["#/public-report", "Report an issue"], ["#/track", "Track a complaint"], ["#/stats", "Public dashboard"], ["#/women", "Women's safety"]]),
      col("Solutions", [["#/solutions/events", "Event operations"], ["#/solutions/organizations", "Organizations"], ["#/register/organization", "Register an organization"], ["#/register/organizer", "Event organizer account"]]),
      col("KAVACH", [["#/about", "About and team"], ["#/signin", "Sign in"], ["#/start", "Register"]])),
    h("div", { class: "fine" },
      h("span", {}, "KAVACH does not replace the police, ambulance or emergency services. In danger, call 112. KAVACH is an independent platform; it is not endorsed by any government body."),
      h("span", {}, "Maps © OpenStreetMap contributors"))));
}

/* Fade sections in as they scroll into view. */
export function reveal(root) {
  const items = root.querySelectorAll(".reveal");
  if (!("IntersectionObserver" in window) || matchMedia("(prefers-reduced-motion: reduce)").matches) { items.forEach((el) => el.classList.add("in")); return () => {}; }
  const io = new IntersectionObserver((entries) => entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: 0.12 });
  items.forEach((el) => io.observe(el));
  return () => io.disconnect();
}

/* Count a number up from zero once it is visible. */
export function countUp(el, value, { suffix = "", decimals = 0 } = {}) {
  if (value == null) { el.textContent = "—"; return; }
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const finish = () => { el.textContent = Number(value).toFixed(decimals) + suffix; };
  if (reduce || !("IntersectionObserver" in window)) return finish();
  el.textContent = (0).toFixed(decimals) + suffix;
  const io = new IntersectionObserver(([e]) => {
    if (!e.isIntersecting) return;
    io.disconnect();
    const start = performance.now(), dur = 1100;
    const step = (now) => {
      const t = Math.min(1, (now - start) / dur), eased = 1 - Math.pow(1 - t, 3);
      el.textContent = (value * eased).toFixed(decimals) + suffix;
      if (t < 1) requestAnimationFrame(step); else finish();
    };
    requestAnimationFrame(step);
  });
  io.observe(el);
}

export const initials = (name) => String(name || "?").replace(/\(.*\)/, "").trim().split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();
export const hours = (hrs) => (hrs == null ? "—" : hrs < 1 ? `${Math.round(hrs * 60)} min` : hrs < 48 ? `${+hrs.toFixed(1)} hrs` : `${Math.round(hrs / 24)} days`);

/* Where each experience starts after signing in. */
export const ROLE_INFO = {
  CITIZEN: { label: "Citizen", color: "linear-gradient(135deg,#F7C36A,#F08A24)", icon: "user" },
  WORKER: { label: "Field worker", color: "linear-gradient(135deg,#7FD1BE,#1F8C80)", icon: "tasks" },
  SUPERVISOR: { label: "Supervisor", color: "linear-gradient(135deg,#5FA8E8,#1D5BC2)", icon: "review" },
  ORG_ADMIN: { label: "Organization admin", color: "linear-gradient(135deg,#1B5C56,#0B2F2C)", icon: "building" },
  EVENT_ORGANIZER: { label: "Event organizer", color: "linear-gradient(135deg,#B48BF0,#6D28D9)", icon: "calendar" },
  PLATFORM_ADMIN: { label: "Platform admin", color: "linear-gradient(135deg,#F28B82,#B42318)", icon: "shield" },
};
export const roleKey = (u) => u?.platform_role || u?.role;
