/* KAVACH shell: public site and signed-in workspaces, role-aware navigation,
   development identity switcher, router. GeoSatya's pages are used as they
   are for incidents, tasks, live tracking and review. */

import { api, bootstrap, connectivity, flushOutbox, loadContext, preference, session, signOut, switchUser } from "./api.js";
import { onChange as onOutboxChange, pending, results } from "./outbox.js";
import { button, clear, errorState, h, icon, spinner, toast } from "./ui.js";
import { renderDashboard } from "./pages/dashboard.js";
import { renderIncident, renderMyReports } from "./pages/incident.js";
import { renderEvidenceShortcut, renderTask, renderTasks } from "./pages/tasks.js";
import { renderNextReview, renderQueue, renderReview } from "./pages/review.js";
import { renderHistory } from "./pages/history.js";
import { renderBoard } from "./pages/board.js";
import { renderSettings } from "./pages/settings.js";
import { renderLiveDashboard } from "./pages/livemap.js";
import { ROLE_INFO, renderFooter, renderPublicBar, roleKey } from "./kavach/brand.js";
import { renderAbout, renderEventSolutions, renderHome, renderOrgSolutions, renderStats, renderTrack } from "./kavach/public.js";
import { renderEnter, renderJoin, renderRegisterOrg, renderRegisterOrganizer } from "./kavach/access.js";
import { renderKavachReport, renderPublicReportGate } from "./kavach/report.js";
import { renderCitizenHome, renderDepartments, renderEventNew, renderEvents, renderInsights, renderMembers, renderWorkspaceHome,
  renderWorkspaceSettings, renderZones } from "./kavach/workspace.js";
import { renderAdmin } from "./kavach/admin.js";

const SUP = ["SUPERVISOR"];
const inWs = () => !!session.ctx?.workspace;
const isAdmin = () => ["ORG_ADMIN", "EVENT_ORGANIZER"].includes(session.me?.platform_role);

/* Navigation per experience. [href, text, icon, show?] */
function navItems() {
  const k = roleKey(session.me);
  if (k === "CITIZEN") return [["#/", "Home", "dashboard"], ["#/report", "Report an issue", "plus"], ["#/reports", "My reports", "list"],
    ["#/track", "Track complaint", "search"], ["#/stats", "Public dashboard", "chart"]];
  if (k === "WORKER") return [["#/", "Home", "dashboard"], ["#/tasks", "My assignments", "tasks"], ["#/evidence", "Submit completion", "upload"],
    inWs() && ["#/report-incident", "Report incident", "plus"]];
  if (k === "EVENT_ORGANIZER") return [["#/events", "My events", "calendar"], ...(inWs() ? [["#/", "Event dashboard", "dashboard"], ["#/live", "Live operations", "live"],
    ["#/board", "Incidents", "alert"], ["#/queue", "Completion review", "review"], ["#/members", "Workers", "users"], ["#/zones", "Zones", "zone"],
    ["#/insights", "Reports", "chart"], ["#/report-incident", "Report incident", "plus"], ["#/workspace-settings", "Event settings", "settings"]] : [])];
  if (k === "ORG_ADMIN") return [["#/", "Overview", "dashboard"], ["#/live", "Live monitoring", "live"], ["#/board", "Incidents & assignments", "alert"],
    ["#/queue", "Completion review", "review"], ["#/departments", "Departments", "building"], ["#/members", "Workers & supervisors", "users"],
    ["#/zones", "Zones", "zone"], ["#/insights", "Reports", "chart"], ["#/history", "Audit history", "history"], ["#/report-incident", "Report incident", "plus"],
    ["#/workspace-settings", "Settings", "settings"]];
  if (k === "PLATFORM_ADMIN") return [["#/admin", "Platform", "shield"], ["#/live", "Civic live map", "live"], ["#/board", "Civic incidents", "alert"],
    ["#/queue", "Reviews", "review"], ["#/history", "Evidence history", "history"], ["#/settings", "Verification limits", "settings"], ["#/stats", "Public dashboard", "chart"]];
  // A supervisor: the open civic team, or inside an organization / event.
  return [["#/", inWs() ? "Overview" : "Live map", "dashboard"], inWs() && ["#/live", "Live map", "live"], ["#/board", "Dispatch board", "alert"],
    ["#/queue", "Reviews", "review"], ["#/history", "Evidence history", "history"], inWs() && ["#/members", "Team", "users"],
    inWs() && ["#/insights", "Reports", "chart"], inWs() && ["#/report-incident", "Report incident", "plus"], !inWs() && ["#/settings", "Settings", "settings"]];
}

function home(ctx) {
  const k = roleKey(session.me);
  if (k === "CITIZEN") return renderCitizenHome(ctx);
  if (k === "PLATFORM_ADMIN") return renderAdmin(ctx);
  if (k === "WORKER") return renderDashboard(ctx);
  if (k === "ORG_ADMIN" || k === "EVENT_ORGANIZER" || inWs()) return renderWorkspaceHome(ctx);
  return renderDashboard(ctx);  // the open civic supervisor lands on GeoSatya's live map
}

/* mode: "public" (site), "app" (signed in), "both" (app when signed in). */
const ROUTES = [
  [/^home$/, renderHome, null, "public"],
  [/^public-report$/, renderPublicReportGate, null, "public"],
  [/^solutions\/events$/, renderEventSolutions, null, "public"],
  [/^solutions\/organizations$/, renderOrgSolutions, null, "public"],
  [/^about$/, renderAbout, null, "public"],
  [/^enter$/, renderEnter, null, "public"],
  [/^register\/organization$/, renderRegisterOrg, null, "public"],
  [/^register\/organizer$/, renderRegisterOrganizer, null, "public"],
  [/^join(?:\/(.+))?$/, renderJoin, null, "public"],
  [/^track(?:\/(.+))?$/, renderTrack, null, "both"],
  [/^stats$/, renderStats, null, "both"],
  [/^$/, home, null, "app"],
  [/^report$/, renderKavachReport, ["CITIZEN"], "app"],
  [/^report-incident$/, renderKavachReport, ["WORKER", "SUPERVISOR"], "app"],
  [/^reports$/, renderMyReports, ["CITIZEN"], "app"],
  [/^incidents\/(.+)$/, renderIncident, null, "app"],
  [/^tasks$/, renderTasks, ["WORKER", "SUPERVISOR"], "app"],
  [/^evidence$/, renderEvidenceShortcut, ["WORKER"], "app"],
  [/^tasks\/(.+)$/, renderTask, ["WORKER", "SUPERVISOR"], "app"],
  [/^live$/, renderLiveDashboard, SUP, "app"],
  [/^board$/, renderBoard, SUP, "app"],
  [/^queue$/, renderQueue, SUP, "app"],
  [/^review$/, renderNextReview, SUP, "app"],
  [/^review\/(.+)$/, renderReview, SUP, "app"],
  [/^history$/, renderHistory, SUP, "app"],
  [/^settings$/, renderSettings, SUP, "app"],
  [/^events$/, renderEvents, ["EVENT_ORGANIZER"], "app"],
  [/^events\/new$/, renderEventNew, ["EVENT_ORGANIZER"], "app"],
  [/^members$/, renderMembers, SUP, "app"],
  [/^departments$/, renderDepartments, ["ORG_ADMIN"], "app"],
  [/^zones$/, renderZones, ["ORG_ADMIN", "EVENT_ORGANIZER"], "app"],
  [/^workspace-settings$/, renderWorkspaceSettings, SUP, "app"],
  [/^insights$/, renderInsights, SUP, "app"],
  [/^admin$/, renderAdmin, ["PLATFORM_ADMIN"], "app"],
];
const allowed = (roles) => !roles || roles.includes(session.me?.role) || roles.includes(session.me?.platform_role);
let cleanups = [];

const currentPath = () => decodeURIComponent((location.hash || "#/").replace(/^#\/?/, "")).replace(/\/$/, "");

function renderNav() {
  const path = "#/" + currentPath();
  const items = navItems().filter(Boolean);
  const active = (href) => (href === "#/" ? path === "#/" : href === "#/queue" ? path.startsWith("#/queue") || path.startsWith("#/review") : path === href || path.startsWith(href + "/"));
  clear(document.getElementById("nav"), items.map(([href, text, ic]) => h("a", { href, "aria-current": active(href) ? "page" : null }, icon(ic, 19), h("span", {}, text))),
    h("a", { href: "#/home", style: { marginTop: "auto", opacity: .8 } }, icon("globe", 19), h("span", {}, "Public site")));
  document.getElementById("ws-name").textContent = session.ctx?.workspace?.name || (roleKey(session.me) === "PLATFORM_ADMIN" ? "Platform administration" : "Civic intelligence");
}

function renderRoleSwitcher() {
  const host = document.getElementById("role-switcher");
  if (!session.me) { clear(host); return; }
  if (session.config.auth_mode !== "demo") { clear(host, h("span", { class: "muted" }, session.me?.display_name || "")); return; }
  const groups = {};
  for (const u of session.users) (groups[ROLE_INFO[roleKey(u)]?.label || u.role] ||= []).push(u);
  const select = h("select", { id: "role-select", "aria-label": "Demo identity", onchange: (e) => switchUser(e.target.value) },
    Object.entries(groups).map(([g, users]) => h("optgroup", { label: g }, users.map((u) => h("option", { value: u.user_id, selected: u.user_id === session.me.user_id }, u.display_name)))));
  clear(host, h("label", { for: "role-select", style: { display: "flex", gap: "8px", alignItems: "center" } }, icon("user", 17), "Viewing as"), select);
}

function renderWorkspaceSwitch() {
  const host = document.getElementById("ws-switch");
  const events = session.ctx?.events || [];
  if (session.me?.platform_role !== "EVENT_ORGANIZER" || !events.length) {
    const w = session.ctx?.workspace;
    clear(host, w ? h("span", { class: "ws-pill" }, icon(w.kind === "EVENT" ? "calendar" : "building", 16), w.name) : null);
    return;
  }
  const sel = h("select", { "aria-label": "Open event", onchange: async (e) => {
    try { await api(`/kavach/events/${e.target.value}/open`, { method: "POST" }); await loadContext(); renderShell(); location.hash = "#/"; route(); }
    catch (err) { toast(err.message, "fail"); }
  } }, !session.ctx.workspace ? h("option", { value: "" }, "Choose an event") : null,
  events.map((ev) => h("option", { value: ev.workspace_id, selected: ev.workspace_id === session.ctx.workspace?.workspace_id }, ev.name)));
  clear(host, h("label", { class: "ws-pill" }, icon("calendar", 16), sel));
}

function setupSimulationToggle() {
  const label = document.getElementById("sim-toggle"), box = document.getElementById("sim-check");
  label.hidden = !session.config.simulation_allowed;
  box.checked = preference("simulate") === "on";
  box.addEventListener("change", () => preference("simulate", box.checked ? "on" : "off"));
}

const roleGate = (roles) => h("section", { class: "card", style: { alignItems: "center", textAlign: "center", padding: "44px 24px", maxWidth: "560px", margin: "20px auto" } },
  icon("review", 30), h("h2", {}, "This part is for another role"),
  h("p", { class: "muted" }, `It's for: ${roles.map((r) => (ROLE_INFO[r]?.label || r).toLowerCase()).join(" or ")}. The server checks access too.`),
  h("div", { class: "row wrap center" }, h("a", { class: "btn primary", href: "#/" }, "Back to my home"), h("a", { class: "btn", href: "#/enter" }, "Switch identity")));

function renderShell() {
  renderRoleSwitcher();
  renderWorkspaceSwitch();
  renderNav();
  document.getElementById("signout").hidden = !session.me || session.config.auth_mode !== "demo";
}

async function route() {
  cleanups.forEach((fn) => { try { fn(); } catch { /* ignore */ } });
  cleanups = [];
  const path = currentPath();
  // Not signed in: "#/" is the public landing page.
  const effective = !session.me && path === "" ? "home" : path;
  const entry = ROUTES.find(([pattern]) => pattern.test(effective));
  const mode = !entry ? (session.me ? "app" : "public") : entry[3] === "both" ? (session.me ? "app" : "public") : entry[3];
  if (mode === "app" && !session.me) { location.hash = "#/enter"; return; }
  document.body.dataset.mode = mode;
  const outer = document.getElementById(mode === "app" ? "main" : "pubmain");
  if (mode === "app") renderNav(); else renderPublicBar(effective);
  // Each navigation draws into its own container. If the user moves on before
  // a slow page finishes, that page writes into a detached node, not over the new one.
  const main = h("div", { class: mode === "app" ? "stack" : "", style: mode === "app" ? { gap: "22px" } : null });
  outer.replaceChildren(main);
  if (mode === "public") window.scrollTo({ top: 0 });
  if (!entry) { clear(main, errorState(new Error("Page not found"), () => { location.hash = "#/"; })); return; }
  const [pattern, render, roles] = entry;
  if (roles && !allowed(roles)) { clear(main, roleGate(roles)); return; }
  clear(main, spinner());
  try { await render({ main, params: effective.match(pattern).slice(1), onCleanup: (fn) => cleanups.push(fn), rerender: route }); }
  catch (err) { console.error(err); clear(main, errorState(err, route)); }
  if (outer.contains(main)) outer.focus({ preventScroll: true });
}

/* ---------------------------------------------- worker app: offline status */
const KIND_TEXT = { accept: "Accept", arrive: "Arrival", start: "Start work", location: "Location", progress: "Progress note", completion: "Completion photo",
  before_photo: "Before photo", checklist: "Checklist" };

async function renderNetStatus() {
  const host = document.getElementById("net-status");
  if (!session.me) { host.hidden = true; return; }
  const waiting = await pending(session.me.user_id).catch(() => []);
  const offline = navigator.onLine === false;
  const unreachable = !offline && !connectivity.serverReachable;
  host.hidden = !offline && !unreachable && !waiting.length;
  clear(host,
    h("span", { class: `net-dot ${offline || unreachable ? "off" : "on"}` }),
    h("span", {}, offline ? "Offline" : unreachable ? "Can't reach the server" : "Online"),
    waiting.length ? h("span", { class: "muted" }, `· ${waiting.length} waiting to send`) : null,
    waiting.length && !offline ? button("Send now", { class: "btn small", onclick: () => sendQueued(true) }) : null);
}

/* Send queued actions, then tell the worker what happened to each. */
async function sendQueued(manual = false) {
  if (!session.me || navigator.onLine === false) return;
  const before = new Set((await results(session.me.user_id).catch(() => [])).map((r) => r.id));
  const sent = await flushOutbox();
  const fresh = (await results(session.me.user_id).catch(() => [])).filter((r) => !before.has(r.id));
  for (const r of fresh) {
    const what = r.label || KIND_TEXT[r.kind] || "Saved action";
    if (!r.ok) toast(`${what} (saved offline) was not accepted: ${r.message}`, "fail");
    else if (r.kind === "completion") {
      const c = r.data?.completion;
      toast(`${what} sent: ${c?.accepted ? "accepted for review" : `not accepted (${(c?.outcome || "").toLowerCase()}): ${c?.message || ""}`}`, c?.accepted ? "pass" : "fail");
    } else if (r.kind !== "location") toast(`${what} sent`, "pass");
  }
  if (manual && !sent) toast("Nothing could be sent yet.", "info");
  if (fresh.some((r) => r.kind !== "location") && /^tasks/.test(currentPath())) route();
}

function setupWorkerApp() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch((err) => console.warn("Service worker not registered:", err.message));
  }
  // Kept for the worker dashboard's "Install app" button (Chrome / Edge / Android).
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); session.installPrompt = e; });
  window.addEventListener("online", () => { renderNetStatus(); sendQueued(); });
  window.addEventListener("offline", renderNetStatus);
  // When the server answers again, show it and send what's waiting.
  window.addEventListener("geosatya-connectivity", () => { renderNetStatus(); if (connectivity.serverReachable) sendQueued(); });
  onOutboxChange(renderNetStatus);
  setInterval(() => sendQueued(), 30000);   // also retries after a server error, not just after "online"
  renderNetStatus();
  sendQueued();
}

async function start() {
  const main = document.getElementById("pubmain");
  clear(main, spinner("Starting Kavach…"));
  try { await bootstrap(); } catch (err) { clear(main, errorState(err, start)); return; }
  renderFooter();
  renderShell();
  setupSimulationToggle();
  setupWorkerApp();
  document.getElementById("signout").addEventListener("click", () => { signOut(); });
  session.listeners.add((user) => { renderShell(); renderNetStatus(); location.hash = user ? "#/" : "#/home"; route(); });
  window.addEventListener("hashchange", route);
  route();
}

start();
