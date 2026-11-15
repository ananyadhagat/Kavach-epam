/* Reporting without photographs: category, description and location.
   - Citizens report public civic issues (authority suggested and routed).
   - Members of an event or organization report incidents inside it.
   The location is captured and checked by GeoSatya exactly as before. */

import { api, firstUser, session } from "../api.js";
import { newKey } from "../outbox.js";
import { banner, button, card, chip, clear, h, icon, pageHead, toast } from "../ui.js";
import { enterAs } from "./access.js";
import { field, reportLocation, select } from "./widgets.js";

const ROAD_CATS = ["road_damage", "safety_hazard", "streetlight", "infrastructure"];

export async function renderPublicReportGate({ main }) {
  if (session.me?.role === "CITIZEN") { location.hash = "#/report"; return; }
  const demo = firstUser("CITIZEN");
  clear(main, h("section", { class: "page-hero" }, h("div", { class: "wrap", style: { position: "relative", zIndex: 1 } },
    h("span", { class: "eyebrow" }, "Report an issue"), h("h1", { style: { marginTop: "10px" } }, "Report a civic issue in under a minute"),
    h("p", {}, "Potholes, garbage, water leaks, drains, streetlights and other public problems. Your location is attached; no photo needed."))),
  h("div", { class: "wrap pub-body" },
    card({}, h("h2", {}, "Continue as a citizen"),
      h("p", { class: "muted" }, "Mobile OTP sign-in will come later. During development you report as a demo citizen."),
      h("div", { class: "row wrap" }, demo ? button(`Continue as ${demo.display_name}`, { class: "btn primary big", onclick: () => enterAs(demo.user_id, "#/report") }, "user") : null,
        h("a", { class: "btn big", href: "#/enter" }, "Choose another identity")))));
}

export async function renderKavachReport(ctx) {
  const { main, onCleanup } = ctx;
  const ws = session.ctx?.workspace;
  const inWorkspace = session.me.role !== "CITIZEN";
  if (inWorkspace && !ws) {
    clear(main, card({}, h("h2", {}, "Reporting is part of a workspace"), h("p", { class: "muted" }, "Open an event or join an organization to report incidents inside it.")));
    return;
  }
  const cat = session.catalog ||= await api("/kavach/catalog");
  const allowed = inWorkspace ? new Set(ws.settings?.categories || []) : null;
  const cats = cat.categories.filter((c) => (inWorkspace ? allowed.has(c.id) : c.scope !== "event"));
  const state = { category: cats[0]?.id || null };

  const title = h("input", { type: "text", id: "r-title", required: true, minlength: 3, maxlength: 120 });
  const desc = h("textarea", { id: "r-desc", required: true, minlength: 10, maxlength: 2000, rows: 4 });
  const landmark = h("input", { type: "text", id: "r-land", maxlength: 200, placeholder: "Nearby shop, gate number, pole number…" });
  const road = select("r-road", cat.road_types.map((r) => [r.id, r.label]), "UNKNOWN");
  const roadField = field("What kind of road?", road, "Helps route it to the city, a state highway or a national highway authority.");
  const zone = ws?.zones?.length ? select("r-zone", [["", "No specific zone"], ...ws.zones.map((z) => [z.zone_id, z.name])], "") : null;
  const authority = h("div", { "aria-live": "polite" });
  const err = h("p", { class: "field-error", "aria-live": "polite" });
  const loc = reportLocation();
  const grid = h("div", { class: "cats" });
  const submit = h("button", { class: "btn primary big", type: "submit" }, icon("check", 18), "Submit report");

  const applyCategory = () => {
    const c = cats.find((x) => x.id === state.category);
    title.placeholder = c?.title_placeholder || "Short summary";
    desc.placeholder = c?.description_placeholder || "Describe what you see";
    roadField.hidden = inWorkspace || !ROAD_CATS.includes(state.category);
    grid.querySelectorAll(".cat").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.id === state.category)));
    suggest();
  };
  let pending = null;
  const suggest = () => {
    if (inWorkspace) return;
    clearTimeout(pending);
    pending = setTimeout(async () => {
      const p = loc.point();
      if (!p || !state.category) { clear(authority); return; }
      try {
        const s = await api(`/kavach/authorities/suggest?latitude=${p[0]}&longitude=${p[1]}&category=${encodeURIComponent(state.category)}&road_type=${road.value}`);
        clear(authority, h("div", { class: "authority-card" }, h("span", { class: "ico" }, icon("building", 20)), h("div", { class: "stack tight" },
          h("span", { class: "lbl" }, "Suggested authority"), h("strong", {}, s.authority?.name || "Kavach civic team (manual review)"),
          h("span", { class: "hint" }, s.reason), s.authority?.data_note ? h("span", { class: "hint" }, s.authority.data_note) : null,
          s.authority && !s.authority.on_kavach ? h("span", { class: "hint" }, "Kavach has no direct connection to this authority; a supervisor forwards it.") : null)));
      } catch { clear(authority); }
    }, 350);
  };
  road.addEventListener("change", suggest);
  // Re-check the suggestion when the location settles.
  let lastPoint = null;
  const watch = setInterval(() => { const p = JSON.stringify(loc.point()); if (p !== lastPoint) { lastPoint = p; suggest(); } }, 800);
  onCleanup(() => clearInterval(watch));

  clear(grid, cats.map((c) => h("button", { class: "cat", type: "button", "data-id": c.id, "aria-pressed": "false",
    onclick: () => { state.category = c.id; applyCategory(); } }, h("span", { class: "ico" }, icon(c.icon, 20)), c.label)));

  const key = newKey();
  clear(main,
    pageHead({ crumbs: [["Home", "#/"]], title: inWorkspace ? "Report an incident" : "Report an issue",
      subtitle: inWorkspace ? `Inside ${ws.name}. The best available team member is dispatched automatically.`
        : "Tell us what and where. No photo needed: your location does the work." }),
    h("form", { class: "stack", style: { gap: "22px" }, onsubmit: async (e) => {
      e.preventDefault(); err.textContent = "";
      if (!state.category) { err.textContent = "Choose a category."; return; }
      if (!loc.ready()) { err.textContent = "We need a location: allow location access, or tap the map to place a pin."; return; }
      submit.disabled = true;
      const body = { category: state.category, title: title.value, description: desc.value, landmark: landmark.value || null, ...loc.value() };
      if (!inWorkspace && !roadField.hidden) body.road_type = road.value;
      if (zone?.value) body.zone_id = zone.value;
      try {
        const path = inWorkspace ? `/kavach/workspaces/${ws.workspace_id}/incidents` : "/kavach/public/reports";
        const res = await api(path, { method: "POST", json: body, headers: { "Idempotency-Key": key } });
        done(main, res, inWorkspace);
      } catch (ex) { err.textContent = ex.message; submit.disabled = false; toast(ex.message, "fail"); }
    } },
    card({}, h("h2", {}, "1 · What is it?"), grid),
    card({}, h("h2", {}, "2 · Tell us more"), h("div", { class: "form-grid" }, field("Short title", title, null, "full"), field("What's happening?", desc, null, "full"),
      field("Landmark", landmark, "Optional"), zone ? field("Zone", zone) : roadField)),
    card({}, h("h2", {}, "3 · Where is it?"), loc.el, authority),
    banner("info", inWorkspace ? "Only people in this workspace can see this incident." : "Photos aren't collected on the public portal. Your location and description are enough to dispatch a worker."),
    err, h("div", { class: "row wrap" }, submit)));
  applyCategory();
  await loc.mount(ws?.center ? [ws.center.latitude, ws.center.longitude] : null);
  onCleanup(() => loc.destroy());
}

function done(main, inc, inWorkspace) {
  const a = inc.authority?.authority;
  const copy = button("Copy", { class: "btn small", onclick: async () => {
    try { await navigator.clipboard.writeText(inc.incident_id); toast("Reference copied", "pass"); } catch { toast("Copy it from the screen", "info"); }
  } }, "copy");
  clear(main, card({ class: "card", style: { alignItems: "center", textAlign: "center", padding: "40px 22px", gap: "18px" } },
    h("span", { class: "ico", style: { width: "64px", height: "64px", borderRadius: "50%", background: "var(--grad)", color: "#fff" } }, icon("check", 32)),
    h("h1", {}, inWorkspace ? "Incident reported" : "Thank you, your report is in"),
    h("div", { class: "stack tight", style: { alignItems: "center" } }, h("span", { class: "lbl" }, "Reference number"),
      h("div", { class: "row" }, h("span", { class: "code-big" }, inc.incident_id), copy)),
    inc.task ? banner("pass", "A worker has been assigned. You can follow them live.") : banner("review", "No worker is free right now; a supervisor will assign one."),
    !inWorkspace ? h("div", { class: "authority-card", style: { textAlign: "left", maxWidth: "560px" } }, h("span", { class: "ico" }, icon("building", 20)),
      h("div", { class: "stack tight" }, h("span", { class: "lbl" }, "Responsible authority (suggested)"), h("strong", {}, a?.name || "Kavach civic team"),
        h("span", { class: "hint" }, a?.on_kavach ? "This authority works on Kavach, so your report went straight to their team." : "Not sent outside Kavach automatically. A supervisor reviews and forwards it if needed."))) : null,
    h("div", { class: "row wrap center" }, h("a", { class: "btn primary big", href: `#/incidents/${inc.incident_id}` }, icon("live", 18), "Track live"),
      !inWorkspace ? h("a", { class: "btn big", href: `#/track/${inc.incident_id}` }, "Public status page") : null,
      h("a", { class: "btn big", href: "#/" }, "Done")),
    inc.location?.flags?.length ? h("div", { class: "row wrap center" }, inc.location.flags.map((f) => chip("REVIEW_REQUIRED", f.replace(/_/g, " ").toLowerCase()))) : null));
}
