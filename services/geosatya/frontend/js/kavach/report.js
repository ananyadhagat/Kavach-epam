/* Reporting.
   - Citizens: camera-first complaint with automatic GPS (./complaint.js).
   - Members of an event or organization report incidents inside it
     (category, description and location; checked by GeoSatya as before). */

import { api, session } from "../api.js";
import { newKey } from "../outbox.js";
import { banner, button, card, chip, clear, h, icon, pageHead, toast } from "../ui.js";
import { renderCitizenReport } from "./complaint.js";
import { field, reportLocation, select } from "./widgets.js";
import { infoOf, selectCategory, selectedCategory } from "./categories.js";

const ROAD_CATS = ["road_damage", "safety_hazard", "streetlight", "infrastructure", "highway"];

export async function renderPublicReportGate({ main }) {
  if (session.me?.role === "CITIZEN") { location.hash = "#/report"; return; }
  clear(main, h("section", { class: "page-hero" }, h("div", { class: "wrap", style: { position: "relative", zIndex: 1 } },
    h("span", { class: "eyebrow" }, "Report an issue"), h("h1", { style: { marginTop: "10px" } }, "Report a civic issue in under a minute"),
    h("p", {}, "Choose what it is, take a photo and add a line. Your phone's GPS is recorded with the photo."))),
  h("div", { class: "wrap pub-body" },
    card({ style: { maxWidth: "620px" } }, h("h2", {}, session.me ? "Complaints are sent from a citizen account" : "Sign in to report"),
      h("p", { class: "muted" }, session.me ? "You are signed in with a staff account. Sign out and use a citizen account to report."
        : "A free citizen account lets you track your complaints and get updates."),
      session.me ? null : h("div", { class: "row wrap" },
        h("a", { class: "btn primary big", href: "#/signup/citizen?next=report" }, icon("user", 18), "Register as a Citizen"),
        h("a", { class: "btn big", href: "#/signin?next=report" }, "Sign in")))));
}

export async function renderKavachReport(ctx) {
  const { main, onCleanup } = ctx;
  if (session.me.role === "CITIZEN") return renderCitizenReport(ctx);
  const ws = session.ctx?.workspace;
  const inWorkspace = true;
  if (inWorkspace && !ws) {
    clear(main, card({}, h("h2", {}, "Reporting is part of a workspace"), h("p", { class: "muted" }, "Open an event or join an organization to report incidents inside it.")));
    return;
  }
  const cat = session.catalog ||= await api("/kavach/catalog");
  const allowed = inWorkspace ? new Set(ws.settings?.categories || []) : null;
  const cats = cat.categories.filter((c) => (inWorkspace ? allowed.has(c.id) : c.scope !== "event"));
  // The category picked on the home page (or earlier in this form) stays selected throughout.
  const remembered = selectedCategory();
  const state = { category: cats.some((c) => c.id === remembered) ? remembered : null };

  const title = h("input", { type: "text", id: "r-title", minlength: 3, maxlength: 120, placeholder: "Optional: a short title" });
  const desc = h("textarea", { id: "r-desc", required: true, minlength: 10, maxlength: 2000, rows: 4 });
  const picked = h("div", { class: "picked", "aria-live": "polite" });
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
    desc.placeholder = c?.description_placeholder || "Describe what you see";
    clear(picked, c ? h("span", { class: "picked-chip" }, icon(c.icon || "dots", 16), (infoOf(c.id)?.name || c.label)) : h("span", { class: "muted" }, "No category chosen yet"));
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
    onclick: () => { state.category = c.id; if (!inWorkspace) selectCategory(c.id); applyCategory(); } },
    h("span", { class: "ico" }, icon(c.icon, 20)), (!inWorkspace && infoOf(c.id)?.name) || c.label)));

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
      const label = (cats.find((x) => x.id === state.category)?.label || "Complaint");
      const text = desc.value.trim();
      const autoTitle = `${(!inWorkspace && infoOf(state.category)?.name) || label}: ${text.slice(0, 60)}${text.length > 60 ? "…" : ""}`;
      const body = { category: state.category, title: (title.value.trim().length >= 3 ? title.value.trim() : autoTitle).slice(0, 120), description: desc.value, landmark: landmark.value || null, ...loc.value() };
      if (!inWorkspace && !roadField.hidden) body.road_type = road.value;
      if (zone?.value) body.zone_id = zone.value;
      try {
        const path = inWorkspace ? `/kavach/workspaces/${ws.workspace_id}/incidents` : "/kavach/public/reports";
        const res = await api(path, { method: "POST", json: body, headers: { "Idempotency-Key": key } });
        if (!inWorkspace) selectCategory(null);        // the next report starts fresh
        done(main, res, inWorkspace);
      } catch (ex) { err.textContent = ex.message; submit.disabled = false; toast(ex.message, "fail"); }
    } },
    card({}, h("h2", {}, "1 · What is it?"), grid),
    card({}, h("h2", {}, "2 · Tell us more"), picked, h("div", { class: "form-grid" }, field("What's happening?", desc, "One or two lines is enough.", "full"),
      field("Landmark", landmark, "Optional"), zone ? field("Zone", zone) : roadField),
      h("details", {}, h("summary", {}, "Add a title (optional)"), h("div", { style: { marginTop: "10px" } }, field("Title", title)))),
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
