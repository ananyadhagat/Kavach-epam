/* KAVACH workspaces: citizen home, organization and event operations,
   events, members and invitations, departments, zones, settings, reports.
   Live data comes from GeoSatya's own endpoints, which the server scopes to
   the signed-in user's workspace. */

import { api, loadContext, session } from "../api.js";
import { categoryIcon } from "../components.js";
import { createMap, esc } from "../maps.js";
import { banner, button, card, chip, clear, demoTag, emptyState, fmtAgo, fmtTime, h, icon, kv, label, pageHead, toast } from "../ui.js";
import { countUp, hours, initials } from "./brand.js";
import { field, pointPicker, select } from "./widgets.js";

const ws = () => session.ctx?.workspace;
const isEvent = () => ws()?.kind === "EVENT";
const canManage = () => !!session.ctx?.can_manage;
const catalog = async () => (session.catalog ||= await api("/kavach/catalog"));
const VERIFY_TEXT = { VERIFIED: "Verified organization", PENDING: "Verification pending", UNVERIFIED: "Not verified", REJECTED: "Verification rejected", DEMO: "Sample organization" };
const PHASE_TEXT = { LIVE: "Live now", UPCOMING: "Upcoming", ENDED: "Ended", NOT_SCHEDULED: "No dates set" };
const reload = async (ctx) => { await loadContext(); ctx.rerender(); };
const noWorkspace = (main) => clear(main, card({ style: { alignItems: "center", textAlign: "center", padding: "44px 22px" } },
  icon("calendar", 30), h("h2", {}, session.me.platform_role === "EVENT_ORGANIZER" ? "No event is open" : "No workspace"),
  h("p", { class: "muted" }, session.me.platform_role === "EVENT_ORGANIZER" ? "Create an event, or open one of yours." : "This account is not part of a workspace."),
  session.me.platform_role === "EVENT_ORGANIZER" ? h("div", { class: "row wrap center" }, h("a", { class: "btn primary", href: "#/events/new" }, "Create an event"),
    h("a", { class: "btn", href: "#/events" }, "My events")) : null));

function kpi(text, value, ic, tone, href) {
  const n = h("strong", {});
  countUp(n, value);
  return h(href ? "a" : "div", { class: `kpi ${tone}`, href, style: href ? { textDecoration: "none", color: "inherit" } : null },
    h("span", { class: "kico" }, icon(ic, 20)), n, h("span", { class: "lbl" }, text));
}

/* -------------------------------------------------------- citizen home */
export async function renderCitizenHome({ main }) {
  const mine = await api("/incidents").catch(() => []);
  const first = session.me.display_name.split(" ")[0];
  const hour = new Date().getHours();
  const latest = mine[0];
  clear(main,
    h("div", { class: "greet" }, h("span", { class: "face" }, initials(session.me.display_name)),
      h("div", { class: "stack tight" }, h("h1", { style: { fontSize: "24px" } }, `Good ${hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening"}, ${first}`),
        h("span", { class: "muted" }, "Here's what you can do today."))),
    latest ? h("div", { class: "latest" }, h("div", { class: "stack tight" }, h("strong", { style: { fontSize: "17px" } }, latest.title),
      h("span", { style: { opacity: .85 } }, `${latest.category_label} · ${latest.incident_id} · ${latest.status_text}`)),
      h("a", { class: "btn", href: `#/incidents/${latest.incident_id}` }, "View status")) : null,
    h("div", { class: "tiles" },
      h("a", { class: "tile teal", href: "#/report" }, h("span", { class: "tico" }, icon("plus", 22)), h("strong", {}, "Report an issue"), h("span", {}, "Pothole, garbage, leak, streetlight…")),
      h("a", { class: "tile saffron", href: "#/reports" }, h("span", { class: "tico" }, icon("list", 22)), h("strong", {}, "My reports"), h("span", {}, `${mine.length} report${mine.length === 1 ? "" : "s"} so far`)),
      h("a", { class: "tile lime", href: "#/track" }, h("span", { class: "tico" }, icon("search", 22)), h("strong", {}, "Track a complaint"), h("span", {}, "Status by reference number")),
      h("a", { class: "tile navy", href: "#/stats" }, h("span", { class: "tico" }, icon("chart", 22)), h("strong", {}, "Public dashboard"), h("span", {}, "How your city is doing"))),
    card({}, h("h2", {}, "Recent reports"), mine.length ? h("div", { class: "items" }, mine.slice(0, 5).map((i) => h("a", { class: "item", href: `#/incidents/${i.incident_id}` },
      categoryIcon(i.category_icon), h("div", { class: "grow" }, h("strong", {}, i.title), h("span", { class: "muted mono" }, i.incident_id), " ", i.is_demo ? demoTag() : null,
        h("div", { class: "muted" }, `${i.category_label} · ${fmtAgo(i.created_at)}`)), chip(i.status, i.status_text))))
      : emptyState("No reports yet", "When you report something, you can follow it here.", h("a", { class: "btn primary", href: "#/report" }, "Report an issue"))));
}

/* ----------------------------------------------- organization / event home */
export async function renderWorkspaceHome(ctx) {
  const { main, onCleanup } = ctx;
  const w = ws();
  if (!w) return noWorkspace(main);
  const live = await api("/dashboard/live");
  const k = live.kpis, workers = live.workers;
  const offline = workers.filter((x) => ["OFFLINE", "NONE"].includes(x.location_state)).length;
  const sharing = workers.filter((x) => x.location_state === "LIVE").length;
  const high = live.incidents.filter((i) => i.priority === "HIGH").length;
  const escalateAfter = w.settings?.escalation?.unassigned_after_min ?? 30;
  const overdueUnassigned = live.incidents.filter((i) => !i.worker_id && (Date.now() - new Date(i.reported_at)) / 60000 > escalateAfter);
  const mapEl = h("div", { class: "map", style: { height: "360px" }, role: "img", "aria-label": "Map of the workspace" });

  const meta = [h("span", { class: "chip" }, w.category_label),
    w.kind === "EVENT" ? h("span", { class: `chip ${w.phase === "LIVE" ? "phase-live" : ""}` }, PHASE_TEXT[w.phase]) : h("span", { class: "chip" }, VERIFY_TEXT[w.verification_status]),
    w.venue ? h("span", { class: "chip" }, w.venue) : null, w.is_demo ? h("span", { class: "chip" }, "Demo") : null,
    w.kind === "EVENT" && w.starts_at ? h("span", { class: "chip" }, `${fmtTime(w.starts_at)} → ${fmtTime(w.ends_at)}`) : null];
  clear(main,
    h("section", { class: "ws-banner" }, h("div", { style: { position: "relative", zIndex: 1 } },
      h("span", { class: "eyebrow" }, w.kind === "EVENT" ? "Event operations" : "Organization overview"), h("h1", { style: { marginTop: "6px" } }, w.name),
      h("div", { class: "meta" }, meta)),
      h("div", { class: "actions" }, h("a", { class: "btn primary", href: "#/live" }, icon("live", 17), "Live operations"),
        h("a", { class: "btn", href: "#/report-incident" }, icon("plus", 17), "Report incident"),
        canManage() ? h("a", { class: "btn", href: "#/members" }, icon("key", 17), "Invite workers") : null)),
    w.verification_status === "PENDING" ? banner("review", "Your organization is waiting for verification by the Kavach team. You can use the workspace meanwhile.") : null,
    overdueUnassigned.length ? banner("fail", `${overdueUnassigned.length} incident${overdueUnassigned.length > 1 ? "s have" : " has"} had no worker for over ${escalateAfter} min (your escalation rule). `,
      h("a", { href: "#/board" }, "Open the dispatch board")) : null,
    h("div", { class: "kpis" },
      kpi("Registered workers", workers.length, "users", "blue", "#/members"),
      kpi("Sharing location now", sharing, "live", "green", "#/live"),
      kpi("Available", k.available_workers, "check", "green"),
      kpi("On a job", k.assigned_workers + k.travelling_workers + k.on_site_workers, "route", "violet"),
      kpi("On break", workers.filter((x) => x.status === "UNAVAILABLE").length, "clock", "amber"),
      kpi("Offline", offline, "x", "red"),
      kpi("Active incidents", k.open_incidents, "alert", "amber", "#/board"),
      kpi(high ? "High-priority alerts" : "Resolved", high || k.resolved_total, high ? "warn" : "shield", high ? "red" : "green", high ? "#/board" : null)),
    h("div", { class: "grid two" },
      card({ class: "card flush" }, h("div", { class: "pad row between wrap" }, h("h2", {}, w.kind === "EVENT" ? "Venue and zones" : "Service area"),
        h("a", { class: "btn small", href: "#/live" }, "Full live map")), mapEl),
      card({}, h("div", { class: "row between" }, h("h2", {}, "Open incidents"), h("a", { class: "btn small", href: "#/board" }, "Dispatch board")),
        live.incidents.length ? h("div", { class: "items" }, live.incidents.slice(0, 6).map((i) => h("a", { class: "item", href: `#/incidents/${i.incident_id}` },
          h("span", { class: "ico" }, icon(i.icon, 18)), h("div", { class: "grow" }, h("strong", {}, i.title),
            h("span", { class: "muted" }, `${i.category_label} · ${i.worker_name ? i.worker_name.replace(/\s*\(.*\)/, "") : "no worker yet"}`)),
          h("span", { class: `chip ${i.priority === "HIGH" ? "fail" : i.priority === "MEDIUM" ? "review" : ""}` }, i.phase_text))))
          : emptyState("All clear", "No open incidents right now."))),
    w.kind === "ORGANIZATION" ? card({}, h("div", { class: "row between" }, h("h2", {}, "Departments"), canManage() ? h("a", { class: "btn small", href: "#/departments" }, "Manage") : null),
      w.departments.length ? h("div", { class: "facts" }, w.departments.map((d) => h("div", {}, h("span", { class: "muted" }, d.name), h("strong", {}, `${d.members} member${d.members === 1 ? "" : "s"}`),
        h("span", { class: "hint" }, d.supervisor_name ? `Supervisor: ${d.supervisor_name}` : "No supervisor set"))))
        : emptyState("No departments yet", "Add departments like Roads, Sanitation or Electrical.")) : null,
    card({}, h("h2", {}, "Plan"), kv([["Plan", w.plan?.name], ["Worker limit", w.plan?.max_workers ?? "Unlimited"], ["Status", label(w.subscription_status)], ["Pricing", w.plan?.price]])));

  setTimeout(async () => {
    const center = w.center ? [w.center.latitude, w.center.longitude] : [23.2599, 77.4126];
    const map = await createMap(mapEl, { center, zoom: w.kind === "EVENT" ? 15 : 12 });
    onCleanup(() => map.destroy());
    if (w.center && w.radius_m) map.circle("area", center, w.radius_m, "area");
    for (const z of w.zones || []) { map.circle(`z${z.zone_id}`, [z.latitude, z.longitude], z.radius_m, "zone");
      map.html(`zl${z.zone_id}`, [z.latitude, z.longitude], `<span class="zlabel">${esc(z.name)}</span>`, z.name, null, 1); }
    for (const i of live.incidents) map.marker(`i${i.incident_id}`, "target", [i.latitude, i.longitude], i.title);
    for (const x of workers) if (x.location) map.marker(`w${x.worker_id}`, "worker", [x.location.latitude, x.location.longitude], x.name);
    if (w.kind === "ORGANIZATION" && w.radius_m) map.setView(center, w.radius_m > 8000 ? 11 : 12);
  });
}

/* ------------------------------------------------------------- events */
export async function renderEvents(ctx) {
  const { main } = ctx;
  const events = session.ctx?.events || [];
  const openId = ws()?.workspace_id;
  const open = async (id) => { await api(`/kavach/events/${id}/open`, { method: "POST" }); await loadContext(); location.hash = "#/"; };
  const d = (iso) => (iso ? new Date(iso) : null);
  clear(main, pageHead({ title: "My events", subtitle: "Each event is its own private workspace with its own team and incidents.",
    right: [h("a", { class: "btn primary", href: "#/events/new" }, icon("plus", 17), "Create event")] }),
  events.length ? h("div", { class: "grid halves" }, events.map((e) => h("article", { class: `event-card ${e.workspace_id === openId ? "open" : ""}` },
    h("div", { class: "row", style: { gap: "14px", alignItems: "flex-start" } },
      h("span", { class: "event-date" }, d(e.starts_at) ? [h("b", {}, String(d(e.starts_at).getDate())), h("small", {}, d(e.starts_at).toLocaleString(undefined, { month: "short" }))] : icon("calendar", 22)),
      h("div", { class: "stack tight grow" }, h("strong", { style: { fontSize: "17px" } }, e.name), h("span", { class: "muted" }, `${e.category_label}${e.venue ? ` · ${e.venue}` : ""}`),
        h("div", { class: "row wrap", style: { gap: "6px", marginTop: "4px" } }, h("span", { class: `chip ${e.phase === "LIVE" ? "pass" : ""}` }, PHASE_TEXT[e.phase]),
          e.is_demo ? demoTag() : null, e.workspace_id === openId ? chip("ASSIGNED", "Open now") : null))),
    h("div", { class: "facts" }, h("div", {}, h("span", { class: "muted" }, "Workers"), h("strong", {}, String(e.workers))),
      h("div", {}, h("span", { class: "muted" }, "Open incidents"), h("strong", {}, String(e.incidents.open))),
      h("div", {}, h("span", { class: "muted" }, "Resolved"), h("strong", {}, String(e.incidents.resolved)))),
    h("div", { class: "row wrap" }, e.workspace_id === openId ? h("a", { class: "btn primary small", href: "#/" }, "Go to dashboard")
      : button("Open this event", { class: "btn primary small", onclick: () => open(e.workspace_id) }),
    button("Archive", { class: "btn small danger", onclick: async () => {
      if (!confirm(`Archive "${e.name}"? Its records are kept, but it leaves your events list.`)) return;
      await api(`/kavach/events/${e.workspace_id}/archive`, { method: "POST" }); toast("Event archived", "pass"); await reload(ctx);
    } })))))
    : card({}, emptyState("No events yet", "Create your first event to invite workers and go live.", h("a", { class: "btn primary", href: "#/events/new" }, "Create event"))));
}

export async function renderEventNew(ctx) {
  const { main, onCleanup } = ctx;
  const cat = await catalog();
  const now = new Date(); now.setMinutes(0, 0, 0); now.setHours(now.getHours() + 24);
  const local = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const f = {
    name: h("input", { type: "text", id: "ev-name", required: true, minlength: 3, maxlength: 120, placeholder: "e.g. Riverside Food Festival" }),
    category: select("ev-cat", cat.event_categories.map((c) => [c.id, c.label]), "FESTIVAL"),
    desc: h("textarea", { id: "ev-desc", rows: 3, maxlength: 1000 }),
    venue: h("input", { type: "text", id: "ev-venue", maxlength: 200, placeholder: "Venue name" }),
    company: h("input", { type: "text", id: "ev-co", maxlength: 120, value: sessionStorage.getItem("kavach.company") || "" }),
    starts: h("input", { type: "datetime-local", id: "ev-start", value: local(now) }),
    ends: h("input", { type: "datetime-local", id: "ev-end", value: local(new Date(now.getTime() + 8 * 3600e3)) }),
    radius: select("ev-rad", [["300", "300 m"], ["500", "500 m"], ["1000", "1 km"], ["2000", "2 km"], ["5000", "5 km"]], "1000"),
  };
  const defaults = ["medical_assistance", "crowd_management", "security_concern", "missing_person", "event_operations", "garbage", "safety_hazard"];
  const cats = h("div", { class: "choice-grid" }, cat.categories.map((c) => h("label", { class: "choice" },
    h("input", { type: "checkbox", value: c.id, checked: defaults.includes(c.id) }), c.label)));
  const picker = pointPicker({ radius: 1000, label: "Click the map at the venue" });
  f.radius.addEventListener("change", () => picker.setRadius(Number(f.radius.value)));
  const err = h("p", { class: "field-error", "aria-live": "polite" });
  clear(main, pageHead({ crumbs: [["My events", "#/events"]], title: "Create an event", subtitle: "You can change everything later in event settings." }),
    h("form", { class: "stack", style: { gap: "22px" }, onsubmit: async (e) => {
      e.preventDefault(); err.textContent = "";
      const p = picker.state.point;
      if (!p) { err.textContent = "Click the map to set the venue location."; return; }
      const chosen = [...cats.querySelectorAll("input:checked")].map((i) => i.value);
      if (!chosen.length) { err.textContent = "Choose at least one incident category."; return; }
      try {
        const ev = await api("/kavach/events", { method: "POST", json: { name: f.name.value, category: f.category.value, description: f.desc.value,
          venue: f.venue.value || null, company: f.company.value || null, center_latitude: p[0], center_longitude: p[1], radius_m: Number(f.radius.value),
          starts_at: f.starts.value ? new Date(f.starts.value).toISOString() : null, ends_at: f.ends.value ? new Date(f.ends.value).toISOString() : null,
          categories: chosen } });
        toast(`${ev.name} created`, "pass"); await loadContext(); location.hash = "#/zones";
      } catch (ex) { err.textContent = ex.message; }
    } },
    card({}, h("h2", {}, "1 · The event"), h("div", { class: "form-grid" }, field("Event name", f.name), field("Category", f.category),
      field("Organizing company", f.company), field("Venue", f.venue), field("Starts", f.starts), field("Ends", f.ends), field("Description", f.desc, null, "full"))),
    card({}, h("h2", {}, "2 · Where"), picker.el, field("Event boundary", f.radius, "Incidents reported outside it are flagged for you, not blocked.")),
    card({}, h("h2", {}, "3 · Incident types"), h("p", { class: "muted" }, "Your team can only report the types you enable."), cats),
    err, h("div", {}, h("button", { class: "btn primary big", type: "submit" }, "Create event"))));
  await picker.mount();
  onCleanup(() => picker.destroy());
}

/* ----------------------------------------------------------- members */
export async function renderMembers(ctx) {
  const { main } = ctx;
  const w = ws();
  if (!w) return noWorkspace(main);
  const cat = await catalog();
  const [members, invites] = await Promise.all([api(`/kavach/workspaces/${w.workspace_id}/members`),
    canManage() ? api(`/kavach/workspaces/${w.workspace_id}/invites`) : Promise.resolve([])]);
  const skillBoxes = (id) => h("div", { class: "choice-grid", id }, cat.skills.map((s) => h("label", { class: "choice" }, h("input", { type: "checkbox", value: s }), label(s))));
  const chosen = (el) => [...el.querySelectorAll("input:checked")].map((i) => i.value);
  const deps = [["", "No department"], ...(w.departments || []).map((d) => [d.department_id, d.name])];
  const roles = w.settings?.worker_roles || [];

  const patch = async (m, body, msg) => {
    try { await api(`/kavach/workspaces/${w.workspace_id}/members/${m.user_id}`, { method: "PATCH", json: body }); toast(msg, "pass"); ctx.rerender(); }
    catch (ex) { toast(ex.message, "fail"); }
  };
  const row = (m) => h("div", { class: "member-row" }, h("span", { class: "mini-av" }, initials(m.name)),
    h("div", { class: "stack tight", style: { minWidth: 0 } }, h("strong", {}, m.name, " ", !m.active ? chip("FAIL", "Deactivated") : null),
      h("span", { class: "muted" }, [m.role === "WORKER" ? "Worker" : "Supervisor", m.department, m.skills?.length ? m.skills.map(label).join(", ") : null].filter(Boolean).join(" · ")),
      h("span", { class: "hint" }, m.role === "WORKER" ? `${m.available ? "Available" : "On break"} · ${m.active_tasks} open task${m.active_tasks === 1 ? "" : "s"} · ${m.location_shared_at ? `location shared ${fmtAgo(m.location_shared_at)}` : "no location shared yet"}` : "")),
    canManage() ? h("div", { class: "row wrap", style: { justifyContent: "flex-end", gap: "6px" } },
      m.role === "WORKER" && m.active ? button(m.available ? "Mark on break" : "Mark available", { class: "btn small", onclick: () => patch(m, { available: !m.available }, "Updated") }) : null,
      button(m.active ? "Deactivate" : "Reactivate", { class: `btn small ${m.active ? "danger" : ""}`, onclick: () => patch(m, { active: !m.active }, m.active ? "Deactivated" : "Reactivated") })) : null);

  const addForm = () => {
    const name = h("input", { type: "text", id: "m-name", required: true, minlength: 2, maxlength: 80 });
    const role = select("m-role", [["WORKER", "Field worker"], ["SUPERVISOR", "Supervisor"]], "WORKER");
    const dep = select("m-dep", deps, "");
    const job = select("m-job", [["", "—"], ...roles.map((r) => [r, r])], "");
    const skills = skillBoxes("m-skills");
    return h("form", { class: "stack", onsubmit: async (e) => {
      e.preventDefault();
      try {
        await api(`/kavach/workspaces/${w.workspace_id}/members`, { method: "POST", json: { name: name.value, role: role.value,
          department_id: dep.value || null, job_role: job.value || null, skills: chosen(skills) } });
        toast(`${name.value} added`, "pass"); ctx.rerender();
      } catch (ex) { toast(ex.message, "fail"); }
    } }, h("div", { class: "form-grid" }, field("Name", name), field("Role", role), w.kind === "ORGANIZATION" ? field("Department", dep) : null, field("Job role", job)),
    h("span", { class: "lbl" }, "Skills (used by dispatch)"), skills, h("div", {}, h("button", { class: "btn primary", type: "submit" }, icon("plus", 16), "Add member")));
  };
  const inviteForm = () => {
    const role = select("i-role", [["WORKER", "Field worker"], ["SUPERVISOR", "Supervisor"]], "WORKER");
    const dep = select("i-dep", deps, "");
    const skills = skillBoxes("i-skills");
    const out = h("div");
    return h("form", { class: "stack", onsubmit: async (e) => {
      e.preventDefault();
      try {
        const r = await api(`/kavach/workspaces/${w.workspace_id}/invites`, { method: "POST", json: { role: role.value, department_id: dep.value || null, skills: chosen(skills) } });
        const link = `${location.origin}${location.pathname}#/join/${r.code}`;
        clear(out, h("div", { class: "authority-card" }, h("span", { class: "ico" }, icon("key", 20)), h("div", { class: "stack tight" },
          h("span", { class: "lbl" }, "One-time invite code"), h("span", { class: "code-big" }, r.code),
          h("span", { class: "hint" }, "Share the code or this link. It works once."), h("span", { class: "mono", style: { overflowWrap: "anywhere" } }, link),
          button("Copy link", { class: "btn small", onclick: async () => { try { await navigator.clipboard.writeText(link); toast("Link copied", "pass"); } catch { toast("Copy it from the screen", "info"); } } }, "copy"))));
      } catch (ex) { toast(ex.message, "fail"); }
    } }, h("div", { class: "form-grid" }, field("Invite as", role), w.kind === "ORGANIZATION" ? field("Department", dep) : null),
    h("span", { class: "lbl" }, "Skills"), skills, h("div", {}, h("button", { class: "btn primary", type: "submit" }, icon("key", 16), "Create invite code")), out);
  };
  const workersN = members.filter((m) => m.role === "WORKER").length;
  clear(main, pageHead({ title: isEvent() ? "Event team" : "Workers & supervisors",
    subtitle: `${workersN} worker${workersN === 1 ? "" : "s"}${w.plan?.max_workers ? ` of ${w.plan.max_workers} on the ${w.plan.name} plan` : ""}` }),
  h("div", { class: "grid two" },
    card({}, h("h2", {}, "Members"), members.length ? h("div", {}, members.map(row)) : emptyState("No members yet", "Add workers directly or send an invite code.")),
    canManage() ? h("div", { class: "stack", style: { gap: "22px" } },
      card({}, h("h2", {}, "Invite with a code"), inviteForm()),
      card({}, h("details", {}, h("summary", {}, "Add a member directly"), h("div", { style: { marginTop: "12px" } }, addForm()))),
      invites.length ? card({}, h("h2", {}, "Invite codes"), h("div", {}, invites.slice(0, 10).map((i) => h("div", { class: "member-row" },
        h("span", { class: "mono" }, i.code), h("span", { class: "muted" }, `${i.role === "WORKER" ? "Worker" : "Supervisor"} · ${fmtAgo(i.created_at)}`),
        i.used ? chip("PASS", `Used by ${i.used_by_name}`) : chip("", "Unused"))))) : null)
      : card({}, h("p", { class: "muted" }, "Only the workspace administrator can add members."))));
}

/* -------------------------------------------------------- departments */
export async function renderDepartments(ctx) {
  const { main } = ctx;
  const w = ws();
  if (!w) return noWorkspace(main);
  const cat = await catalog();
  const members = await api(`/kavach/workspaces/${w.workspace_id}/members`);
  const sups = members.filter((m) => m.role === "SUPERVISOR");
  const name = h("input", { type: "text", id: "d-name", required: true, minlength: 2, maxlength: 120, placeholder: "e.g. Road Maintenance" });
  const desc = h("input", { type: "text", id: "d-desc", maxlength: 500 });
  const sup = select("d-sup", [["", "No supervisor yet"], ...sups.map((s) => [s.user_id, s.name])], "");
  const cats = h("div", { class: "choice-grid" }, cat.categories.filter((c) => (w.settings?.categories || []).includes(c.id)).map((c) =>
    h("label", { class: "choice" }, h("input", { type: "checkbox", value: c.id }), c.label)));
  clear(main, pageHead({ title: "Departments", subtitle: `${w.name} → departments → supervisors → workers` }),
    h("div", { class: "grid two" },
      card({}, h("h2", {}, "Structure"), w.departments.length ? h("div", {}, w.departments.map((d) => h("div", { class: "member-row" },
        h("span", { class: "ico" }, icon("building", 18)), h("div", { class: "stack tight" }, h("strong", {}, d.name),
          h("span", { class: "muted" }, `${d.members} member${d.members === 1 ? "" : "s"} · ${d.supervisor_name ? `supervisor ${d.supervisor_name}` : "no supervisor"}`),
          d.categories.length ? h("span", { class: "hint" }, d.categories.map((c) => session.categories.find((x) => x.id === c)?.label || c).join(", ")) : null),
        canManage() ? button("Remove", { class: "btn small danger", onclick: async () => {
          if (!confirm(`Remove the ${d.name} department? Its members stay in the organization.`)) return;
          await api(`/kavach/workspaces/${w.workspace_id}/departments/${d.department_id}`, { method: "DELETE" }); toast("Department removed", "pass"); await reload(ctx);
        } }) : null))) : emptyState("No departments yet")),
      canManage() ? card({}, h("h2", {}, "Add a department"), h("form", { class: "stack", onsubmit: async (e) => {
        e.preventDefault();
        try {
          await api(`/kavach/workspaces/${w.workspace_id}/departments`, { method: "POST", json: { name: name.value, description: desc.value,
            supervisor_id: sup.value || null, categories: [...cats.querySelectorAll("input:checked")].map((i) => i.value) } });
          toast("Department added", "pass"); await reload(ctx);
        } catch (ex) { toast(ex.message, "fail"); }
      } }, field("Name", name), field("Description", desc), field("Supervisor", sup, sups.length ? null : "Add a supervisor on the Workers page first."),
      h("span", { class: "lbl" }, "Handles these categories"), cats, h("div", {}, h("button", { class: "btn primary", type: "submit" }, "Add department")))) : null));
}

/* --------------------------------------------------------------- zones */
export async function renderZones(ctx) {
  const { main, onCleanup } = ctx;
  const w = ws();
  if (!w) return noWorkspace(main);
  const name = h("input", { type: "text", id: "z-name", required: true, minlength: 2, maxlength: 120, placeholder: "e.g. Gate 2, Medical tent" });
  const kind = select("z-kind", [["AREA", "Area"], ["STAGE", "Stage"], ["GATE", "Gate / entry"], ["MEDICAL", "Medical"], ["SERVICE", "Service point"], ["PARKING", "Parking"]], "AREA");
  const radius = select("z-rad", [["30", "30 m"], ["60", "60 m"], ["100", "100 m"], ["200", "200 m"], ["500", "500 m"]], "60");
  const center = w.center ? [w.center.latitude, w.center.longitude] : null;
  const picker = pointPicker({ center, radius: 60, kind: "zone", label: "Click the map where the zone is" });
  radius.addEventListener("change", () => picker.setRadius(Number(radius.value)));
  clear(main, pageHead({ title: isEvent() ? "Event zones" : "Operational zones", subtitle: "Zones appear on every live map and can be attached to incident reports." }),
    h("div", { class: "grid two" },
      card({}, h("h2", {}, canManage() ? "Add a zone" : "Zones"), picker.el, canManage() ? h("form", { class: "stack", onsubmit: async (e) => {
        e.preventDefault();
        const p = picker.state.point;
        if (!p) { toast("Click the map to place the zone", "fail"); return; }
        try {
          await api(`/kavach/workspaces/${w.workspace_id}/zones`, { method: "POST", json: { name: name.value, kind: kind.value, latitude: p[0], longitude: p[1], radius_m: Number(radius.value) } });
          toast("Zone added", "pass"); await reload(ctx);
        } catch (ex) { toast(ex.message, "fail"); }
      } }, h("div", { class: "form-grid" }, field("Name", name), field("Type", kind), field("Radius", radius)), h("div", {}, h("button", { class: "btn primary", type: "submit" }, "Add zone"))) : null),
      card({}, h("h2", {}, `${w.zones.length} zone${w.zones.length === 1 ? "" : "s"}`), w.zones.length ? h("div", {}, w.zones.map((z) => h("div", { class: "member-row" },
        h("span", { class: "ico" }, icon("zone", 18)), h("div", { class: "stack tight" }, h("strong", {}, z.name), h("span", { class: "muted" }, `${label(z.kind)} · ${z.radius_m} m`)),
        canManage() ? button("Remove", { class: "btn small danger", onclick: async () => {
          await api(`/kavach/workspaces/${w.workspace_id}/zones/${z.zone_id}`, { method: "DELETE" }); toast("Zone removed", "pass"); await reload(ctx);
        } }) : null))) : emptyState("No zones yet", "Add the stage, gates, medical tent and service points."))));
  const map = await picker.mount();
  onCleanup(() => picker.destroy());
  for (const z of w.zones) { map.circle(`z${z.zone_id}`, [z.latitude, z.longitude], z.radius_m, "zone");
    map.html(`zl${z.zone_id}`, [z.latitude, z.longitude], `<span class="zlabel">${esc(z.name)}</span>`, z.name, null, 1); }
  if (center && w.radius_m) { map.circle("area", center, w.radius_m, "area"); map.setView(center, isEvent() ? 15 : 12); }
}

/* ------------------------------------------------------------ settings */
export async function renderWorkspaceSettings(ctx) {
  const { main } = ctx;
  const w = ws();
  if (!w) return noWorkspace(main);
  const cat = await catalog();
  const s = w.settings || {};
  const local = (iso) => (iso ? new Date(new Date(iso).getTime() - new Date(iso).getTimezoneOffset() * 60000).toISOString().slice(0, 16) : "");
  const f = {
    name: h("input", { type: "text", id: "s-name", value: w.name, minlength: 3, maxlength: 120 }),
    desc: h("textarea", { id: "s-desc", rows: 3, maxlength: 1000, value: w.description || "" }),
    venue: h("input", { type: "text", id: "s-venue", value: w.venue || "", maxlength: 200 }),
    starts: h("input", { type: "datetime-local", id: "s-start", value: local(w.starts_at) }),
    ends: h("input", { type: "datetime-local", id: "s-end", value: local(w.ends_at) }),
    roles: h("input", { type: "text", id: "s-roles", value: (s.worker_roles || []).join(", "), maxlength: 400 }),
    escalate: h("input", { type: "number", id: "s-esc", min: 1, max: 1440, value: s.escalation?.unassigned_after_min ?? 30 }),
    high: h("input", { type: "checkbox", id: "s-high", checked: s.notifications?.high_priority_alerts !== false }),
    daily: h("input", { type: "checkbox", id: "s-daily", checked: !!s.notifications?.daily_summary }),
  };
  const enabled = new Set(s.categories || []);
  const cats = h("div", { class: "choice-grid" }, cat.categories.map((c) => h("label", { class: "choice" },
    h("input", { type: "checkbox", value: c.id, checked: enabled.has(c.id) }), c.label)));
  const targets = h("div", { class: "form-grid" }, cat.categories.filter((c) => enabled.has(c.id)).map((c) =>
    field(c.label, h("input", { type: "number", min: 0.25, max: 720, step: 0.25, "data-cat": c.id, value: s.target_hours?.[c.id] ?? c.target_hours ?? 24 }), "hours")));
  const ro = !canManage();
  if (ro) main.dataset.readonly = "1";
  clear(main, pageHead({ title: isEvent() ? "Event settings" : "Organization settings", subtitle: ro ? "Only the workspace administrator can change these." : "Changes apply to your workspace only." }),
    h("form", { class: "stack", style: { gap: "22px" }, onsubmit: async (e) => {
      e.preventDefault();
      const chosen = [...cats.querySelectorAll("input:checked")].map((i) => i.value);
      const target_hours = Object.fromEntries([...targets.querySelectorAll("input[data-cat]")].map((i) => [i.dataset.cat, Number(i.value)]));
      try {
        await api(`/kavach/workspaces/${w.workspace_id}`, { method: "PUT", json: {
          name: f.name.value, description: f.desc.value, venue: f.venue.value || null,
          ...(isEvent() ? { starts_at: f.starts.value ? new Date(f.starts.value).toISOString() : null, ends_at: f.ends.value ? new Date(f.ends.value).toISOString() : null } : {}),
          settings: { categories: chosen, worker_roles: f.roles.value.split(",").map((x) => x.trim()).filter(Boolean), target_hours,
            escalation: { unassigned_after_min: Number(f.escalate.value), notify_admin: true },
            notifications: { high_priority_alerts: f.high.checked, daily_summary: f.daily.checked } } } });
        toast("Settings saved", "pass"); await reload(ctx);
      } catch (ex) { toast(ex.message, "fail"); }
    } },
    card({}, h("h2", {}, "General"), h("div", { class: "form-grid" }, field("Name", f.name), field(isEvent() ? "Venue" : "Address / area", f.venue),
      isEvent() ? field("Starts", f.starts) : null, isEvent() ? field("Ends", f.ends) : null, field("Description", f.desc, null, "full"))),
    card({}, h("h2", {}, "Incident categories"), h("p", { class: "muted" }, "Members can only report enabled categories; dispatch uses each category's required skills."), cats),
    card({}, h("h2", {}, "Resolution targets"), h("p", { class: "muted" }, "Your own targets, used on the reports page. Save after changing categories to see new ones here."), targets),
    card({}, h("h2", {}, "Team and escalation"), h("div", { class: "form-grid" },
      field("Job roles", f.roles, "Comma-separated; offered when adding members."),
      field("Escalate when no worker for", f.escalate, "minutes; shown as an alert on your overview"))),
    card({}, h("h2", {}, "Notifications"), banner("review", "Preferences are saved, but no delivery channel (SMS, email, push) is connected yet, so nothing is sent."),
      h("label", { class: "toggle" }, f.high, "Alert me about high-priority incidents"), h("label", { class: "toggle" }, f.daily, "Daily summary")),
    ro ? null : h("div", {}, h("button", { class: "btn primary big", type: "submit" }, "Save settings"))));
  if (ro) main.querySelectorAll("input, textarea, select").forEach((el) => { el.disabled = true; });
}

/* ------------------------------------------------------------- reports */
export async function renderInsights({ main }) {
  const w = ws();
  if (!w) return noWorkspace(main);
  const r = await api(`/kavach/workspaces/${w.workspace_id}/report`);
  const max = Math.max(1, ...r.by_category.map((c) => c.total));
  const dayMax = Math.max(1, ...r.by_day.map((d) => d.count));
  const target = w.settings?.target_hours || {};
  const late = r.recent.filter((i) => i.status !== "RESOLVED" && target[i.category] && (Date.now() - new Date(i.created_at)) / 3600e3 > target[i.category]);
  clear(main, pageHead({ title: "Reports", subtitle: `${w.name} · all incidents in this workspace` }),
    h("div", { class: "kpis" }, kpi("Incidents", r.total, "alert", "blue"), kpi("Resolved", r.resolved, "check", "green"),
      kpi("Open", r.total - r.resolved, "clock", "amber"), kpi("Past your target", late.length, "warn", late.length ? "red" : "green")),
    h("div", { class: "grid two" },
      card({}, h("h2", {}, "By category"), r.by_category.length ? h("div", { class: "bars" }, r.by_category.map((c) => h("div", { class: "bar-row" },
        h("span", {}, c.label), h("span", { class: "track" }, h("span", { style: { width: `${(100 * c.total) / max}%` } })), h("strong", {}, `${c.resolved}/${c.total}`))))
        : emptyState("No incidents yet")),
      card({}, h("h2", {}, "Per day"), r.by_day.length ? [h("div", { class: "chart-bars", role: "img", "aria-label": "Incidents per day" },
        r.by_day.map((d, i) => h("span", { title: `${d.day}: ${d.count}`, style: { height: `${(100 * d.count) / dayMax}%`, animationDelay: `${i * 30}ms` } }))),
        h("div", { class: "row between muted", style: { fontSize: "12.5px" } }, h("span", {}, r.by_day[0].day), h("span", {}, r.by_day.at(-1).day))] : emptyState("No incidents yet"))),
    card({}, h("h2", {}, "Recent incidents"), r.recent.length ? h("div", { class: "table-wrap" }, h("table", { class: "list" },
      h("thead", {}, h("tr", {}, ["Reference", "Title", "Category", "Reported", "Status", "Target"].map((t) => h("th", {}, t)))),
      h("tbody", {}, r.recent.map((i) => h("tr", {}, h("td", {}, h("a", { href: `#/incidents/${i.incident_id}`, class: "mono" }, i.incident_id)), h("td", {}, i.title),
        h("td", {}, i.category_label), h("td", {}, fmtTime(i.created_at)), h("td", {}, chip(i.status, i.status_text)),
        h("td", {}, target[i.category] ? (late.includes(i) ? chip("FAIL", `over ${hours(target[i.category])}`) : hours(target[i.category])) : "—")))))) : emptyState("No incidents yet")));
}
