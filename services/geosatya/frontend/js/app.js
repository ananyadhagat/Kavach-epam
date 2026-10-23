/* GeoSatya shell: role-aware navigation, demo role switcher, router. */

import { bootstrap, firstUser, preference, session, switchUser } from "./api.js";
import { button, clear, errorState, h, icon, spinner } from "./ui.js";
import { renderDashboard } from "./pages/dashboard.js";
import { renderReport } from "./pages/report.js";
import { renderIncident, renderMyReports } from "./pages/incident.js";
import { renderEvidenceShortcut, renderTask, renderTasks } from "./pages/tasks.js";
import { renderNextReview, renderQueue, renderReview } from "./pages/review.js";
import { renderHistory } from "./pages/history.js";
import { renderSettings } from "./pages/settings.js";

const ROLE_TEXT = { CITIZEN: "citizen", WORKER: "field worker", SUPERVISOR: "supervisor" };
const NAV = [
  ["#/", "Dashboard", "dashboard", null],
  ["#/report", "Report an Incident", "plus", ["CITIZEN"]],
  ["#/reports", "My Reports", "list", ["CITIZEN"]],
  ["#/tasks", "Worker Tasks", "tasks", ["WORKER"]],
  ["#/evidence", "Submit Completion Evidence", "upload", ["WORKER"]],
  ["#/queue", "Verification Queue", "queue", ["SUPERVISOR"]],
  ["#/review", "Supervisor Review", "review", ["SUPERVISOR"]],
  ["#/history", "Evidence History", "history", ["SUPERVISOR"]],
  ["#/settings", "Settings", "settings", ["SUPERVISOR"]],
];
const ROUTES = [
  [/^$/, renderDashboard],
  [/^report$/, renderReport, ["CITIZEN"]],
  [/^reports$/, renderMyReports, ["CITIZEN"]],
  [/^incidents\/(.+)$/, renderIncident],
  [/^tasks$/, renderTasks, ["WORKER", "SUPERVISOR"]],
  [/^evidence$/, renderEvidenceShortcut, ["WORKER"]],
  [/^tasks\/(.+)$/, renderTask, ["WORKER", "SUPERVISOR"]],
  [/^queue$/, renderQueue, ["SUPERVISOR"]],
  [/^review$/, renderNextReview, ["SUPERVISOR"]],
  [/^review\/(.+)$/, renderReview, ["SUPERVISOR"]],
  [/^history$/, renderHistory, ["SUPERVISOR"]],
  [/^settings$/, renderSettings, ["SUPERVISOR"]],
];
let cleanups = [];

const currentPath = () => decodeURIComponent((location.hash || "#/").replace(/^#\/?/, "")).replace(/\/$/, "");

function renderNav() {
  const path = "#/" + currentPath(), role = session.me?.role;
  clear(document.getElementById("nav"), NAV.filter(([, , , roles]) => !roles || roles.includes(role)).map(([href, text, ic]) =>
    h("a", { href, "aria-current": (href === "#/" ? path === "#/" : path.startsWith(href)) ? "page" : null }, icon(ic, 19), h("span", {}, text))));
}

function renderRoleSwitcher() {
  const host = document.getElementById("role-switcher");
  if (session.config.auth_mode !== "demo") { clear(host, h("span", { class: "muted" }, session.me?.display_name || "")); return; }
  const select = h("select", { id: "role-select", "aria-label": "Demo role", onchange: (e) => switchUser(e.target.value) },
    ["CITIZEN", "WORKER", "SUPERVISOR"].map((role) => h("optgroup", { label: ROLE_TEXT[role][0].toUpperCase() + ROLE_TEXT[role].slice(1) },
      session.users.filter((u) => u.role === role).map((u) => h("option", { value: u.user_id, selected: u.user_id === session.me.user_id }, u.display_name)))));
  clear(host, h("label", { for: "role-select", style: { display: "flex", gap: "8px", alignItems: "center" } }, icon("user", 17), "Viewing as"), select);
}

function setupSimulationToggle() {
  const label = document.getElementById("sim-toggle"), box = document.getElementById("sim-check");
  label.hidden = !session.config.simulation_allowed;
  box.checked = preference("simulate") === "on";
  box.addEventListener("change", () => preference("simulate", box.checked ? "on" : "off"));
}

const roleGate = (roles) => h("section", { class: "card", style: { alignItems: "center", textAlign: "center", padding: "44px 24px", maxWidth: "560px", margin: "20px auto" } },
  icon("review", 30), h("h2", {}, "This part is for another role"),
  h("p", { class: "muted" }, `It's for the ${roles.map((r) => ROLE_TEXT[r]).join(" or ")}. In the local demo you can switch with one click; the server still checks access.`),
  h("div", { class: "row wrap center" }, roles.map((r) => firstUser(r)).filter(Boolean).map((u) => button(`Continue as ${u.display_name}`, { class: "btn primary", onclick: () => switchUser(u.user_id) }, "user"))));

async function route() {
  cleanups.forEach((fn) => { try { fn(); } catch { /* ignore */ } });
  cleanups = [];
  renderNav();
  // Each navigation draws into its own container. If the user moves on before
  // a slow page finishes, that page writes into a detached node, not over the new one.
  const outer = document.getElementById("main"), path = currentPath();
  const main = h("div", { class: "stack", style: { gap: "22px" } });
  outer.replaceChildren(main);
  for (const [pattern, render, roles] of ROUTES) {
    const match = path.match(pattern);
    if (!match) continue;
    if (roles && !roles.includes(session.me?.role)) { clear(main, roleGate(roles)); return; }
    clear(main, spinner());
    try { await render({ main, params: match.slice(1), onCleanup: (fn) => cleanups.push(fn), rerender: route }); }
    catch (err) { console.error(err); clear(main, errorState(err, route)); }
    if (outer.contains(main)) outer.focus({ preventScroll: true });
    return;
  }
  clear(main, errorState(new Error("Page not found"), () => { location.hash = "#/"; }));
}

async function start() {
  const main = document.getElementById("main");
  clear(main, spinner("Starting GeoSatya…"));
  try { await bootstrap(); } catch (err) { clear(main, errorState(err, start)); return; }
  renderRoleSwitcher();
  setupSimulationToggle();
  session.listeners.add(() => { renderRoleSwitcher(); location.hash = "#/"; route(); });
  window.addEventListener("hashchange", route);
  route();
}

start();
