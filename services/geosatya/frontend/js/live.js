/* Live progress: the journey of a report after it is filed, the worker's
   location (only while shared), ETA (arrival) and ETR (resolution), plus the
   supervisor's Incident Intelligence and Dispatch panels and the worker's
   location sharing. Estimates are always labelled approximate. */

import { api, sendOrQueue, session } from "./api.js";
import { DEMO_CENTER, LOCATION_BLOCKED_HELP, locate, simulatedFix, simulationOn } from "./capture.js";
import { createMap, esc, legend } from "./maps.js";
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
  ["reported_at", "Reported"], ["assigned_at", "Assigned"], ["accepted_at", "Accepted"], ["tracking_started_at", "On the way"],
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
function etaBox(eta, role) {
  if (role === "CITIZEN" && eta) {
    // Plain words; the method is one tap away.
    const text = {
      AVAILABLE: [`About ${eta.minutes_low}–${eta.minutes_high} min`, `around ${clock(eta.eta_at_low)}–${clock(eta.eta_at_high)}`],
      STALE: ["Location not updated recently", "The arrival time may be out of date."],
      WAITING_FOR_LOCATION: ["Not on the way yet", "You'll see an arrival time once they set off."],
    }[eta.state] || ["—", ""];
    return h("div", { class: `est ${eta.state === "STALE" ? "warn" : ""}` }, h("span", { class: "lbl" }, "Arrival"), h("strong", {}, text[0]),
      h("span", { class: "muted" }, text[1]),
      eta.state === "AVAILABLE" ? h("details", { class: "how" }, h("summary", {}, "How is this estimated?"),
        h("span", { class: "hint" }, eta.speed_source === "ROAD_ROUTE"
          ? `From the road route (${fmtM(eta.road_distance_m)}), without live traffic. It may change.`
          : `From the straight-line distance (${fmtM(eta.distance_m)}) with an allowance for roads. It may change.`)) : null);
  }
  const head = h("span", { class: "lbl" }, "Worker arrival (ETA)");
  if (!eta) return h("div", {}, head, h("strong", {}, "—"));
  const range = eta.minutes_low != null ? `≈ ${eta.minutes_low}–${eta.minutes_high} min` : null;
  const body = {
    AVAILABLE: [h("strong", {}, range), h("span", { class: "muted" }, `around ${clock(eta.eta_at_low)}–${clock(eta.eta_at_high)} · `
      + (eta.road_distance_m != null ? `${fmtM(eta.road_distance_m)} by road (${fmtM(eta.straight_distance_m)} straight line)` : `${fmtM(eta.distance_m)} away (straight line)`))],
    STALE: [h("strong", {}, "Location update is stale"), h("span", { class: "muted" }, range ? `Last estimate ${range}, from ${fmtAgo(new Date(Date.now() - eta.location_age_s * 1000).toISOString())}` : "")],
    WAITING_FOR_LOCATION: [h("strong", {}, "Waiting for worker location"), h("span", { class: "muted" }, "ETA unavailable until the worker shares their location.")],
    ARRIVED: [h("strong", {}, "Arrived"), h("span", { class: "muted" }, eta.arrived_at ? `at ${clock(eta.arrived_at)} (estimated from shared location)` : "Work has started at the site.")],
    NOT_APPLICABLE: [h("strong", {}, "—"), h("span", { class: "muted" }, "Not travelling to this task.")],
  }[eta.state] || [h("strong", {}, "ETA unavailable")];
  return h("div", { class: `est ${eta.state === "STALE" ? "warn" : ""}` }, head, ...body,
    eta.state === "AVAILABLE" || eta.state === "STALE" ? h("span", { class: "hint" }, eta.speed_source === "ROAD_ROUTE"
      ? "From the road route's travel time, without live traffic. Arrival may change."
      : eta.speed_source === "OBSERVED_APPROACH" ? "Approximate: based on how fast the worker has been approaching."
      : "Approximate: assumes a typical city travel speed. Arrival estimate may change.") : null,
    eta.stationary ? h("span", { class: "hint" }, "The worker hasn't moved closer for a few minutes.") : null);
}

function etrBox(etr, role) {
  const head = h("span", { class: "lbl" }, role === "CITIZEN" ? "Expected to be fixed" : "Resolution (ETR)");
  if (!etr || etr.state === "UNAVAILABLE") return h("div", { class: "est" }, head, h("strong", {}, "Estimate unavailable"), h("span", { class: "muted" }, etr?.message || ""));
  if (etr.state === "RESOLVED") {
    const a = etr.actual || {};
    return h("div", { class: "est ok" }, head, h("strong", {}, `Resolved in ${dur(a.total_min)}`),
      h("span", { class: "muted" }, `Actual time from report (${fmtTime(a.reported_at)}) to approval (${fmtTime(a.resolved_at)}).`),
      kv([a.to_assignment_min != null && ["Until assigned", dur(a.to_assignment_min)], a.travel_min != null && ["Travel", dur(a.travel_min)],
        a.work_min != null && ["On-site work", dur(a.work_min)], a.review_min != null && ["Supervisor review", dur(a.review_min)]]));
  }
  const b = etr.basis || {};
  const source = { HISTORICAL_MEDIAN: `the typical time of ${b.history_samples} similar past jobs`, WORKER_ESTIMATE: "the worker's own estimate",
    CATEGORY_BASELINE: "a standard time for this kind of job" }[b.work_source] || "a standard time";
  return h("div", { class: `est ${etr.state === "OVERDUE" ? "warn" : ""}` }, head,
    h("strong", {}, etr.state === "OVERDUE" ? "Taking longer than expected" : `By about ${clock(etr.due_at)}`),
    h("span", { class: "muted" }, etr.state === "OVERDUE" ? `It was expected by ${clock(etr.due_at)}.` : `in about ${dur(etr.remaining_min)}`),
    h("details", { class: "how" }, h("summary", {}, "How is this estimated?"),
      h("span", { class: "hint" }, `An estimate, not a promise. It adds up ${[b.travel_min ? `travel (${b.travel_min} min)` : null,
        b.work_min ? `the work (${b.work_min} min, from ${source})` : null, `a check by a supervisor (${b.review_min} min)`].filter(Boolean).join(", ")}. `
        + `Last updated ${clock(etr.updated_at)} (${label(etr.updated_on).toLowerCase()}).`),
      role !== "CITIZEN" ? (b.notes || []).map((n) => h("span", { class: "hint" }, n)) : null));
}

/* ----------------------------------------------- progress card (incident) */
const firstName = (name) => String(name || "The worker").replace(/\s*\(.*\)\s*/, "").trim() || "The worker";

/* One plain sentence saying where things stand, the way a delivery app does. */
function headline(phase, t, inc) {
  const who = firstName(inc.task?.worker_name);
  const eta = t?.eta;
  const arriving = eta?.state === "AVAILABLE" && eta.minutes_low != null ? ` · arriving in about ${eta.minutes_low}–${eta.minutes_high} min` : "";
  return {
    UNASSIGNED: ["Finding a field worker for this report", "We'll show who's coming as soon as someone is assigned."],
    AWAITING_ACCEPTANCE: [`${who} has been assigned`, "Waiting for them to confirm the job."],
    ACCEPTED: [`${who} accepted the job`, "They'll set off shortly."],
    EN_ROUTE: [`${who} is on the way${arriving}`, eta?.state === "STALE" ? "Their location hasn't updated for a few minutes." : null],
    ARRIVED: [`${who} has arrived at the spot`, "Work will start shortly."],
    IN_PROGRESS: [`${who} is fixing it now`, null],
    AWAITING_REVIEW: ["The work is done and being checked", "A supervisor confirms the photos and location before closing it."],
    RESOLVED: ["Resolved", null],
  }[phase] || [label(phase), null];
}

/* Arrival + "expected done", showing only what matters at this stage. */
function estimates(phase, t, role) {
  const boxes = [];
  if (["AWAITING_ACCEPTANCE", "ACCEPTED", "EN_ROUTE"].includes(phase)) boxes.push(etaBox(t.eta, role));
  if (["ARRIVED", "IN_PROGRESS"].includes(phase)) {
    boxes.push(h("div", { class: "est ok" }, h("span", { class: "lbl" }, "On site"), h("strong", {}, `Since ${clock(t.arrived_at || t.work_started_at)}`),
      t.work_started_at ? h("span", { class: "muted" }, `Work started ${clock(t.work_started_at)}`) : null));
  }
  boxes.push(etrBox(t.etr, role));
  return h("div", { class: "facts est-row" }, boxes);
}

/* ------------------------------------------- citizen: delivery-style tracking */
const PIN_SVG = '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 2 20h20L12 3zM12 10v4M12 17h.01"/></svg>';
const TRACK_TONE = { AWAITING_ACCEPTANCE: "wait", ACCEPTED: "wait", EN_ROUTE: "go", ARRIVED: "go", IN_PROGRESS: "go",
  AWAITING_REVIEW: "check", RESOLVED: "done" };

/* The pill under the headline: the one number the citizen cares about right now. */
function trackPill(t) {
  const e = t.eta || {};
  if (t.phase === "EN_ROUTE") {
    if (e.state === "AVAILABLE" && e.minutes_low != null) return `Arriving in ${e.minutes_low}–${e.minutes_high} mins`;
    if (e.state === "STALE") return "Location not updated recently";
    return "Setting off";
  }
  if (t.phase === "AWAITING_ACCEPTANCE" || t.phase === "ACCEPTED") return "Waiting to set off";
  if (t.phase === "ARRIVED" || t.phase === "IN_PROGRESS") return `On site since ${clock(t.arrived_at || t.work_started_at)}`;
  if (t.phase === "AWAITING_REVIEW") return "Work done · being checked";
  if (t.phase === "RESOLVED") return t.etr?.actual?.total_min != null ? `Resolved in ${dur(t.etr.actual.total_min)}` : "Resolved";
  return label(t.phase);
}

export function trackScreen(inc, ctx) {
  const head = h("div", { class: "track-head wait" }, h("h2", {}, "Loading…"));
  const note = h("div", { class: "track-note" });
  const mapEl = h("div", { class: "map track-map", role: "img", "aria-label": "Map: your report and the field worker on the way" });
  const body = h("div", { class: "track-body" });
  const timeline = h("details", { class: "track-timeline" }, h("summary", {}, "Timeline"), eventList(inc.progress));
  let map = null, mapReady = null, timer = null, fitted = false, every = 0;

  const draw = (t) => {
    const [title] = headline(t.phase, t, inc);
    const travelling = ["AWAITING_ACCEPTANCE", "ACCEPTED", "EN_ROUTE"].includes(t.phase);
    clear(head, h("h2", {}, title.replace(/ · arriving.*$/, "")),
      h("div", { class: "row" }, h("span", { class: "pill" }, trackPill(t)),
        travelling ? h("button", { class: "refresh", type: "button", "aria-label": "Refresh", onclick: (e) => {
          e.currentTarget.classList.add("spin"); load(); } }, icon("refresh", 18)) : null));
    head.className = `track-head ${TRACK_TONE[t.phase] || "wait"}`;

    const l = t.latest;
    clear(note, travelling && l ? [h("span", { class: `dot ${l.kind === "CURRENT" ? "live" : "stale"}` }, l.kind === "CURRENT" ? "Live" : "Last seen"),
      ` · updated ${fmtAgo(l.received_at)}${l.mode === "SIMULATED" ? " · simulated (demo)" : ""}`,
      t.route?.distance_m != null ? ` · ${fmtM(t.route.distance_m)} away by road` : l.distance_m != null ? ` · ${fmtM(l.distance_m)} away` : ""]
      : travelling ? "You'll see them on the map once they set off." : "");
    note.hidden = !note.textContent;

    const w = t.worker || {};
    const etr = t.etr || {};
    clear(body,
      h("div", { class: "wcard" }, h("span", { class: "wavatar" }, (w.first_name || "?").slice(0, 1).toUpperCase()),
        h("div", { class: "stack tight grow" }, h("strong", {}, w.first_name || "Field worker"),
          h("span", { class: "muted" }, `${w.role || "Field worker"} · ${w.resolved_jobs ? `${w.resolved_jobs} civic job${w.resolved_jobs === 1 ? "" : "s"} resolved` : "no jobs resolved yet"}`))),
      etr.state === "ESTIMATED" || etr.state === "OVERDUE"
        ? h("div", { class: "track-row" }, icon("history", 18), h("span", {}, etr.state === "OVERDUE" ? "Taking longer than expected" : `Expected to be fixed by about ${clock(etr.due_at)}`),
          h("details", { class: "how" }, h("summary", {}, "How?"), h("span", { class: "hint" }, "An estimate from the work involved and a supervisor's check; not a promise.")))
        : etr.state === "RESOLVED" ? h("div", { class: "track-row ok" }, icon("check", 18), h("span", {}, `Resolved ${fmtTime(etr.actual?.resolved_at)}`)) : null,
      journey({ ...inc.progress, ...pick(t) }), timeline);

    // Map: your report (pin), the worker (round marker, pulsing while live) and the road route between them.
    mapReady ||= createMap(mapEl, { center: [t.target.latitude, t.target.longitude], zoom: 16 }).then((m) => { map = m; return m; });
    mapReady.then((m) => {
      const target = [t.target.latitude, t.target.longitude];
      m.html("t", target, `<span class="tpin">${PIN_SVG}</span>`, "Your report", null, 40);
      const pts = [target];
      if (l && t.phase !== "RESOLVED" && t.phase !== "AWAITING_REVIEW") {
        const here = [l.latitude, l.longitude];
        m.html("w", here, `<span class="tworker${l.kind === "CURRENT" ? " live" : ""}">${esc((w.first_name || "?").slice(0, 1).toUpperCase())}</span>`,
          `${w.first_name || "Worker"} · ${l.kind === "CURRENT" ? "live" : "last seen"} ${fmtAgo(l.received_at)}`, null, 44);
        if (travelling && t.route?.geometry?.length) m.line("route", t.route.geometry, "#2563EB", false, 5);
        else if (travelling) m.line("route", [here, target], "#64748B", true);
        else m.remove("route");
        pts.push(here);
      } else { m.remove("w"); m.remove("route"); }
      if (!fitted || travelling) { m.fit(pts); fitted = true; }
    });
    // Faster while the worker is actually moving towards you.
    const want = travelling && l?.kind === "CURRENT" ? 5000 : 15000;
    if (want !== every) { clearInterval(timer); every = want; if (["ASSIGNED", "IN_PROGRESS"].includes(inc.task.status)) timer = setInterval(load, every); }
  };
  const load = async () => {
    if (document.visibilityState === "hidden") return;
    try { draw(await api(`/incidents/${inc.incident_id}/tracking`)); }
    catch (err) { clear(note, err.code === "NETWORK" ? "Can't reach the server right now; showing nothing rather than an old position." : err.message); note.hidden = false; }
  };
  load();
  ctx.onCleanup(() => { clearInterval(timer); map?.destroy(); });
  return h("section", { class: "card flush track" }, head, note, mapEl, body);
}

export function progressCard(inc, ctx) {
  const role = session.me.role;
  if (role === "CITIZEN" && inc.task) return trackScreen(inc, ctx);
  const rework = inc.task?.rework_reason && ["ASSIGNED", "IN_PROGRESS"].includes(inc.status)
    ? banner("review", h("strong", {}, "Sent back for rework: "), inc.task.rework_reason) : null;
  const timeline = h("details", { open: role === "CITIZEN" }, h("summary", {}, "Timeline"), eventList(inc.progress));
  if (!inc.task) {
    const [title, sub] = headline("UNASSIGNED", null, inc);
    return card({ class: "card status-card" }, h("h2", { class: "headline" }, title), h("p", { class: "muted" }, sub),
      journey(inc.progress), role !== "CITIZEN" ? banner("info", "No field worker assigned yet: see the Dispatch & AI tab.") : null, timeline);
  }
  const body = h("div", { class: "stack" }, h("div", { class: "row" }, h("span", { class: "spinner" }), "Loading live status…"));
  const mapEl = h("div", { class: "map short", role: "img", "aria-label": "Map: incident location and the worker's last shared position" });
  const mapNote = h("p", { class: "hint" });
  let map = null, timer = null, mapReady = null;
  const active = ["ASSIGNED", "IN_PROGRESS"].includes(inc.task.status);

  const draw = (t) => {
    const latest = t.latest;
    const [title, sub] = headline(t.phase, t, inc);
    // The worker's position only matters while they travel; once on site it is noise.
    const travelling = latest && ["AWAITING_ACCEPTANCE", "ACCEPTED", "EN_ROUTE"].includes(t.phase);
    clear(body,
      h("h2", { class: "headline" }, title), sub ? h("p", { class: "muted" }, sub) : null,
      rework, journey({ ...inc.progress, ...pick(t) }), estimates(t.phase, t, role),
      travelling ? trackingLine(t, role) : null);
    mapEl.hidden = !travelling;
    clear(mapNote, travelling && t.route?.geometry?.length ? "Blue line: road route from the worker's live position (no live traffic)." : "");
    if (travelling) {
      mapReady ||= createMap(mapEl, { center: [t.target.latitude, t.target.longitude], zoom: 15 }).then((m) => { map = m; return m; });
      mapReady.then((m) => {
        const target = [t.target.latitude, t.target.longitude], w = [latest.latitude, latest.longitude];
        m.marker("t", "target", target, "Incident location");
        m.marker("w", latest.mode === "SIMULATED" ? "simulated" : "worker", w,
          `${latest.kind === "CURRENT" ? "Worker now" : "Worker last seen"} · ${fmtAgo(latest.received_at)}`);
        (t.history || []).forEach((p, i) => m.circle(`h${i}`, [p.latitude, p.longitude], 4, "worker"));
        if (t.route?.geometry?.length) m.line("route", t.route.geometry, "#2563EB");
        else m.remove("route");
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
  return card({ class: "card status-card" }, body, mapEl, mapNote, timeline,
    active ? h("span", { class: "hint" }, "Updates automatically.") : null);
}

const pick = (t) => ({ accepted_at: t.accepted_at, tracking_started_at: t.tracking_started_at, arrived_at: t.arrived_at, work_started_at: t.work_started_at });

/* Events that actually happened, from persisted timestamps (server-built). */
export function eventList(progress) {
  const evs = progress?.events || [];
  if (!evs.length) return null;
  return h("ol", { class: "events" }, evs.map((e) => h("li", { class: `ev ${e.event.toLowerCase()}` },
    h("span", { class: "muted" }, fmtTime(e.time)), h("span", {}, h("strong", {}, e.text), e.detail ? h("span", { class: "muted" }, ` · ${e.detail}`) : null))));
}

function trackingLine(t, role) {
  const l = t.latest;
  const text = {
    LIVE: l ? `Live location · updated ${fmtAgo(l.received_at)}${role === "CITIZEN" ? "" : ` · GPS ±${Math.round(l.accuracy_m || 0)} m`}` : "Location sharing on",
    STALE: l ? `Last seen ${fmtAgo(l.received_at)}. Their phone may be offline; the map shows where they were then.` : "No recent location.",
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
export function locationSharer(t, ctx, opts = {}) {
  const min = Math.max(10, session.config.tracking?.min_interval_s || 10) * 1000;
  const status = h("div", { class: "stack tight", "aria-live": "polite" });
  let watchId = null, timer = null, lastSent = 0, simPos = null, on = false;
  const target = [t.target_latitude, t.target_longitude];

  const send = async (fix) => {
    if (Date.now() - lastSent < min) return;
    lastSent = Date.now();
    try {
      // Offline, only the newest position is kept (with its real device time); older ones are useless for live tracking.
      const r = await sendOrQueue(`/tasks/${t.task_id}/location`, { kind: "location", taskId: t.task_id, replaceKey: `loc:${t.task_id}`,
        json: { latitude: fix.latitude, longitude: fix.longitude, accuracy_m: fix.accuracy_m, observed_at: fix.observed_at, mode: fix.mode } });
      if (r.queued) show("review", `No connection: your latest position (${new Date().toLocaleTimeString()}) is saved on this phone and will be sent when you're back online. The citizen sees your last sent position as "last seen".`);
      else if (r.stored) show("pass", `Shared at ${new Date().toLocaleTimeString()} · ${fmtM(r.distance_m)} from the spot${r.arrived ? " · arrived" : ""}${fix.mode === "SIMULATED" ? " (simulated)" : ""}`);
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
      (e) => show("fail", e.code === 1 ? LOCATION_BLOCKED_HELP : "Your device couldn't get a position. Sharing will continue when it can."),
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
    : button(simulationOn() ? "Start journey (simulated travel)" : "Start journey", { class: "btn primary", onclick: start }, "navigate"),
    ...(opts.extra || []));
  draw();
  clear(status, h("p", { class: "muted" }, "Starting the journey shares your location, so the citizen sees when you'll arrive. Sharing stops when you submit the completion."));
  ctx.onCleanup(() => { if (watchId != null) navigator.geolocation.clearWatch(watchId); clearInterval(timer); });
  return card({ class: "card next-step" }, opts.step ? h("span", { class: "lbl" }, opts.step) : null, h("h2", {}, "Head to the spot"), btn, status);
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
  const hasEvidence = (inc.completions || []).length > 0;
  const timeoutMin = session.config.tracking?.acceptance_timeout_min || 15;
  const accepted = !!(inc.progress?.accepted_at || inc.progress?.tracking_started_at || inc.progress?.work_started_at);
  const overdue = task && task.status === "ASSIGNED" && !accepted
    && (Date.now() - new Date(task.assigned_at).getTime()) / 60000 > timeoutMin;
  const release = (kind, title, description) => async () => {
    const reason = await reasonDialog({ title, description, confirmText: title, tone: kind === "CANCELLED" ? "danger" : "primary" });
    if (reason == null) return;
    try { const r = await api(`/tasks/${task.task_id}/release`, { method: "POST", json: { kind, reason } });
      toast(r.task ? `Re-dispatched to ${r.task.worker_name}` : "No other worker available; waiting for assignment", r.task ? "pass" : "info"); ctx.rerender(); }
    catch (err) { toast(err.message, "fail"); }
  };
  const releaseActions = canReassign && !hasEvidence ? h("div", { class: "row wrap" },
    overdue ? button(`Re-dispatch (not accepted in ${timeoutMin} min)`, { class: "btn small primary",
      onclick: release("ACCEPTANCE_TIMEOUT", "Re-dispatch", "The current worker didn't accept in time. Dispatch runs again without them.") }, "refresh") : null,
    button("Cancel assignment", { class: "btn small", onclick: release("CANCELLED", "Cancel assignment",
      "The worker loses this job, tracking stops and its points are deleted. Dispatch runs again without them.") }, "x")) : null;
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
    task ? kv([["Acceptance", accepted ? `Accepted ${fmtTime(inc.progress.accepted_at || inc.progress.tracking_started_at || inc.progress.work_started_at)}` : overdue ? "Overdue: not accepted" : "Waiting for the worker"]]) : null,
    releaseActions,
    canReassign ? h("details", {}, h("summary", {}, "Reassign to another worker"), h("div", { class: "stack", style: { marginTop: "10px" } },
      h("label", { class: "field", for: "assign-worker" }, "New worker", workerSelect),
      h("div", {}, button("Reassign", { class: "btn", onclick: () => act(`/tasks/${task.task_id}/reassign`, true) }, "user")))) : null);
}
