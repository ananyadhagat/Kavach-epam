/* Supervisor home: live tracking dashboard. KPI cards, filters, a map of open
   incidents and field workers, the live worker list, what needs attention,
   and the selected incident with its worker, trail, route and estimates.
   Refreshes by polling every 15 s while the tab is visible, and every 5 s for
   the selected worker while their location is live. */

import { api, preference, session } from "../api.js";
import { createMap, esc } from "../maps.js";
import { banner, button, card, chip, clear, fmtAgo, fmtM, fmtTime, h, icon, kv, label } from "../ui.js";

const POLL_MS = 15000, LIVE_POLL_MS = 5000;
const PHASE_COLOR = {
  UNASSIGNED: "#DC2626", AWAITING_ACCEPTANCE: "#D97706", ACCEPTED: "#D97706", EN_ROUTE: "#2563EB",
  ARRIVED: "#7C3AED", IN_PROGRESS: "#7C3AED", AWAITING_REVIEW: "#0E7490", RESOLVED: "#16A34A",
};
const WORKER_COLOR = { AVAILABLE: "#16A34A", ASSIGNED: "#D97706", EN_ROUTE: "#2563EB", ON_SITE: "#7C3AED", BUSY: "#64748B", UNAVAILABLE: "#94A3B8" };
const WORKER_TEXT = { AVAILABLE: "Available", ASSIGNED: "Assigned", EN_ROUTE: "Travelling", ON_SITE: "On site", BUSY: "At capacity", UNAVAILABLE: "Unavailable" };
const FLAG_TEXT = { UNASSIGNED: "Awaiting worker", ACCEPTANCE_OVERDUE: "Not accepted in time", TRACKING_STALE: "Tracking stale",
  WORKER_STATIONARY: "Worker not moving", ETR_OVERDUE: "Past estimate", AWAITING_EVIDENCE: "Awaiting rework", AWAITING_REVIEW: "Awaiting review" };
const LOC_TEXT = { LIVE: "Live", STALE: "Stale", OFFLINE: "Offline", NONE: "No location" };
const initials = (name) => String(name || "?").replace(/\(.*\)/, "").trim().split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();
const mins = (s) => (s == null ? "—" : s < 90 ? `${Math.round(s)} s` : s < 3600 ? `${Math.round(s / 60)} min` : `${Math.floor(s / 3600)} h`);

/* The filters, and how each one tests an incident or a worker. */
const FILTERS = {
  category: { label: "Category", all: "All categories", options: () => session.categories.map((c) => [c.id, c.label]), test: (i, v) => i.category === v },
  priority: { label: "Priority", all: "Any priority", options: () => [["HIGH", "High"], ["MEDIUM", "Medium"], ["NORMAL", "Normal"], ["LOW", "Low"]], test: (i, v) => i.priority === v },
  status: { label: "Status", all: "Any status", options: () => [["SUBMITTED", "Received"], ["ASSIGNED", "Assigned"], ["IN_PROGRESS", "Work in progress"],
    ["AWAITING_VERIFICATION", "Being verified"]], test: (i, v) => i.status === v },
  assignment: { label: "Assignment", all: "Any assignment", options: () => [["UNASSIGNED", "No worker yet"], ["AWAITING_ACCEPTANCE", "Waiting to be accepted"],
    ["ACCEPTED", "Accepted"], ["EN_ROUTE", "Worker on the way"], ["ON_SITE", "Worker on site"], ["AWAITING_REVIEW", "Awaiting review"]],
    test: (i, v) => (v === "ON_SITE" ? ["ARRIVED", "IN_PROGRESS"].includes(i.phase) : i.phase === v) },
  workers: { label: "Workers", all: "All workers", options: () => [["AVAILABLE", "Available"], ["BUSY_ANY", "Assigned / travelling / on site"],
    ["UNAVAILABLE", "Unavailable"], ["LIVE", "Live location only"]],
    test: (w, v) => (v === "BUSY_ANY" ? ["ASSIGNED", "EN_ROUTE", "ON_SITE", "BUSY"].includes(w.status) : v === "LIVE" ? w.location_state === "LIVE" : w.status === v) },
};
const INCIDENT_FILTERS = ["category", "priority", "status", "assignment"];

/* Live map | Dispatch board: two views of the same work, one menu item. */
export const viewSwitch = (current) => h("div", { class: "seg", role: "tablist", "aria-label": "Dashboard view" },
  h("a", { href: "#/", role: "tab", "aria-selected": String(current === "map") }, "Live map"),
  h("a", { href: "#/board", role: "tab", "aria-selected": String(current === "board") }, "Dispatch board"));

function loadFilters() {
  try { return { ...Object.fromEntries(Object.keys(FILTERS).map((k) => [k, ""])), ...JSON.parse(preference("liveFilters") || "{}") }; }
  catch { return Object.fromEntries(Object.keys(FILTERS).map((k) => [k, ""])); }
}

export async function renderLiveDashboard({ main, onCleanup }) {
  const state = { data: null, selected: null, filters: loadFilters(), layers: { incidents: true, workers: true }, tracking: null };
  const kpiRow = h("div", { class: "kpis" });
  const mapEl = h("div", { class: "map live", role: "img", "aria-label": "Map of open incidents and field workers" });
  const workerList = h("div", { class: "wlist" });
  const attention = h("div", { class: "stack tight" });
  const detail = h("div", { class: "stack" });
  const updated = h("span", { class: "muted" });
  const shown = h("span", { class: "muted" });
  let map = null, timer = null, liveTimer = null, fitted = false;

  const setFilter = (key, value) => {
    state.filters[key] = value;
    preference("liveFilters", JSON.stringify(state.filters));
    draw();
  };
  const selects = Object.entries(FILTERS).map(([key, f]) => h("label", { class: "filter" }, h("span", { class: "lbl" }, f.label),
    h("select", { "aria-label": f.label, onchange: (e) => setFilter(key, e.target.value) },
      h("option", { value: "" }, f.all), f.options().map(([v, t]) => h("option", { value: v, selected: state.filters[key] === v }, t)))));
  const clearBtn = button("Clear filters", { class: "btn small", onclick: () => {
    Object.keys(state.filters).forEach((k) => { state.filters[k] = ""; });
    preference("liveFilters", null);
    selects.forEach((l) => { l.querySelector("select").value = ""; });
    draw();
  } }, "x");
  const toggle = (key, text) => h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: true,
    onchange: (e) => { state.layers[key] = e.target.checked; draw(); } }), text);

  clear(main,
    h("header", { class: "page-head" }, h("div", { class: "stack tight" }, viewSwitch("map"), h("h1", {}, "Live tracking"),
      h("p", { class: "muted" }, "Open incidents and field workers · updates automatically")),
      h("div", { class: "row wrap" }, toggle("incidents", "Incidents"), toggle("workers", "Workers"), updated)),
    kpiRow,
    h("details", { class: "card filters-card", open: window.innerWidth > 700 }, h("summary", {}, "Filters ", shown),
      h("div", { class: "filters" }, selects, clearBtn)),
    h("div", { class: "live-grid" },
      card({ class: "card flush" }, mapEl, h("div", { class: "pad legend live-legend" },
        Object.entries({ "Awaiting worker": PHASE_COLOR.UNASSIGNED, "Assigned": PHASE_COLOR.ACCEPTED, "Worker on the way": PHASE_COLOR.EN_ROUTE,
          "Being resolved": PHASE_COLOR.IN_PROGRESS, "Awaiting review": PHASE_COLOR.AWAITING_REVIEW })
          .map(([t, c]) => h("span", {}, h("i", { style: { background: c } }), t)),
        h("span", {}, h("i", { class: "ring" }), "Worker (faded = stale location)"),
        h("span", {}, h("i", { class: "trail" }), "Worker's recent trail"))),
      card({}, h("h2", {}, "Field workers"), workerList)),
    h("div", { class: "grid two" }, card({}, h("h2", {}, "Selected incident"), detail), card({}, h("h2", {}, "Needs attention"), attention)));

  /* Fresh tracking for the selected incident; while it's live the worker's marker moves with it. */
  const loadTracking = async () => {
    const id = state.selected;
    const inc = state.data?.incidents.find((i) => i.incident_id === id);
    if (!inc?.task_id) { state.tracking = null; return; }
    let t = null;
    try { t = await api(`/incidents/${id}/tracking`); } catch { t = null; }
    if (state.selected !== id) return;
    state.tracking = t;
    const w = state.data.workers.find((x) => x.worker_id === inc.worker_id);
    if (t?.latest && w) {
      w.location = { ...(w.location || {}), latitude: t.latest.latitude, longitude: t.latest.longitude, accuracy_m: t.latest.accuracy_m, mode: t.latest.mode };
      w.location_age_s = t.latest.age_s;
      w.location_state = t.latest.kind === "CURRENT" ? "LIVE" : "STALE";
    }
  };
  const syncLiveTimer = () => {
    const live = state.tracking?.state === "LIVE";
    if (live && !liveTimer) liveTimer = setInterval(async () => {
      if (document.visibilityState === "hidden") return;
      await loadTracking(); draw(); syncLiveTimer();
    }, LIVE_POLL_MS);
    if (!live && liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  };

  const select = async (id) => {
    state.selected = id;
    state.tracking = null;
    draw();
    await loadTracking();
    draw();
    syncLiveTimer();
  };

  const draw = () => {
    const d = state.data;
    if (!d) return;
    const k = d.kpis;
    const kpi = (n, text, ic, tone, sub) => h("div", { class: `kpi ${tone}` }, h("span", { class: "kico" }, icon(ic, 20)),
      h("div", { class: "stack tight" }, h("span", { class: "lbl" }, text), h("strong", {}, String(n)), sub ? h("span", { class: "muted" }, sub) : null));
    clear(kpiRow,
      kpi(k.total_reported, "Total reported", "list", "blue"),
      kpi(k.open_incidents, "Open", "alert", "blue", `${k.awaiting_worker} without a worker`),
      kpi(k.available_workers, "Available workers", "user", "green"),
      kpi(k.assigned_workers, "Workers assigned", "tasks", "amber", "not travelling yet"),
      kpi(k.travelling_workers, "Travelling", "navigate", "amber", "on the way to a job"),
      kpi(k.work_in_progress, "Work in progress", "settings", "violet", `${k.awaiting_review} awaiting review`),
      kpi(k.resolved_total, "Resolved", "check", "green", `${k.resolved_today} today`),
      kpi(k.overdue, "Overdue", "warn", "red", "past estimate or not accepted"));

    const f = state.filters;
    const incidents = d.incidents.filter((i) => INCIDENT_FILTERS.every((key) => !f[key] || FILTERS[key].test(i, f[key])));
    const workers = d.workers.filter((w) => !f.workers || FILTERS.workers.test(w, f.workers));
    const active = Object.values(f).filter(Boolean).length;
    shown.textContent = active ? `· ${active} on · showing ${incidents.length} of ${d.incidents.length} incidents, ${workers.length} of ${d.workers.length} workers` : "";

    const inc = incidents.find((i) => i.incident_id === state.selected);
    const t = inc ? state.tracking : null;
    if (map) {
      const keep = new Set();
      if (state.layers.incidents) for (const i of incidents) {
        const id = `i:${i.incident_id}`, sel = i.incident_id === state.selected;
        keep.add(id);
        map.html(id, [i.latitude, i.longitude], `<span class="imark${sel ? " sel" : ""}" style="--c:${PHASE_COLOR[i.phase] || "#334155"}"></span>`,
          `${i.incident_id} · ${i.title} · ${i.phase_text} · priority ${i.priority}`, () => select(i.incident_id), sel ? 30 : 22);
      }
      if (state.layers.workers) for (const w of workers.filter((x) => x.location)) {
        const id = `w:${w.worker_id}`;
        keep.add(id);
        const acc = w.location.accuracy_m != null ? ` · ±${Math.round(w.location.accuracy_m)} m` : "";
        map.html(id, [w.location.latitude, w.location.longitude],
          `<span class="wmark${w.location_state === "STALE" ? " stale" : ""}" style="--c:${WORKER_COLOR[w.status]}">${esc(initials(w.name))}</span>`,
          `${w.name} · ${WORKER_TEXT[w.status]} · ${w.location_state === "LIVE" ? "live" : "last seen"} ${mins(w.location_age_s)} ago${acc}${w.location.mode === "SIMULATED" ? " (simulated)" : ""}`,
          w.current_incident_id ? () => select(w.current_incident_id) : null, 34);
      }
      if (t?.latest && inc) {
        const here = [t.latest.latitude, t.latest.longitude];
        // Where they've been (recent shared positions, oldest first), how sure the GPS is, and the way to the job.
        const trail = (t.history || []).map((p) => [p.latitude, p.longitude]);
        if (trail.length > 1) { keep.add("trail"); map.line("trail", trail, "#7C3AED", false, 3); }
        if (t.latest.accuracy_m) { keep.add("acc"); map.circle("acc", here, t.latest.accuracy_m, "worker"); }
        keep.add("route");
        if (t.route?.geometry?.length) map.line("route", t.route.geometry, "#2563EB");
        else map.line("route", [here, [inc.latitude, inc.longitude]], "#64748B", true);
      }
      for (const id of map.ids()) if (!keep.has(id)) map.remove(id);
      if (!fitted) {
        // Zoom to what's active: open incidents and workers with a live position (a stale one far away shouldn't zoom out the city).
        const pts = [...incidents.map((i) => [i.latitude, i.longitude]),
          ...workers.filter((w) => w.location_state === "LIVE").map((w) => [w.location.latitude, w.location.longitude])];
        if (pts.length) { map.fit(pts); fitted = true; }
      }
    }

    clear(workerList, workers.length ? workers.map((w) => h("button", { class: "witem", type: "button", disabled: !w.current_incident_id,
      onclick: () => w.current_incident_id && select(w.current_incident_id) },
      h("span", { class: "avatar", style: `--c:${WORKER_COLOR[w.status]}` }, initials(w.name)),
      h("span", { class: "grow stack tight" }, h("strong", {}, w.name),
        h("span", { class: "muted" }, w.current_incident_id ? `${WORKER_TEXT[w.status]} · ${w.current_incident_id}` : `${WORKER_TEXT[w.status]} · ${w.active_tasks}/${w.max_active_tasks} tasks`)),
      h("span", { class: "stack tight", style: { alignItems: "flex-end" } },
        h("span", { class: `dot ${w.location_state.toLowerCase()}` }, LOC_TEXT[w.location_state]),
        w.location_age_s != null ? h("span", { class: "muted" }, `${mins(w.location_age_s)} ago${w.location?.accuracy_m != null ? ` · ±${Math.round(w.location.accuracy_m)} m` : ""}`) : null)))
      : h("p", { class: "muted" }, d.workers.length ? "No worker matches the filter." : "No field workers."));

    const flagged = incidents.filter((i) => i.flags.length);
    clear(attention, flagged.length ? flagged.map((i) => h("button", { class: "witem", type: "button", onclick: () => select(i.incident_id) },
      h("span", { class: "grow stack tight" }, h("strong", {}, i.title), h("span", { class: "muted mono" }, i.incident_id, " · ", i.category_label)),
      h("span", { class: "row wrap", style: { gap: "4px", justifyContent: "flex-end" } }, i.flags.map((fl) => h("span", { class: `chip ${fl === "UNASSIGNED" || fl === "ACCEPTANCE_OVERDUE" ? "fail" : "review"}` }, FLAG_TEXT[fl] || label(fl))))))
      : banner("pass", active ? "Nothing that matches the filters needs attention." : "Nothing needs attention right now."));

    const trailInfo = t?.history?.length > 1
      ? `${t.history.length} positions over ${mins((new Date(t.history.at(-1).received_at) - new Date(t.history[0].received_at)) / 1000)}` : null;
    clear(detail, !inc ? h("p", { class: "muted" }, state.selected ? "The selected incident is hidden by the filters." : "Click an incident or a worker on the map.") : [
      h("div", { class: "row between wrap" }, h("div", { class: "stack tight" }, h("strong", {}, inc.title), h("span", { class: "muted mono" }, `${inc.incident_id} · ${inc.category_label}`)),
        h("span", { class: "row" }, h("span", { class: `chip ${inc.priority === "HIGH" ? "fail" : inc.priority === "MEDIUM" ? "review" : ""}` }, inc.priority), chip("", inc.phase_text))),
      kv([["Worker", inc.worker_name || "Not assigned"],
        ["Location", t?.latest ? h("span", {}, h("span", { class: `dot ${t.latest.kind === "CURRENT" ? "live" : "stale"}` }, t.latest.kind === "CURRENT" ? "Live" : "Last known"),
          ` · updated ${fmtAgo(t.latest.received_at)} · GPS ±${Math.round(t.latest.accuracy_m || 0)} m${t.latest.mode === "SIMULATED" ? " (simulated)" : ""}`) : t ? label(t.state) : "—"],
        trailInfo && ["Trail", trailInfo],
        ["Distance", t?.eta?.road_distance_m != null ? `${fmtM(t.eta.road_distance_m)} by road · ${fmtM(t.eta.straight_distance_m)} straight` : t?.eta?.distance_m != null ? `${fmtM(t.eta.distance_m)} straight line` : "—"],
        ["ETA", t?.eta ? (t.eta.minutes_low != null && t.eta.state === "AVAILABLE" ? `≈ ${t.eta.minutes_low}–${t.eta.minutes_high} min (${t.eta.speed_source === "ROAD_ROUTE" ? "road route" : "approximate"})` : label(t.eta.state)) : "—"],
        ["ETR", inc.etr?.state === "ESTIMATED" ? `by ${fmtTime(inc.etr.due_at)}` : label(inc.etr?.state)],
        ["Verification", inc.verification_outcome ? chip(inc.verification_outcome) : "—"]]),
      t?.state === "LIVE" ? h("p", { class: "hint" }, "Live: this worker's position refreshes every 5 seconds.") : null,
      t && !t.route && t.latest ? h("p", { class: "hint" }, d.routing === "none" ? "Dashed line: straight line, not a road route (routing is off)." : "No road route available right now; the dashed line is a straight line.") : null,
      h("div", { class: "row wrap" }, h("a", { class: "btn small primary", href: `#/incidents/${inc.incident_id}` }, "Open incident"),
        h("a", { class: "btn small", href: "#/board" }, "Dispatch board"))]);
    updated.textContent = `Updated ${fmtAgo(d.generated_at)}`;
  };

  const load = async () => {
    if (document.visibilityState === "hidden") return;
    try {
      state.data = await api("/dashboard/live");
      if (state.selected && state.data.incidents.some((i) => i.incident_id === state.selected)) await loadTracking();
      draw();
      syncLiveTimer();
    } catch (err) { clear(attention, banner("fail", err.code === "NETWORK" ? "Can't reach the server: the map is not updating." : err.message)); }
  };
  map = await createMap(mapEl, { center: [23.2599, 77.4126], zoom: 13 });
  await load();
  timer = setInterval(load, POLL_MS);
  onCleanup(() => { clearInterval(timer); clearInterval(liveTimer); map?.destroy(); });
}
