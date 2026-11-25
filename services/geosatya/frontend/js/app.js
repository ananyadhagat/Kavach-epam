/* KAVACH shell: public site and signed-in workspaces, role-aware navigation,
   development identity switcher, router. GeoSatya's pages are used as they
   are for incidents, tasks, live tracking and review. */

import { api, bootstrap, connectivity, defaultDevUser, devAccess, flushOutbox, teamDemo, hasToken, loadContext, preference, session, signOut, switchUser } from "./api.js";
import { onChange as onOutboxChange, pending, results } from "./outbox.js";
import { button, clear, errorState, h, icon, loadingScreen, spinner, toast } from "./ui.js";
import { renderDashboard } from "./pages/dashboard.js";
import { renderIncident, renderMyReports } from "./pages/incident.js";
import { renderEvidenceShortcut, renderTask, renderTasks } from "./pages/tasks.js";
import { renderNextReview, renderQueue, renderReview } from "./pages/review.js";
import { renderHistory } from "./pages/history.js";
import { renderBoard } from "./pages/board.js";
import { renderSettings } from "./pages/settings.js";
import { renderLiveDashboard } from "./pages/livemap.js";
import { ROLE_INFO, renderFooter, renderPublicBar, roleKey } from "./kavach/brand.js";
import { renderAbout, renderEventSolutions, renderOrgSolutions, renderStats, renderTrack } from "./kavach/public.js";
import { renderHome } from "./kavach/home.js";
import { renderEnter, renderJoin, renderRegisterOrg, renderRegisterOrganizer } from "./kavach/access.js";
import { renderCitizenSignup, renderSignin, renderStart, renderSupervisorSignin, renderWorkerSignup } from "./kavach/auth.js";
import { renderProfile, renderShareLocation, renderWorkersList } from "./kavach/profile.js";
import { renderKavachReport, renderPublicReportGate } from "./kavach/report.js";
import { renderCitizenHome, renderDepartments, renderEventNew, renderEvents, renderInsights, renderMembers, renderWorkspaceHome,
  renderWorkspaceSettings, renderZones } from "./kavach/workspace.js";
import { renderAdmin } from "./kavach/admin.js";
import { renderJobs } from "./kavach/jobs.js";
import { renderAllyView, renderSafety, renderWomenInfo } from "./kavach/safety.js";
import { renderTeam } from "./kavach/team.js";
import { renderTeamLogin } from "./kavach/teamlogin.js";

const SUP = ["SUPERVISOR"];
/* Development access: the sign-in pages show the role picker instead (real sign-in returns with AUTH_MODE=jwt). */
const devOr = (render) => (ctx) => (teamDemo() ? renderTeamLogin(ctx) : devAccess() ? renderEnter(ctx) : render(ctx));
const inWs = () => !!session.ctx?.workspace;
const isAdmin = () => ["ORG_ADMIN", "EVENT_ORGANIZER"].includes(session.me?.platform_role);

/* Navigation per experience: the few things each role does every day first;
   everything else under "More" (progressive disclosure). [href, text, icon, more?] */
function navItems() {
  const k = roleKey(session.me);
  if (k === "CITIZEN") return [["#/report", "Report an issue", "plus"], ["#/reports", "My complaints", "list"], ["#/track", "Track complaint", "search"],
    ["#/reports/history", "Complaint history", "history"], ["#/safety", "Women's safety", "heart"], ["#/profile", "Profile", "user"],
    ["#/", "Home", "dashboard", true], ["#/stats", "Public dashboard", "chart", true]];
  if (k === "WORKER") return [["#/tasks", "My tasks", "tasks"], ["#/jobs", "Available tasks", "search"], ["#/location", "Share my location", "crosshair"],
    ["#/task-history", "Task history", "history"], ["#/profile", "Profile", "user"],
    ["#/", "Overview", "dashboard", true], ["#/evidence", "Completion photo", "upload", true], inWs() && ["#/report-incident", "Report incident", "plus", true]];
  if (k === "EVENT_ORGANIZER") return [["#/events", "My events", "calendar"], ...(inWs() ? [["#/board", "Active complaints", "alert"], ["#/members", "Available workers", "users"],
    ["#/tasks", "Assigned tasks", "tasks"], ["#/queue", "Pending approvals", "review"], ["#/live", "Live operations map", "live"],
    ["#/", "Event dashboard", "dashboard", true], ["#/zones", "Zones", "zone", true], ["#/insights", "Reports", "chart", true],
    ["#/report-incident", "Report incident", "plus", true], ["#/workspace-settings", "Event settings", "settings", true]] : []), ["#/profile", "Profile", "user", true]];
  if (k === "PLATFORM_ADMIN") return [["#/admin", "Platform", "shield"], ["#/board", "Active complaints", "alert"], ["#/queue", "Pending approvals", "review"],
    ["#/live", "Live operations map", "live"], ["#/history", "Evidence history", "history", true], ["#/settings", "Verification limits", "settings", true],
    ["#/stats", "Public dashboard", "chart", true], ["#/profile", "Profile", "user", true]];
  // Supervisors and organization admins: the open civic team, or inside an organization / event.
  const civic = !inWs();
  return [["#/board", "Active complaints", "alert"], [civic ? "#/workers" : "#/members", "Available workers", "users"], ["#/tasks", "Assigned tasks", "tasks"],
    ["#/queue", "Pending approvals", "review"], [civic ? "#/" : "#/live", "Live operations map", "live"],
    !civic && ["#/", "Overview", "dashboard", true], !civic && ["#/insights", "Reports", "chart", true], ["#/history", "Evidence history", "history", true],
    k === "ORG_ADMIN" && ["#/departments", "Departments", "building", true], k === "ORG_ADMIN" && ["#/zones", "Zones", "zone", true],
    !civic && ["#/report-incident", "Report incident", "plus", true], civic ? ["#/settings", "Settings", "settings", true] : ["#/workspace-settings", "Settings", "settings", true],
    ["#/profile", "Profile", "user", true]];
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
  [/^enter$/, devOr(renderStart), null, "public"],
  [/^start$/, devOr(renderStart), null, "public"],
  [/^team$/, renderTeam, null, "public"],
  [/^demo$/, devOr(renderEnter), null, "public"],
  [/^signup\/citizen(\?.*)?$/, renderCitizenSignup, null, "public"],
  [/^signup\/worker$/, renderWorkerSignup, null, "public"],
  [/^signin\/supervisor$/, devOr(renderSupervisorSignin), null, "public"],
  [/^signin(\?.*)?$/, devOr(renderSignin), null, "public"],
  [/^register\/organization$/, renderRegisterOrg, null, "public"],
  [/^register\/organizer$/, renderRegisterOrganizer, null, "public"],
  [/^join(?:\/(.+))?$/, renderJoin, null, "public"],
  [/^women$/, renderWomenInfo, null, "public"],
  [/^sos\/([A-Za-z0-9_-]{8,80})$/, renderAllyView, null, "public"],
  [/^track(?:\/(.+))?$/, renderTrack, null, "both"],
  [/^stats$/, renderStats, null, "both"],
  [/^$/, home, null, "app"],
  [/^menu$/, renderMenu, null, "app"],
  [/^report$/, renderKavachReport, ["CITIZEN"], "app"],
  [/^report-incident$/, renderKavachReport, ["WORKER", "SUPERVISOR"], "app"],
  [/^reports$/, renderMyReports, ["CITIZEN"], "app"],
  [/^reports\/history$/, (c) => renderMyReports({ ...c, history: true }), ["CITIZEN"], "app"],
  [/^profile$/, renderProfile, null, "app"],
  [/^location$/, renderShareLocation, ["WORKER"], "app"],
  [/^task-history$/, (c) => renderTasks({ ...c, history: true }), ["WORKER"], "app"],
  [/^workers$/, renderWorkersList, SUP, "app"],
  [/^safety$/, renderSafety, ["CITIZEN"], "app"],
  [/^jobs$/, renderJobs, ["WORKER"], "app"],
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
  const daily = items.filter((i) => !i[3]), more = items.filter((i) => i[3]);
  const active = (href) => (href === "#/" ? path === "#/" : href === "#/queue" ? path.startsWith("#/queue") || path.startsWith("#/review")
    : href === "#/reports" || href === "#/tasks" ? path === href : path === href || path.startsWith(href + "/"));
  const link = ([href, text, ic]) => h("a", { href, "aria-current": active(href) ? "page" : null }, icon(ic, 19), h("span", {}, text));
  const open = more.some(([href]) => active(href));
  clear(document.getElementById("nav"), daily.map(link),
    more.length ? h("details", { class: "nav-more", open: open || null }, h("summary", {}, icon("dots", 19), h("span", {}, "More")), more.map(link)) : null,
    h("a", { href: "#/home", style: { marginTop: "auto", opacity: .8 } }, icon("globe", 19), h("span", {}, "Public site")));
  // Phones: four daily items plus "More" (the full menu) as a bottom bar, reachable with one thumb.
  const SHORT = { "Women's safety": "Safety", "Report an issue": "Report", "Track complaint": "Track", "My complaints": "Complaints", "Available tasks": "Available",
    "Share my location": "Location", "Active complaints": "Complaints", "Available workers": "Workers", "Assigned tasks": "Tasks", "Pending approvals": "Approvals",
    "Live operations map": "Live map", "Complaint history": "History", "Task history": "History" };
  clear(document.getElementById("bottom-nav"), daily.slice(0, 4).map(([href, text, ic]) => h("a", { href, "aria-current": active(href) ? "page" : null }, icon(ic, 22), h("span", {}, SHORT[text] || text))),
    h("a", { href: "#/menu", "aria-current": path === "#/menu" ? "page" : null }, icon("menu", 22), h("span", {}, "More")));
  // Citizens always have a one-tap route to SOS, except on the safety page itself.
  // (not on the report form either, where it would cover the Submit button)
  document.getElementById("sos-fab").hidden = !(roleKey(session.me) === "CITIZEN" && !["#/safety", "#/report"].includes(path));
  document.getElementById("ws-name").textContent = session.ctx?.workspace?.name || (roleKey(session.me) === "PLATFORM_ADMIN" ? "Platform administration" : "Civic intelligence");
}

function renderRoleSwitcher() {
  const host = document.getElementById("role-switcher");
  if (!session.me) { clear(host); return; }
  if (session.config.auth_mode !== "demo" || hasToken() || teamDemo()) {
    const info = ROLE_INFO[roleKey(session.me)] || ROLE_INFO.CITIZEN;
    clear(host, h("a", { class: "who-chip", href: "#/profile" }, icon(info.icon, 16), h("span", {}, session.me?.display_name || ""), h("span", { class: "muted" }, info.label)));
    return;
  }
  const groups = {};
  for (const u of session.users) (groups[ROLE_INFO[roleKey(u)]?.label || u.role] ||= []).push(u);
  const select = h("select", { id: "role-select", "aria-label": "Test identity", onchange: (e) => switchUser(e.target.value) },
    Object.entries(groups).map(([g, users]) => h("optgroup", { label: g }, users.map((u) => h("option", { value: u.user_id, selected: u.user_id === session.me.user_id }, u.display_name)))));
  // One tap per role: the first test identity of that role (civic team first).
  const QUICK = [["CITIZEN", "Citizen"], ["WORKER", "Worker"], ["SUPERVISOR", "Supervisor"], ["ORG_ADMIN", "Organization"], ["EVENT_ORGANIZER", "Event"], ["PLATFORM_ADMIN", "Admin"]];
  const first = (k) => session.users.filter((u) => roleKey(u) === k).sort((a, b) => (a.workspace_id ? 1 : 0) - (b.workspace_id ? 1 : 0))[0];
  const chips = h("div", { class: "dev-roles", role: "group", "aria-label": "Switch role" },
    QUICK.filter(([k]) => first(k)).map(([k, text]) => h("button", { type: "button", class: "dev-role", "aria-pressed": String(roleKey(session.me) === k),
      onclick: () => { const u = first(k); if (u && u.user_id !== session.me.user_id) { location.hash = "#/"; switchUser(u.user_id); } } }, icon(ROLE_INFO[k].icon, 15), text)));
  clear(host, h("span", { class: "dev-badge", title: "Development access: no login. Real sign-in returns with AUTH_MODE=jwt; production refuses this mode." }, "DEV"),
    chips, h("label", { class: "dev-who" }, h("span", { class: "visually-hidden" }, "Test identity"), select));
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

/* Phones: the full menu behind the bottom bar's "More". */
function renderMenu({ main }) {
  const items = navItems().filter(Boolean);
  const row = (href, text, ic) => h("a", { class: "item", href }, icon(ic, 20), h("strong", { class: "grow" }, text), icon("arrowRight", 16));
  clear(main, h("h1", {}, "Menu"), h("div", { class: "items" }, items.map(([href, text, ic]) => row(href, text, ic)), row("#/home", "Public site", "globe"),
    h("button", { class: "item", type: "button", onclick: () => signOut() }, icon("logout", 20), h("strong", { class: "grow", style: { textAlign: "left" } }, "Sign out"))));
}

const roleGate = (roles) => h("section", { class: "card", style: { alignItems: "center", textAlign: "center", padding: "44px 24px", maxWidth: "560px", margin: "20px auto" } },
  icon("review", 30), h("h2", {}, "This part is for another role"),
  h("p", { class: "muted" }, `It's for: ${roles.map((r) => (ROLE_INFO[r]?.label || r).toLowerCase()).join(" or ")}. The server checks access too.`),
  h("div", { class: "row wrap center" }, h("a", { class: "btn primary", href: "#/" }, "Back to my home"), h("a", { class: "btn", href: "#/start" }, "Use another account")));

function renderShell() {
  renderRoleSwitcher();
  renderWorkspaceSwitch();
  renderNav();
  document.getElementById("signout").hidden = !session.me || (devAccess() && !teamDemo());   // development access: switch roles instead
}

async function route() {
  cleanups.forEach((fn) => { try { fn(); } catch { /* ignore */ } });
  cleanups = [];
  const path = currentPath();
  // Not signed in: "#/" is the public landing page.
  const effective = !session.me && path === "" ? "home" : path;
  const entry = ROUTES.find(([pattern]) => pattern.test(effective));
  const mode = !entry ? (session.me ? "app" : "public") : entry[3] === "both" ? (session.me ? "app" : "public") : entry[3];
  if (mode === "app" && !session.me) {
    const dev = devAccess() && !teamDemo() && defaultDevUser();
    if (dev) { await switchUser(dev.user_id); return; }     // development access: straight in, no login
    location.hash = "#/signin"; return;
  }
  document.body.dataset.mode = mode;
  const outer = document.getElementById(mode === "app" ? "main" : "pubmain");
  if (mode === "app") renderNav(); else renderPublicBar(effective);
  // Simulated GPS is a labelled testing aid for reporting; it has no place on the women's safety screen.
  document.getElementById("sim-toggle").hidden = !session.config.simulation_allowed || /^(safety|report$)/.test(effective);   // citizen complaints never use simulated GPS
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
  clear(main, loadingScreen());
  try { await bootstrap(); } catch (err) { clear(main, errorState(err, start)); return; }
  renderFooter();
  renderShell();
  setupSimulationToggle();
  setupWorkerApp();
  document.getElementById("signout").addEventListener("click", () => { signOut(); });
  session.listeners.add((user) => {
    renderShell(); renderNetStatus();
    const next = user ? (session.afterSignIn || "#/") : "#/home";
    session.afterSignIn = null;
    if (location.hash === next) route(); else location.hash = next;   // the hashchange re-routes
  });
  // The token expired or was signed out on another device.
  window.addEventListener("kavach-signed-out", () => { if (session.me) { signOut(); toast("Please sign in again.", "info"); } });
  window.addEventListener("hashchange", route);
  route();
}

start();
