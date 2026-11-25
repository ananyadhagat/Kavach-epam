/* Worker search and allocation (supervisor). Visual direction: the "Finding people nearby" glass
   radar from the team's Figma file. Everything shown is real: the candidates come from
   GET /incidents/{id}/dispatch/candidates, which runs the Dispatch agent's own rules (skills,
   availability, capacity, fresh location within the radius; then 70% distance / 30% workload)
   without assigning anyone. Each blip sits at the worker's real bearing and distance from the
   incident. Assigning still goes through the existing endpoints and their server-side checks. */

import { api } from "../api.js";
import { button, clear, fmtAgo, h, icon, label, reasonDialog, toast } from "../ui.js";
import { initials } from "./brand.js";

const MIN_SCAN_MS = 1100;          // the sweep runs at least this long, so the result never flashes
const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function bearingKm(from, to) {
  const R = 6371, toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(to[0] - from[0]), dLon = toRad(to[1] - from[1]);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(from[0])) * Math.cos(toRad(to[0])) * Math.sin(dLon / 2) ** 2;
  const km = 2 * R * Math.asin(Math.sqrt(a));
  const y = Math.sin(dLon) * Math.cos(toRad(to[0]));
  const x = Math.cos(toRad(from[0])) * Math.sin(toRad(to[0])) - Math.sin(toRad(from[0])) * Math.cos(toRad(to[0])) * Math.cos(dLon);
  return { km, bearing: Math.atan2(y, x) };
}

const ageText = (s) => (s == null ? "No location shared" : `Location ${fmtAgo(new Date(Date.now() - s * 1000).toISOString())}`);

/* The radar: rings, a sweep and one blip per worker with a usable location. */
function radar(data, onPick) {
  const blips = h("div", { class: "radar-blips" });
  const el = h("div", { class: "radar", role: "img", "aria-label": "Workers around the incident" },
    h("span", { class: "radar-ring r1" }), h("span", { class: "radar-ring r2" }), h("span", { class: "radar-ring r3" }),
    h("span", { class: "radar-cross" }), h("span", { class: "radar-sweep" }),
    h("span", { class: "radar-core", title: "Incident location" }, icon("pin", 20)), blips);
  const place = (d) => {
    clear(blips);
    if (!d) return;
    const maxKm = Math.max(0.5, d.max_radius_km || 2);
    for (const w of d.workers) {
      if (w.latitude == null || w.longitude == null) continue;
      const { km, bearing } = bearingKm([d.latitude, d.longitude], [w.latitude, w.longitude]);
      const r = Math.min(1, km / maxKm) * 46;             // % of the radar, the outer ring = dispatch radius
      const x = 50 + r * Math.sin(bearing), y = 50 - r * Math.cos(bearing);
      blips.append(h("button", { type: "button", class: `radar-blip${w.eligible ? " ok" : ""}${w.is_current ? " current" : ""}`, "data-worker": w.worker_id,
        style: { left: `${x}%`, top: `${y}%` }, "aria-label": `${w.name}, ${km.toFixed(2)} km`, title: `${w.name} · ${km.toFixed(2)} km`,
        onclick: () => onPick(w.worker_id) }, initials(w.name)));
    }
  };
  return { el, place };
}

function workerCard(w, d, { selected, onSelect, onAssign, mode }) {
  const need = d.required_skills || [];
  const skills = (w.skills || []).map((s) => h("span", { class: `wc-skill${need.includes(s) ? " need" : ""}` }, label(s)));
  const status = w.is_current ? ["current", "Assigned now"] : w.eligible ? ["ok", `Rank ${w.rank}`] : !w.available ? ["off", "Unavailable"] : ["no", "Not eligible"];
  return h("article", { class: `wcard2 glass${selected ? " selected" : ""}${w.eligible ? " eligible" : ""}`, "data-worker": w.worker_id, tabindex: "0",
    onclick: () => onSelect(w.worker_id), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(w.worker_id); } } },
  h("div", { class: "wc-top" },
    h("span", { class: "wc-av" }, initials(w.name), h("i", { class: `wc-dot ${w.available ? "on" : "off"}` })),
    h("div", { class: "wc-id" }, h("strong", {}, w.name), h("small", {}, ageText(w.location_age_s), w.location_age_s != null && !w.location_fresh ? " · too old for dispatch" : "")),
    h("span", { class: `wc-badge ${status[0]}` }, status[1])),
  h("dl", { class: "wc-facts" },
    h("div", {}, h("dt", {}, "Distance"), h("dd", {}, w.distance_km != null ? `${w.distance_km} km` : "—")),
    h("div", {}, h("dt", {}, "Workload"), h("dd", {}, `${w.active_tasks}/${w.max_active_tasks}`, h("span", { class: "wc-load" }, h("i", { style: { width: `${Math.min(100, (100 * w.active_tasks) / Math.max(1, w.max_active_tasks))}%` } })))),
    h("div", {}, h("dt", {}, "Skills"), h("dd", {}, need.length ? (w.skills_match ? "Match" : "Missing") : "Any"))),
  skills.length ? h("div", { class: "wc-skills" }, skills) : null,
  !w.eligible && w.reasons?.length ? h("p", { class: "wc-why" }, icon("info", 14), w.reasons.join(" · ")) : null,
  selected && w.eligible && !w.is_current ? h("div", { class: "wc-act" },
    button(mode === "reassign" ? `Reassign to ${w.name.split(" ")[0]}` : `Assign ${w.name.split(" ")[0]}`, { class: "btn primary", onclick: (e) => { e.stopPropagation(); onAssign(w); } }, "user"))
    : null);
}

/* The worker search panel for one incident. `mode` is "assign" (no task yet) or "reassign". */
export function workerSearch(inc, ctx, { mode = "assign", autoStart = true } = {}) {
  const state = { data: null, selected: null, filter: "eligible" };
  const status = h("p", { class: "ws-status", "aria-live": "polite" });
  const list = h("div", { class: "ws-list" });
  const rad = radar(null, (id) => select(id));
  const tabs = h("div", { class: "seg ws-seg", role: "tablist" });
  const shell = h("section", { class: "ws glass", "aria-label": "Find a worker" },
    h("div", { class: "ws-head" },
      h("div", {}, h("p", { class: "aur-eyebrow" }, "Worker allocation"), h("h2", {}, mode === "reassign" ? "Find another worker" : "Find a worker nearby")),
      h("div", { class: "row wrap", style: { gap: "8px" } },
        button("Scan again", { class: "btn small", onclick: () => scan() }, "refresh"),
        mode === "assign" ? button("Automatic dispatch", { class: "btn small primary", onclick: auto }, "route") : null)),
    h("div", { class: "ws-body" }, h("div", { class: "ws-radar" }, rad.el, status), h("div", { class: "ws-side" }, tabs, list)));

  function drawTabs() {
    const d = state.data;
    const n = d ? { eligible: d.eligible, all: d.total } : { eligible: 0, all: 0 };
    clear(tabs, [["eligible", `Eligible (${n.eligible})`], ["all", `All workers (${n.all})`]].map(([k, t]) =>
      h("a", { href: "#", role: "tab", "aria-selected": String(state.filter === k), onclick: (e) => { e.preventDefault(); state.filter = k; draw(); } }, t)));
  }
  function draw() {
    drawTabs();
    const d = state.data;
    if (!d) return;
    const shown = d.workers.filter((w) => state.filter === "all" || w.eligible || w.is_current);
    clear(list, shown.length ? shown.map((w, i) => {
      const c = workerCard(w, d, { selected: state.selected === w.worker_id, onSelect: select, onAssign: assign, mode });
      c.style.setProperty("--i", i);
      return c;
    }) : h("div", { class: "ws-empty" }, icon("users", 22), h("p", {}, d.total ? "No worker meets every rule right now. Open “All workers” to see why, or run automatic dispatch later."
      : "No field workers in this workspace yet. Workers appear after they register with the worker access code.")));
    rad.el.querySelectorAll(".radar-blip").forEach((b) => b.classList.toggle("sel", b.dataset.worker === state.selected));
  }
  function select(id) {
    state.selected = state.selected === id ? null : id;
    draw();
    list.querySelector(`[data-worker="${CSS.escape(id)}"]`)?.scrollIntoView({ block: "nearest", behavior: reduceMotion() ? "auto" : "smooth" });
  }
  async function scan() {
    shell.classList.add("scanning");
    status.textContent = "Scanning the area around the incident…";
    const started = performance.now();
    try {
      const data = await api(`/incidents/${inc.incident_id}/dispatch/candidates`);
      const wait = reduceMotion() ? 0 : Math.max(0, MIN_SCAN_MS - (performance.now() - started));
      await new Promise((r) => setTimeout(r, wait));
      state.data = data;
      if (!data.workers.some((w) => w.worker_id === state.selected)) state.selected = data.workers.find((w) => w.eligible && !w.is_current)?.worker_id || null;
      rad.place(data);
      const need = data.required_skills?.length ? ` · needs ${data.required_skills.map(label).join(", ")}` : "";
      status.textContent = `${data.eligible} of ${data.total} worker${data.total === 1 ? "" : "s"} eligible within ${data.max_radius_km} km${need}`;
      draw();
    } catch (err) { status.textContent = err.message; toast(err.message, "fail"); }
    finally { shell.classList.remove("scanning"); }
  }
  async function assign(w) {
    const reason = await reasonDialog({
      title: mode === "reassign" ? `Reassign to ${w.name}` : `Assign ${w.name}`, confirmText: mode === "reassign" ? "Reassign" : "Assign",
      description: mode === "reassign" ? "Tracking of the current worker stops and their shared locations for this task are deleted." : `${w.name} is rank ${w.rank}, ${w.distance_km} km away.`,
      required: mode === "reassign" });
    if (reason == null) return;
    const path = mode === "reassign" ? `/tasks/${inc.task.task_id}/reassign` : `/incidents/${inc.incident_id}/assign`;
    try { await api(path, { method: "POST", json: { worker_id: w.worker_id, reason } }); toast(`Assigned to ${w.name}`, "pass"); ctx.rerender(); }
    catch (err) { toast(err.message, "fail"); scan(); }
  }
  async function auto() {
    try { const r = await api(`/incidents/${inc.incident_id}/dispatch/retry`, { method: "POST" });
      toast(r.task ? `Dispatch assigned ${r.task.worker_name}` : "Still no eligible worker", r.task ? "pass" : "info"); ctx.rerender(); }
    catch (err) { toast(err.message, "fail"); }
  }
  drawTabs();
  status.textContent = "Press Scan to look for workers.";
  if (autoStart) scan();
  return shell;
}


/* The search in a full-screen glass dialog (the dispatch card is too narrow for the radar).
   Closing it (Esc, the close button or the backdrop) ends the search; nothing is assigned unless confirmed. */
export function openWorkerSearch(inc, ctx, opts = {}) {
  const dlg = h("dialog", { class: "ws-dialog", "aria-label": "Find a worker" });
  const close = () => dlg.close();
  const panel = workerSearch(inc, { ...ctx, rerender: () => { close(); ctx.rerender(); } }, opts);
  panel.querySelector(".ws-head")?.append(button("Close", { class: "btn small ghost ws-close", onclick: close }, "x"));
  dlg.append(panel);
  dlg.addEventListener("click", (e) => { if (e.target === dlg) close(); });
  dlg.addEventListener("close", () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
}

/* The button that opens it, for the dispatch card. */
export const findWorkerButton = (inc, ctx, mode) => button(mode === "reassign" ? "Find another worker" : "Find a worker nearby",
  { class: mode === "reassign" ? "btn" : "btn primary", onclick: () => openWorkerSearch(inc, ctx, { mode }) }, "search");
