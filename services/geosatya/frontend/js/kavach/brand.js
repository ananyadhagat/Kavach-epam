/* KAVACH brand pieces shared by the public site and the app. */

import { session } from "../api.js";
import { clear, h, icon } from "../ui.js";

export const logo = (tagline = "Civic intelligence") => h("a", { class: "kbrand", href: "#/home", "aria-label": "Kavach home" },
  h("img", { src: "icons/kavach-mark.svg", alt: "" }), h("span", { class: "word" }, h("strong", {}, "KAVACH"), h("small", {}, tagline)));

export const PUBLIC_NAV = [
  ["#/home", "Home"], ["#/public-report", "Report an issue"], ["#/track", "Track complaint"],
  ["#/solutions/events", "Event solutions"], ["#/solutions/organizations", "Organization solutions"],
  ["#/stats", "Public dashboard"], ["#/about", "About"],
];

export function renderPublicBar(path) {
  const nav = h("nav", { class: "pubnav", id: "pubnav", "aria-label": "Main" },
    PUBLIC_NAV.map(([href, text]) => h("a", { href, "aria-current": ("#/" + path).startsWith(href) ? "page" : null,
      onclick: () => nav.classList.remove("open") }, text)),
    session.me
      ? h("a", { class: "btn primary small cta", href: "#/" }, "Open my workspace")
      : h("a", { class: "btn primary small cta", href: "#/enter" }, "Sign in / Register"));
  const toggle = h("button", { class: "btn small menu-btn", type: "button", "aria-expanded": "false", "aria-controls": "pubnav",
    onclick: () => { const open = nav.classList.toggle("open"); toggle.setAttribute("aria-expanded", String(open)); } }, icon("menu", 18), "Menu");
  clear(document.getElementById("pubbar"), logo("Civic intelligence · Safer operations"), toggle, nav);
}

export function renderFooter() {
  const col = (title, links) => h("div", {}, h("h4", {}, title), links.map(([href, t]) => h("a", { href }, t)));
  clear(document.getElementById("pubfoot"), h("div", { class: "wrap" },
    h("div", { class: "cols" },
      h("div", { class: "stack" }, logo("Civic intelligence · Safer operations"),
        h("p", { style: { maxWidth: "340px", fontSize: "14px" } }, "One platform for citizens, event organizers and organizations: report, dispatch, track and verify field work.")),
      col("Citizens", [["#/public-report", "Report an issue"], ["#/track", "Track a complaint"], ["#/stats", "Public dashboard"]]),
      col("Solutions", [["#/solutions/events", "Event operations"], ["#/solutions/organizations", "Organizations"], ["#/register/organization", "Register an organization"]]),
      col("Kavach", [["#/about", "About & team"], ["#/enter", "Sign in"], ["#/join", "Join with an invite code"]])),
    h("div", { class: "fine" },
      h("span", {}, "Kavach is an independent platform. An organization shown here is not endorsed by, or affiliated with, any government body unless marked verified."),
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
