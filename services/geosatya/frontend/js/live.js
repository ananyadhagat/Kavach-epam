/* Live progress: the journey of a report after it is filed, the worker's
   location (only while shared), ETA (arrival) and ETR (resolution), plus the
   supervisor's Incident Intelligence and Dispatch panels and the worker's
   location sharing. Estimates are always labelled approximate. */

import { api, session } from "./api.js";
import { DEMO_CENTER, locate, simulatedFix, simulationOn } from "./capture.js";
import { createMap, legend } from "./maps.js";
import { banner, button, card, chip, clear, fmtAgo, fmtM, fmtTime, h, icon, kv, label, reasonDialog, toast } from "./ui.js";

const POLL_MS = 15000;
const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—");
const dur = (min) => {
  if (min == null) return "—";
  if (min < 1) return "< 1 min";
  const m = Math.round(min);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60 ? `${m % 60} min` : ""}`.trim();
};

/* ---------------------------------------------------------------- journey */
const JOURNEY = [
  ["reported_at", "Reported"], ["assigned_at", "Assigned"], ["tracking_started_at", "On the way"],
  ["arrived_at", "Arrived"], ["work_started_at", "Working"], ["completion_submitted_at", "Verifying"], ["resolved_at", "Resolved"],
];

export function journey(progress) {
  const reached = JOURNEY.map(([k]) => !!progress?.[k]);
  const now = reached.lastIndexOf(true);
  const items = [];
  JOURNEY.forEach(([k, text], i) => {
    if (i) items.push(h("i", { "aria-hidden": "true" }, "›"));
    items.push(h("span", { class: i === now ? "now" : reached[i] ? "done" : "", title: progress?.[k] ? fmtTime(progress[k], true) : "Not reached" },
      text, progress?.[k] ? h("small", {}, ` ${clock(progress[k])}`) : null));
  });
  return h("div", { class: "lifecycle journey", "aria-label": `Progress: ${JOURNEY[now]?.[1] || "Reported"}` }, items);
}

/* ------------------------------------------------------------- ETA / ETR */
function etaBox(eta) {
  const head = h("span", { class: "lbl" }, "Worker arrival (ETA)");
  if (!eta) return h("div", {}, head, h("strong", {}, "—"));
  const range = eta.minutes_low != null ? `≈ ${eta.minutes_low}–${eta.minutes_high} min` : null;
  const body = {
    AVAILABLE: [h("strong", {}, range), h("span", { class: "muted" }, `around ${clock(eta.eta_at_low)}–${clock(eta.eta_at_high)} · ${fmtM(eta.distance_m)} away (straight line)`)],
    STALE: [h("strong", {}, "Location update is stale"), h("span", { class: "muted" }, range ? `Last estimate ${range}, from ${fmtAgo(new Date(Date.now() - eta.location_age_s * 1000).toISOString())}` : "")],
    WAITING_FOR_LOCATION: [h("strong", {}, "Waiting for worker location"), h("span", { class: "muted" }, "ETA unavailable until the worker shares their location.")],
    ARRIVED: [h("strong", {}, "Arrived"), h("span", { class: "muted" }, eta.arrived_at ? `at ${clock(eta.arrived_at)} (estimated from shared location)` : "Work has started at the site.")],
    NOT_APPLICABLE: [h("strong", {}, "—"), h("span", { class: "muted" }, "Not travelling to this task.")],
  }[eta.state] || [h("strong", {}, "ETA unavailable")];
  return h("div", { class: `est ${eta.state === "STALE" ? "warn" : ""}` }, head, ...body,
    eta.state === "AVAILABLE" || eta.state === "STALE" ? h("span", { class: "hint" }, eta.speed_source === "OBSERVED_APPROACH"
      ? "Approximate: based on how fast the worker has been approaching." : "Approximate: assumes a typical city travel speed. Arrival estimate may change.") : null);
}

function etrBox(etr) {
  const head = h("span", { class: "lbl" }, "Resolution (ETR)");
  if (!etr || etr.state === "UNAVAILABLE") return h("div", { class: "est" }, head, h("strong", {}, "Estimate unavailable"), h("span", { class: "muted" }, etr?.message || ""));
  if (etr.state === "RESOLVED") {
    const a = etr.actual || {};
    return h("div", { class: "est ok" }, head, h("strong", {}, `Resolved in ${dur(a.total_min)}`),
      h("span", { class: "muted" }, `Actual time from report (${fmtTime(a.reported_at)}) to approval (${fmtTime(a.resolved_at)}).`),
      kv([a.to_assignment_min != null && ["Until assigned", dur(a.to_assignment_min)], a.travel_min != null && ["Travel", dur(a.travel_min)],
        a.work_min != null && ["On-site work", dur(a.work_min)], a.review_min != null && ["Supervisor review", dur(a.review_min)]]));
  }
  const b = etr.basis || {};
  return h("div", { class: `est ${etr.state === "OVERDUE" ? "warn" : ""}` }, head,
    h("strong", {}, etr.state === "OVERDUE" ? "Taking longer than estimated" : `By about ${clock(etr.due_at)}`),
    h("span", { class: "muted" }, etr.state === "OVERDUE" ? `Estimated ${fmtTime(etr.due_at)}` : `≈ ${dur(etr.remaining_min)} from now · updated ${clock(etr.updated_at)} (${label(etr.updated_on)})`),
    h("span", { class: "hint" }, "Approximate, not a deadline. ", [b.travel_min ? `Travel ${b.travel_min} min (${label(b.travel_source)}), ` : "",
      b.work_min ? `work ${b.work_min} min (${b.work_source === "HISTORICAL_MEDIAN" ? `median of ${b.history_samples} past jobs` : "category baseline"}), ` : "",
      `review ${b.review_min} min.`].join("")),
    ...(b.notes || []).map((n) => h("span", { class: "hint" }, n)));
}

/* ----------------------------------------------- progress card (incident) */
export function progressCard(inc, ctx) {
  const role = session.me.role;
  if (!inc.task) {
    return card({}, h("h2", {}, "Progress"), journey(inc.progress),
      banner("info", role === "CITIZEN" ? "Your report is saved. We're finding a field worker for it." : "No field worker assigned yet. See Dispatch below."));
  }
  const body = h("div", { class: "stack" }, h("div", { class: "row" }, h("span", { class: "spinner" }), "Loading live status…"));
  const mapEl = h("div", { class: "map short", role: "img", "aria-label": "Map: incident location and the worker's last shared position" });
  let map = null, timer = null, mapReady = null;
  const active = ["ASSIGNED", "IN_PROGRESS"].includes(inc.task.status);

  const draw = (t) => {
    const latest = t.latest;
    clear(body,
      journey({ ...inc.progress, ...pick(t) }),
      h("div", { class: "facts est-row" }, etaBox(t.eta), etrBox(t.etr)),
      trackingLine(t, role));
    mapEl.hidden = !latest;
    if (latest) {
      mapReady ||= createMap(mapEl, { center: [t.target.latitude, t.target.longitude], zoom: 15 }).then((m) => { map = m; return m; });
      mapReady.then((m) => {
        const target = [t.target.latitude, t.target.longitude], w = [latest.latitude, latest.longitude];
        m.marker("t", "target", target, "Incident location");
        m.marker("w", latest.mode === "SIMULATED" ? "simulated" : "worker", w,
          `${latest.kind === "CURRENT" ? "Worker now" : "Worker last seen"} · ${fmtAgo(latest.received_at)}`);
        (t.history || []).forEach((p, i) => m.circle(`h${i}`, [p.latitude, p.longitude], 4, "worker"));
        m.fit([target, w]);
      });
    }
  };
  const load = async () => {
    if (document.visibilityState === "hidden") return;
    try { draw(await api(`/incidents/${inc.incident_id}/tracking`)); }
    catch (err) { clear(body, banner(err.code === "NETWORK" ? "review" : "fail", err.code === "NETWORK" ? "You're offline or the server is unreachable. Showing nothing rather than an old position." : err.message)); }
  };
  load();
  if (active) timer = setInterval(load, POLL_MS);
  ctx.onCleanup(() => { clearInterval(timer); map?.destroy(); });
  return card({}, h("div", { class: "row between wrap" }, h("h2", {}, "Live progress"), active ? h("span", { class: "muted" }, "Refreshes every 15 s") : null),
    body, mapEl, legend(["target", "worker"]));
}

const pick = (t) => ({ tracking_started_at: t.tracking_started_at, arrived_at: t.arrived_at, work_started_at: t.work_started_at });

function trackingLine(t, role) {
  const l = t.latest;
  const text = {
    LIVE: l ? `Location shared ${fmtAgo(l.received_at)} · GPS ±${Math.round(l.accuracy_m || 0)} m` : "Location sharing on",
    STALE: l ? `Last known location, ${fmtAgo(l.received_at)}. The worker's device has stopped updating (offline, app closed or permission removed).` : "No recent location.",
    STOPPED: role === "CITIZEN" ? "The worker is not sharing their location right now." : `Sharing stopped${l ? `; last known ${fmtAgo(l.received_at)}` : ""}.`,
    NOT_STARTED: "The worker hasn't shared a location yet.",
    ENDED: "Field work finished; location sharing has ended.",
  }[t.state];
  return h("div", { class: "row wrap", style: { gap: "8px" } },
    chip(t.state === "LIVE" ? "PASS" : t.state === "STALE" ? "REVIEW_REQUIRED" : "", { LIVE: "Live", STALE: "Stale", STOPPED: "Not sharing", NOT_STARTED: "Not started", ENDED: "Ended" }[t.state]),
    l?.mode === "SIMULATED" ? h("span", { class: "chip demo" }, "Simulated") : null,
    h("span", { class: "muted" }, text));
}

/* --------------------------------------------- worker: share my location */
export function locationSharer(t, ctx) {
  const min = Math.max(10, session.config.tracking?.min_interval_s || 10) * 1000;
  const status = h("div", { class: "stack tight", "aria-live": "polite" });
  let watchId = null, timer = null, lastSent = 0, simPos = null, on = false;
  const target = [t.target_latitude, t.target_longitude];

  const send = async (fix) => {
    if (Date.now() - lastSent < min) return;
    lastSent = Date.now();
    if (!navigator.onLine) { show("review", "You're offline. Your location will not update until you're back online."); return; }
    try {
      const r = await api(`/tasks/${t.task_id}/location`, { method: "POST", json: {
        latitude: fix.latitude, longitude: fix.longitude, accuracy_m: fix.accuracy_m, observed_at: fix.observed_at, mode: fix.mode } });
      if (r.stored) show("pass", `Shared at ${new Date().toLocaleTimeString()} · ${fmtM(r.distance_m)} from the spot${r.arrived ? " · arrived" : ""}${fix.mode === "SIMULATED" ? " (simulated)" : ""}`);
    } catch (err) { show("fail", err.message); if (err.status === 409) stop(false); }
  };
  const show = (kind, text) => clear(status, banner(kind, text),
    h("span", { class: "hint" }, "Only you, the supervisor and the citizen who reported this can see it, and only for this task. A web page can't share in the background: keep this page open while travelling."));

  const start = async () => {
    on = true; draw();
    if (simulationOn()) {
      // Labelled demo: start ~1.3 km away and move ~100 m toward the spot each step.
      simPos ||= simulatedFix(target, { north: 1100, east: 700, accuracy: 12 });
      const step = () => {
        const d = [target[0] - simPos.latitude, target[1] - simPos.longitude];
        const dist = Math.hypot(d[0] * 111320, d[1] * 111320 * Math.cos(target[0] * Math.PI / 180));
        const k = dist <= 100 ? 1 : 100 / dist;
        simPos = { ...simPos, latitude: simPos.latitude + d[0] * k + (k === 1 ? 2 / 111320 : 0), longitude: simPos.longitude + d[1] * k, observed_at: new Date().toISOString() };
        send(simPos);
      };
      step(); timer = setInterval(step, min);
      return;
    }
    if (!window.isSecureContext || !navigator.geolocation) { show("fail", "Location sharing needs https:// or http://localhost."); on = false; draw(); return; }
    show("info", "Waiting for your first location… allow it if asked.");
    watchId = navigator.geolocation.watchPosition(
      (p) => send({ latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy_m: p.coords.accuracy, observed_at: new Date(p.timestamp).toISOString(), mode: "LIVE" }),
      (e) => show("fail", e.code === 1 ? "Location permission is blocked. Allow it in the address-bar site settings to share your location." : "Your device couldn't get a position. Sharing will continue when it can."),
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 30000 });
  };
  const stop = async (tellServer = true) => {
    on = false;
    if (watchId != null) navigator.geolocation.clearWatch(watchId);
    clearInterval(timer); watchId = null; timer = null;
    if (tellServer) { try { await api(`/tasks/${t.task_id}/tracking/stop`, { method: "POST" }); } catch { /* shown as stale anyway */ } }
    clear(status, h("p", { class: "muted" }, "Location sharing is off."));
    draw();
  };
  const btn = h("div", { class: "row wrap" });
  const draw = () => clear(btn, on ? button("Stop sharing", { class: "btn", onclick: () => stop() }, "x")
    : button(simulationOn() ? "Share location (simulated travel)" : "Share my location while travelling", { class: "btn primary", onclick: start }, "navigate"));
  draw();
  clear(status, h("p", { class: "muted" }, "Share your location so the citizen and supervisor see an arrival estimate. It stops automatically when you submit the completion."));
  ctx.onCleanup(() => { if (watchId != null) navigator.geolocation.clearWatch(watchId); clearInterval(timer); });
  return card({}, h("div", { class: "row between wrap" }, h("h2", {}, "Live location"), btn), status);
}

/* ------------------------------------------------ worker: availability */
export async function availabilityCard(ctx) {
  const box = h("div", { class: "stack" });
  const draw = (me) => clear(box,
    h("div", { class: "row between wrap" }, h("div", { class: "stack tight" }, h("h2", {}, "Availability for dispatch"),
      h("span", { class: "muted" }, me.available ? "You can receive new tasks." : "You won't receive new tasks.")),
      button(me.available ? "Go unavailable" : "Go available", { class: me.available ? "btn" : "btn primary", onclick: () => checkIn(!me.available, false) })),
    kv([["Skills", (me.skills || []).map(label).join(", ") || "None set"],
      ["Location for dispatch", me.location_shared_at ? `${label(me.location_source)} ${fmtAgo(me.location_shared_at)}${me.location_mode === "SIMULATED" ? " (simulated)" : ""}` : "Not shared"]]),
    h("div", { class: "row wrap" }, button(simulationOn() ? "Share location once (simulated)" : "Share my location once", { onclick: () => checkIn(me.available, true) }, "crosshair"),
      h("span", { class: "hint" }, `Dispatch prefers the nearest worker whose location is under ${Math.round(me.dispatch_location_max_age_s / 60)} min old. This is one reading, not tracking.`)));
  const checkIn = async (available, share) => {
    let location = null;
    if (share) {
      const f = simulationOn() ? simulatedFix(DEMO_CENTER, { north: 250, east: 150, accuracy: 10 }) : await locate();
      if (f.status !== "ok") { toast(f.message, "fail"); return; }
      location = { latitude: f.latitude, longitude: f.longitude, accuracy_m: f.accuracy_m, observed_at: f.observed_at, mode: f.mode };
    }
    try { draw(await api("/workers/me/check-in", { method: "POST", json: { available, location } })); toast("Saved", "pass"); }
    catch (err) { toast(err.message, "fail"); }
  };
  try { draw(await api("/workers/me")); } catch (err) { clear(box, banner("fail", err.message)); }
  return card({}, box);
}

/* ------------------------------------------- supervisor: intelligence */
export function intelligenceCard(inc, ctx) {
  const i = inc.intelligence || {};
  const text = {
    NOT_CONFIGURED: "The Incident Intelligence agent isn't connected (INTELLIGENCE_URL is empty). The report was dispatched with NORMAL priority.",
    UNAVAILABLE: `The agent couldn't be reached (${i.last_error || "unavailable"}). The report is safe; priority is NORMAL until it succeeds.`,
    FAILED: `The agent couldn't analyse this report (${i.last_error || "error"}).`,
    CONFLICT: "The agent already holds a different report under this request id. Check the agent's records.",
    PENDING: "Analysis in progress.",
  }[i.status];
  const retry = ["UNAVAILABLE", "FAILED", "NOT_CONFIGURED", "PENDING"].includes(i.status)
    ? button("Retry analysis", { class: "btn small", onclick: async () => {
      try { const r = await api(`/incidents/${inc.incident_id}/intelligence/retry`, { method: "POST" }); toast(`Analysis: ${label(r.status)}`, r.status === "COMPLETED" ? "pass" : "info"); ctx.rerender(); }
      catch (err) { toast(err.message, "fail"); } } }, "refresh") : null;
  return card({}, h("div", { class: "row between wrap" }, h("h2", {}, "Incident Intelligence"), h("div", { class: "row" }, chip(i.status === "COMPLETED" ? "PASS" : "REVIEW_REQUIRED", label(i.status)), retry)),
    h("p", { class: "hint" }, "System-generated by the KAVACH Incident Intelligence agent. The citizen's own category and words above are unchanged."),
    i.status === "COMPLETED" ? [
      kv([["Priority", h("span", { class: `chip ${i.priority === "HIGH" ? "fail" : i.priority === "MEDIUM" ? "review" : ""}` }, i.priority)],
        ["Severity", `${i.severity}${i.severity_rule_matches?.length ? ` (safety rules: ${i.severity_rule_matches.join(", ")})` : ""}`],
        ["Classified as", `${label(i.category)} › ${label(i.incident_type)}`], ["Summary", i.summary], ["Why", i.severity_reason],
        i.needs_clarification && ["Questions for the citizen", (i.clarification_questions || []).join(" ")],
        i.missing_information?.length && ["Missing", i.missing_information.map(label).join(", ")],
        ["Agent record", h("span", { class: "mono" }, i.external_incident_id || "—")], ["Analysed", fmtTime(i.completed_at)]])]
      : banner(i.status === "PENDING" ? "info" : "review", text || "Not analysed."));
}

/* ----------------------------------------------- supervisor: dispatch */
export function dispatchCard(inc, ctx) {
  const d = inc.dispatch, task = inc.task;
  const workerSelect = h("select", { id: "assign-worker", "aria-label": "Field worker" }, h("option", { value: "" }, "Loading workers…"));
  api("/workers").then((ws) => clear(workerSelect, h("option", { value: "" }, "Choose a worker"), ws.map((w) => h("option", { value: w.worker_id, disabled: task?.worker_id === w.worker_id },
    `${w.name} · ${w.active_tasks}/${w.max_active_tasks} tasks · ${w.available ? "available" : "unavailable"} · ${w.location_fresh ? "location fresh" : "no recent location"}`))))
    .catch(() => clear(workerSelect, h("option", { value: "" }, "Couldn't load workers")));
  const act = async (path, needReason) => {
    if (!workerSelect.value) { toast("Choose a worker first.", "fail"); return; }
    const reason = await reasonDialog({ title: needReason ? "Reassign this task" : "Assign this incident", confirmText: needReason ? "Reassign" : "Assign",
      description: needReason ? "Tracking of the current worker stops and their shared locations for this task are deleted." : null, required: needReason });
    if (reason == null) return;
    try { await api(path, { method: "POST", json: { worker_id: workerSelect.value, reason } }); toast("Assigned", "pass"); ctx.rerender(); }
    catch (err) { toast(err.message, "fail"); }
  };
  const retry = button("Run dispatch again", { class: "btn small", onclick: async () => {
    try { const r = await api(`/incidents/${inc.incident_id}/dispatch/retry`, { method: "POST" }); toast(r.task ? "Assigned" : "Still no eligible worker", r.task ? "pass" : "info"); ctx.rerender(); }
    catch (err) { toast(err.message, "fail"); } } }, "refresh");
  const canReassign = task && ["ASSIGNED", "IN_PROGRESS"].includes(task.status);
  return card({}, h("div", { class: "row between wrap" }, h("h2", {}, "Dispatch"), d ? chip(d.status === "ASSIGNED" ? "PASS" : "FAIL", label(d.status)) : null),
    d ? [kv([["Method", label(d.method)], ["Decision", d.reason], ["Priority", d.priority], ["Needs skills", (d.required_skills || []).map(label).join(", ") || "—"],
      d.worker_name && ["Worker", d.worker_name], ["Decided", fmtTime(d.decided_at)]]),
      d.ranking?.length ? h("details", {}, h("summary", {}, `Ranking (${d.ranking.length} eligible)`), h("table", { class: "mini" },
        h("tr", {}, ["Worker", "Distance", "Open tasks", "Score"].map((x) => h("th", {}, x))),
        d.ranking.map((c) => h("tr", {}, h("td", {}, c.worker_name), h("td", {}, `${c.distance_km} km`), h("td", {}, String(c.active_tasks)), h("td", {}, String(c.score)))))) : null,
      d.rejected?.length ? h("details", {}, h("summary", {}, `Not eligible (${d.rejected.length})`), h("ul", { class: "plain" },
        d.rejected.map((r) => h("li", {}, h("strong", {}, r.worker_name || r.worker_id), `: ${r.reasons.join(", ")}`)))) : null,
      h("p", { class: "hint" }, "Ranking rules from the KAVACH Dispatch Agent: skills, availability, capacity, location under 15 min old and within the dispatch radius; then 70% distance, 30% workload.")]
      : h("p", { class: "muted" }, "No dispatch decision recorded (task created before the dispatch integration)."),
    !task ? h("div", { class: "stack" }, banner("review", "No eligible worker was found automatically."), h("label", { class: "field", for: "assign-worker" }, "Assign to", workerSelect),
      h("div", { class: "row wrap" }, button("Assign", { class: "btn primary", onclick: () => act(`/incidents/${inc.incident_id}/assign`, false) }, "user"), retry)) : null,
    canReassign ? h("details", {}, h("summary", {}, "Reassign to another worker"), h("div", { class: "stack", style: { marginTop: "10px" } },
      h("label", { class: "field", for: "assign-worker" }, "New worker", workerSelect),
      h("div", {}, button("Reassign", { class: "btn", onclick: () => act(`/tasks/${task.task_id}/reassign`, true) }, "user")))) : null);
}
