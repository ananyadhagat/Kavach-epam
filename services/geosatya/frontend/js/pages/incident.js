/* My Reports (list) and the incident page (citizen, worker and supervisor views). */

import { api, session } from "../api.js";
import { categoryIcon, dots, flagChips, lifecycle, locationSource, photo } from "../components.js";
import { createMap, legend, mapProviderName } from "../maps.js";
import { banner, button, card, chip, clear, demoTag, emptyState, fmtAgo, fmtCoord, fmtTime, h, icon, kv, label, pageHead, toast } from "../ui.js";

export async function renderMyReports({ main }) {
  const items = await api("/incidents");
  clear(main,
    pageHead({ title: "My reports", subtitle: "Everything you've reported and where it stands.",
      right: [h("a", { class: "btn primary", href: "#/report" }, icon("plus", 17), "New report")] }),
    items.length ? h("div", { class: "items" }, items.map((i) => h("a", { class: "item", href: `#/incidents/${i.incident_id}` },
      categoryIcon(i.category_icon),
      h("div", { class: "grow" }, h("strong", {}, i.title), h("span", { class: "muted mono" }, i.incident_id), " ", i.is_demo ? demoTag() : null,
        h("div", { class: "muted" }, `${i.category_label} · ${fmtAgo(i.created_at)}`)),
      h("div", { class: "stack tight", style: { alignItems: "flex-end" } }, chip(i.status, i.status_text), dots(i.status)))))
      : card({}, emptyState("No reports yet", "Report a problem and you can follow it here.", h("a", { class: "btn primary", href: "#/report" }, "Report an issue"))));
}

export async function renderIncident(ctx) {
  const { main, params, onCleanup } = ctx;
  const inc = await api(`/incidents/${encodeURIComponent(params[0])}`);
  const role = session.me.role, loc = inc.location, task = inc.task;
  const limits = session.config.limits;
  const mapEl = h("div", { class: "map", role: "img", "aria-label": "Map of the reported location" });

  const actions = [];
  if (role === "WORKER" && task) actions.push(h("a", { class: "btn primary", href: `#/tasks/${task.task_id}` }, "Open task"));
  const pending = (inc.completions || []).filter((c) => c.accepted && !c.review_decision).slice(-1)[0];
  if (role === "SUPERVISOR" && pending) actions.push(h("a", { class: "btn primary", href: `#/review/${pending.completion_id}` }, "Review evidence"));

  clear(main,
    pageHead({ crumbs: [["Home", "#/"], [role === "CITIZEN" ? "My reports" : "Reports", role === "CITIZEN" ? "#/reports" : "#/queue"]],
      title: inc.title, subtitle: h("span", { class: "row wrap" }, inc.category_label, h("span", { class: "mono muted" }, inc.incident_id), inc.is_demo ? demoTag() : null),
      right: [chip(inc.status, inc.status_text), ...actions] }),
    card({}, lifecycle(inc.status), task?.rework_reason && ["ASSIGNED", "IN_PROGRESS"].includes(inc.status)
      ? banner("review", h("strong", {}, "Sent back for rework: "), task.rework_reason) : null),
    h("div", { class: "grid two" },
      h("div", { class: "stack", style: { gap: "22px" } },
        card({ class: "card flush" }, h("div", { class: "pad row between wrap" }, h("h2", {}, "Reported location"), h("span", { class: "muted" }, mapProviderName())),
          mapEl,
          h("div", { class: "pad stack" }, locationSource(loc), flagChips(loc.flags),
            h("div", { class: "mono muted" }, fmtCoord(loc.latitude, loc.longitude)),
            loc.observed_at ? h("span", { class: "muted" }, `Location read ${fmtTime(loc.observed_at, true)}`) : null,
            legend(["target"]))),
        card({}, h("h2", {}, "Photos"), inc.photos.length
          ? h("div", { class: "photos" }, inc.photos.map((p) => h("figure", { class: "photo" }, photo(p.url, "Reported photo"),
            h("figcaption", {}, p.capture_source === "CAMERA_LIVE" ? "Taken in the app" : p.capture_source === "CAMERA_INPUT" ? "Taken with the phone camera" : "Uploaded from files"))))
          : h("p", { class: "muted" }, "No photos."),
          role === "SUPERVISOR" ? evidenceDetails(inc.photos) : null)),
      h("div", { class: "stack", style: { gap: "22px" } },
        card({}, h("h2", {}, "About this report"), h("p", {}, inc.description),
          kv([inc.asset_identifier && [inc.asset_label || "Asset", inc.asset_identifier], inc.reporter_name && ["Reported by", inc.reporter_name],
            ["Reported", fmtTime(inc.created_at)], task && role !== "CITIZEN" && ["Assigned to", task.worker_name]]),
          inc.instructions?.length && role !== "CITIZEN" ? h("div", { class: "stack tight" }, h("span", { class: "lbl" }, "Task steps"),
            h("ol", { style: { margin: 0, paddingLeft: "20px" } }, inc.instructions.map((s) => h("li", {}, s)))) : null),
        role === "SUPERVISOR" && task ? correctionCard(inc, ctx) : null,
        (inc.completions || []).length ? attempts(inc) : null,
        card({}, h("h2", {}, "Progress"), h("div", { class: "timeline" }, inc.timeline.filter((e) => e.action === "STATUS_CHANGED" || e.action === "INCIDENT_REPORTED" || role === "SUPERVISOR")
          .map((e) => h("div", {}, h("span", { class: "muted" }, fmtTime(e.time)), h("span", {}, h("strong", {}, e.details?.to_status ? label(e.details.to_status) : label(e.action)),
            e.actor ? ` · ${e.actor}` : "", e.details?.reason ? h("div", { class: "muted" }, e.details.reason) : null))))))));

  setTimeout(async () => {
    const here = [loc.latitude, loc.longitude];
    const map = await createMap(mapEl, { center: here, zoom: 18 });
    onCleanup(() => map.destroy());
    if (loc.accuracy_m) map.circle("acc", here, loc.accuracy_m, loc.mode === "SIMULATED" ? "simulated" : "me");
    map.marker("t", "target", here, "Reported location");
    if (task && role !== "CITIZEN") map.circle("r", [task.target_latitude, task.target_longitude], limits.geofence_radius_m, "target");
    map.fit([here]);
  });
}

function attempts(inc) {
  return card({}, h("h2", {}, "Completion attempts"), (inc.completions).map((c) => h("div", { class: "row between wrap", style: { padding: "8px 0", borderBottom: "1px solid var(--line)" } },
    h("div", { class: "stack tight" }, h("span", {}, `Attempt ${c.attempt} · ${fmtTime(c.submitted_at)}`), h("span", { class: "muted" }, c.message || "")),
    h("div", { class: "row" }, chip(c.outcome), c.review_decision ? chip(c.review_decision) : null,
      session.me.role === "SUPERVISOR" && c.accepted ? h("a", { class: "btn small", href: `#/review/${c.completion_id}` }, "Open") : null))));
}

function evidenceDetails(photos) {
  if (!photos.some((p) => p.times)) return null;
  return h("details", {}, h("summary", {}, "Evidence details"), photos.map((p) => kv([
    ["Photo source", label(p.capture_source)], ["Image captured (device clock)", p.times.image_captured_at ? fmtTime(p.times.image_captured_at, true) : "Unknown (not taken in the app)"],
    ["Time claimed by the file", p.times.exif_claimed_time || "None"], ["Uploaded (device clock)", fmtTime(p.times.uploaded_at, true)],
    ["Server received", fmtTime(p.times.server_received_at, true)], ["Photo's own GPS", p.exif_gps ? fmtCoord(p.exif_gps.latitude, p.exif_gps.longitude) : label(p.exif_status)]])));
}

function correctionCard(inc, ctx) {
  const task = inc.task;
  if (!["ASSIGNED", "IN_PROGRESS"].includes(task.status)) return null;
  const lat = h("input", { type: "text", id: "clat", value: task.target_latitude.toFixed(6) });
  const lon = h("input", { type: "text", id: "clon", value: task.target_longitude.toFixed(6) });
  const why = h("input", { type: "text", id: "cwhy", maxlength: 300, placeholder: "Why is the location being corrected?" });
  return card({}, h("details", {}, h("summary", {}, "Correct the target location"),
    h("form", { class: "stack", style: { marginTop: "12px" }, onsubmit: async (e) => {
      e.preventDefault();
      try { await api(`/incidents/${inc.incident_id}/correct-location`, { method: "POST", json: { latitude: Number(lat.value), longitude: Number(lon.value), reason: why.value } });
        toast("Target corrected. The original report location is kept.", "pass"); ctx.rerender(); }
      catch (err) { toast(err.message, "fail"); }
    } },
    h("p", { class: "hint" }, `The citizen's original location stays as submitted${task.target_source === "ADMIN_CORRECTION" ? " (the target was already corrected once)" : ""}. Only the worker's target changes, with a recorded reason.`),
    h("div", { class: "grid halves" }, h("label", { class: "field", for: "clat" }, "Latitude", lat), h("label", { class: "field", for: "clon" }, "Longitude", lon)),
    h("label", { class: "field", for: "cwhy" }, "Reason", why), h("div", {}, h("button", { class: "btn primary", type: "submit" }, "Save correction")))));
}
