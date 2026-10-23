/* Supervisor: verification queue and the review page. */

import { api } from "../api.js";
import { distanceFacts, outcomeBanner, photo, reasonChips } from "../components.js";
import { createMap, legend, mapProviderName } from "../maps.js";
import { banner, button, card, chip, clear, demoTag, emptyState, fmtAgo, fmtCoord, fmtM, fmtTime, h, kv, label, pageHead, reasonDialog, toast } from "../ui.js";

export async function renderQueue({ main }) {
  const queue = await api("/verification-queue");
  const pending = queue.filter((q) => q.pending), decided = queue.filter((q) => !q.pending);
  const item = (q) => h("a", { class: "item", href: `#/review/${q.completion_id}` },
    h("div", { class: "grow" }, h("strong", {}, q.title), h("span", { class: "mono muted" }, q.incident_id), " ", q.is_demo ? demoTag() : null,
      h("div", { class: "muted" }, `${q.category_label} · ${q.worker_name} · ${fmtAgo(q.submitted_at)}`),
      h("div", { class: "muted" }, q.message)),
    h("div", { class: "stack tight", style: { alignItems: "flex-end" } }, chip(q.outcome),
      q.review_decision ? chip(q.review_decision) : h("span", { class: "muted" }, q.distance_m != null ? fmtM(q.distance_m) : "")));
  clear(main, pageHead({ title: "Verification queue", subtitle: "Completion evidence waiting for your decision.",
    right: pending.length ? [h("a", { class: "btn primary", href: `#/review/${pending[0].completion_id}` }, "Review next")] : [] }),
    pending.length ? h("div", { class: "items" }, pending.map(item)) : card({}, emptyState("All caught up", "New completion evidence will appear here.")),
    decided.length ? h("div", { class: "stack" }, h("h2", {}, "Decided"), h("div", { class: "items" }, decided.map(item))) : null);
}

export async function renderNextReview(ctx) {
  const next = (await api("/verification-queue")).find((q) => q.pending);
  if (next) { location.replace(`#/review/${next.completion_id}`); return; }
  clear(ctx.main, pageHead({ title: "Supervisor review" }), card({}, emptyState("Nothing to review", "Evidence the checks send for review will appear here.",
    h("a", { class: "btn", href: "#/queue" }, "Verification queue"))));
}

export async function renderReview(ctx) {
  const { main, params, onCleanup, rerender } = ctx;
  const c = await api(`/completions/${encodeURIComponent(params[0])}`);
  const inc = c.incident, r = c.result, dev = c.device;
  const mapEl = h("div", { class: "map", role: "img", "aria-label": "Map: incident location, allowed radius and the worker's reported position" });

  const decide = async (decision, title, description, tone) => {
    const needsReason = decision !== "APPROVE" || c.outcome !== "PASS";
    const reason = await reasonDialog({ title, description, confirmText: title, required: needsReason, tone });
    if (reason === null) return;
    try { await api(`/completions/${c.completion_id}/review`, { method: "POST", json: { decision, reason } }); toast("Decision recorded", "pass"); rerender(); }
    catch (e) { toast(e.message, "fail"); }
  };

  clear(main,
    pageHead({ crumbs: [["Home", "#/"], ["Queue", "#/queue"], [inc.incident_id]], title: inc.title,
      subtitle: h("span", { class: "row wrap" }, inc.category_label, h("span", { class: "mono muted" }, inc.incident_id), `Worker: ${c.worker_name}`, inc.is_demo ? demoTag() : null),
      right: [h("a", { class: "btn", href: `#/incidents/${inc.incident_id}` }, "Report details")] }),
    outcomeBanner(c.outcome, c.message, { simulated: c.simulated }),
    c.review_decision ? card({}, h("h2", {}, "Decision recorded"), chip(c.review_decision), h("p", {}, c.review_reason || "No note."),
      h("span", { class: "muted" }, `${c.reviewed_by_name} · ${fmtTime(c.reviewed_at)}`))
      : c.pending ? card({}, h("h2", {}, "Your decision"),
        c.outcome !== "PASS" ? h("p", { class: "muted" }, "The automated checks did not pass cleanly, so approving is an override and needs a reason.") : null,
        h("div", { class: "row wrap" },
          button("Approve", { class: "btn good", onclick: () => decide("APPROVE", "Approve", "Mark this incident resolved.") }, "check"),
          button("Request more evidence", { onclick: () => decide("REQUEST_EVIDENCE", "Request more evidence", "The worker gets your note and a new attempt.") }, "camera"),
          button("Reject", { class: "btn danger", onclick: () => decide("REJECT", "Reject", "The job goes back to the worker with your reason.", "danger") }, "x")))
        : null,
    h("div", { class: "grid halves" },
      card({}, h("h2", {}, "Reported"), inc.photos[0] ? photo(inc.photos[0].url, "Photo from the report") : h("p", { class: "muted" }, "No photo"),
        h("p", {}, inc.description)),
      card({}, h("h2", {}, "Completed"), c.photo ? photo(c.photo.url, "Completion photo") : h("p", { class: "muted" }, "No photo"),
        h("p", {}, `“${c.description}”`))),
    h("div", { class: "grid two" },
      card({ class: "card flush" }, h("div", { class: "pad row between wrap" }, h("h2", {}, "Where the worker was"), h("span", { class: "muted" }, mapProviderName())),
        mapEl, h("div", { class: "pad stack" }, legend(["target", "me", "exif"]), distanceFacts(c.distance_m, c.accuracy_m, c.radius_m))),
      h("div", { class: "stack", style: { gap: "22px" } },
        card({}, h("h2", {}, "Why this result"), c.reason_codes.length ? reasonChips(c.reason_codes) : null,
          r.exif_target_distance_m != null ? h("p", { class: "muted" }, `Photo GPS is ${fmtM(r.exif_target_distance_m)} from the incident and ${fmtM(r.exif_device_distance_m)} from the worker.`) : null,
          h("p", { class: "muted" }, "GPS shows proximity only. It can't show that the photo is of the right object, so a person confirms it.")),
        card({}, h("details", {}, h("summary", {}, "Evidence details"),
          kv([["Photo source", c.photo ? label(c.photo.capture_source) : "—"],
            ["Image captured (device clock)", r.times?.image_captured_at ? fmtTime(r.times.image_captured_at, true) : "Unknown (not taken in the app)"],
            ["Location read (device clock)", r.times?.location_observed_at ? fmtTime(r.times.location_observed_at, true) : "—"],
            ["Uploaded (device clock)", r.times?.uploaded_at ? fmtTime(r.times.uploaded_at, true) : "—"],
            ["Server received", fmtTime(r.times?.server_received_at, true)],
            ["Time claimed by the file", c.photo?.times?.exif_claimed_time || "None"],
            ["Photo's own GPS", c.photo?.exif_gps ? fmtCoord(c.photo.exif_gps.latitude, c.photo.exif_gps.longitude) : label(c.photo?.exif_status || "none")],
            ["Worker position", dev?.available ? `${fmtCoord(dev.latitude, dev.longitude)}${dev.mode === "SIMULATED" ? " (SIMULATED)" : ""}` : `Not available (${label(dev?.unavailable_reason)})`],
            ["Target", `${fmtCoord(c.target.latitude, c.target.longitude)} (${c.target.source === "ADMIN_CORRECTION" ? "corrected by a supervisor" : "as reported"})`],
            ["Attempt", String(c.attempt)]]))))));

  setTimeout(async () => {
    const target = [c.target.latitude, c.target.longitude];
    const map = await createMap(mapEl, { center: target, zoom: 19 });
    onCleanup(() => map.destroy());
    map.circle("radius", target, c.radius_m, "target");
    map.marker("target", "target", target, "Incident location");
    const pts = [target];
    if (dev?.available) {
      const kind = dev.mode === "SIMULATED" ? "simulated" : "me";
      if (dev.accuracy_m) map.circle("acc", [dev.latitude, dev.longitude], dev.accuracy_m, kind);
      map.marker("me", kind, [dev.latitude, dev.longitude], "Worker's reported position");
      pts.push([dev.latitude, dev.longitude]);
    }
    if (c.photo?.exif_gps) { map.marker("exif", "exif", [c.photo.exif_gps.latitude, c.photo.exif_gps.longitude], "Photo's own GPS"); pts.push([c.photo.exif_gps.latitude, c.photo.exif_gps.longitude]); }
    map.fit(pts);
  });
}
