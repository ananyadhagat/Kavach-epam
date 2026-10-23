/* Worker: task list, and the task page where location + completion photo are verified. */

import { api, session, upload } from "../api.js";
import { SIM_PRESETS, capturePhoto, haversine, locate, permissionState, previewCheck, simulatedFix, simulationOn } from "../capture.js";
import { categoryIcon, outcomeBanner, photo, reasonChips, timingLine } from "../components.js";
import { createMap, legend, mapProviderName } from "../maps.js";
import { banner, button, card, chip, clear, demoTag, emptyState, fmtM, fmtTime, h, icon, label, pageHead, toast } from "../ui.js";

export async function renderTasks({ main, rerender }) {
  const tasks = await api("/tasks");
  const open = tasks.filter((t) => ["ASSIGNED", "IN_PROGRESS"].includes(t.status));
  const rest = tasks.filter((t) => !open.includes(t));
  const item = (t) => h("a", { class: "item", href: `#/tasks/${t.task_id}` }, categoryIcon(t.incident.category_icon),
    h("div", { class: "grow" }, h("strong", {}, t.incident.title), h("span", { class: "mono muted" }, t.incident.incident_id), " ", t.incident.is_demo ? demoTag() : null,
      h("div", { class: "muted" }, t.incident.category_label + (session.me.role === "SUPERVISOR" ? ` · ${t.worker_name}` : "")),
      t.rework_reason && ["ASSIGNED", "IN_PROGRESS"].includes(t.status) ? h("div", { class: "chip review", style: { marginTop: "6px" } }, `Rework: ${t.rework_reason}`) : null),
    chip(t.status));
  clear(main, pageHead({ title: session.me.role === "WORKER" ? "My tasks" : "All field tasks", subtitle: "Each task opens at the location the citizen reported." }),
    h("div", { class: "stack" }, h("h2", {}, "To do"), open.length ? h("div", { class: "items" }, open.map(item))
      : card({}, emptyState("Nothing to do right now", "New reports are assigned automatically."))),
    rest.length ? h("div", { class: "stack" }, h("h2", {}, "Submitted"), h("div", { class: "items" }, rest.map(item))) : null);
}

/* "Submit Completion Evidence": jump straight to the task that needs it. */
export async function renderEvidenceShortcut(ctx) {
  const tasks = await api("/tasks");
  const next = tasks.find((t) => t.status === "IN_PROGRESS") || tasks.find((t) => t.status === "ASSIGNED");
  if (next) { location.replace(`#/tasks/${next.task_id}`); return; }
  clear(ctx.main, pageHead({ title: "Submit completion evidence" }), card({}, emptyState("No task needs evidence", "Tasks assigned to you appear here.", h("a", { class: "btn", href: "#/tasks" }, "My tasks"))));
}

const outcomeOf = (c) => outcomeBanner(c.outcome, c.message, { simulated: c.simulated });

export async function renderTask(ctx) {
  const { main, params, onCleanup, rerender } = ctx;
  const t = await api(`/tasks/${encodeURIComponent(params[0])}`);
  const inc = t.incident, limits = t.limits, isWorker = session.me.role === "WORKER";
  const target = [t.target_latitude, t.target_longitude];
  const editable = isWorker && t.status === "IN_PROGRESS";
  const draft = (renderTask.drafts ||= {})[`${t.task_id}:${t.attempt}`] ||= { cap: null, fix: null, description: "", preset: SIM_PRESETS[0], result: null };
  let map = null;
  onCleanup(() => map?.destroy());
  const mapEl = h("div", { class: "map tall", role: "img", "aria-label": "Map: the incident location, the allowed radius and your position" });
  const livePanel = h("div", { class: "stack", "aria-live": "polite" });
  const resultBox = h("div", { class: "stack", "aria-live": "polite" });
  const capBox = h("div", { class: "stack" });

  const simFix = () => simulatedFix(target, draft.preset);
  const currentFix = () => draft.cap?.fix || draft.fix;

  const drawMap = () => {
    if (!map) return;
    map.circle("radius", target, limits.geofence_radius_m, "target");
    map.marker("target", "target", target, "Incident location");
    map.remove("me"); map.remove("acc");
    const f = currentFix();
    if (f?.status === "ok") {
      const kind = f.mode === "SIMULATED" ? "simulated" : "me";
      map.circle("acc", [f.latitude, f.longitude], f.accuracy_m, kind);
      map.marker("me", kind, [f.latitude, f.longitude], "Your location");
    }
    map.fit([target, f?.status === "ok" ? [f.latitude, f.longitude] : null]);
  };

  const drawLive = () => {
    const f = currentFix();
    const p = previewCheck(f, target, limits);
    clear(livePanel,
      !f ? h("p", { class: "muted" }, "Check your position to see how far you are from the spot.") : null,
      f?.status === "error" ? banner("fail", f.message) : null,
      p ? h("div", { class: "facts" },
        h("div", {}, h("span", { class: "lbl" }, "Distance to the spot"), h("strong", {}, fmtM(p.distance))),
        h("div", {}, h("span", { class: "lbl" }, "Your GPS accuracy"), h("strong", {}, `±${Math.round(f.accuracy_m)} m`)),
        h("div", {}, h("span", { class: "lbl" }, "Allowed radius"), h("strong", {}, `${limits.geofence_radius_m} m`))) : null,
      p ? h("p", { class: p.state === "inside" ? "chip pass" : p.state === "outside" ? "chip fail" : "chip review" },
        { inside: "Looks inside the allowed area", outside: "Outside the allowed area: move closer", edge: "At the edge of the area", weak: "GPS too weak to be sure" }[p.state],
        " (the server makes the final decision)") : null,
      f?.mode === "SIMULATED" ? h("span", { class: "chip demo" }, "Simulated location") : null);
  };

  const check = async () => {
    clear(livePanel, h("div", { class: "banner" }, h("span", { class: "spinner" }), "Getting your location…"));
    draft.fix = simulationOn() ? simFix() : await locate();
    drawLive(); drawMap();
  };

  const submit = button("Submit evidence", { class: "btn primary big block" }, "check");
  const desc = h("textarea", { id: "desc", maxlength: 2000, value: draft.description, placeholder: "What did you do? e.g. Filled and levelled the pothole.",
    oninput: (e) => { draft.description = e.target.value; } });

  const drawCap = () => {
    const c = draft.cap;
    clear(capBox,
      !c ? h("div", { class: "capture-box" }, icon("camera", 30), h("p", { class: "muted" }, "Stand at the spot, then take the completion photo. Your location is read at the same time."),
        h("div", { class: "row wrap center" }, button("Take completion photo", { class: "btn primary big", onclick: () => capture("camera") }, "camera"),
          button("Upload photo", { onclick: () => capture("gallery") }, "upload")))
        : h("div", { class: "stack" }, h("img", { class: "preview", src: c.preview, alt: "Completion photo" }),
          c.fix.status === "ok" ? h("p", { class: "muted" }, timingLine(c.capturedAt, c.fix.observed_at, c.source) || "") : banner("fail", c.fix.message),
          h("div", { class: "row wrap" }, button("Retake", { onclick: () => capture("camera") }, "camera"),
            c.fix.status !== "ok" ? button("Retry location", { class: "btn primary", onclick: async () => { c.fix = simulationOn() ? simFix() : await locate(); drawCap(); drawLive(); drawMap(); } }, "refresh") : null)));
  };

  const capture = async (mode) => {
    const res = await capturePhoto({ mode, simulated: simulationOn() ? simFix : null });
    if (!res) return;
    if (draft.cap?.preview) URL.revokeObjectURL(draft.cap.preview);
    draft.cap = { ...res, preview: URL.createObjectURL(res.blob) };
    clear(resultBox);
    drawCap(); drawLive(); drawMap();
  };

  submit.addEventListener("click", async () => {
    clear(resultBox);
    const c = draft.cap, f = c?.fix;
    const problems = [];
    if (!c) problems.push("Take the completion photo.");
    if (draft.description.trim().length < session.config.min_completion_chars) problems.push("Describe the work you did.");
    if (problems.length) { clear(resultBox, banner("fail", h("ul", { style: { margin: 0, paddingLeft: "18px" } }, problems.map((p) => h("li", {}, p))))); return; }
    submit.disabled = true;
    const payload = { description: draft.description.trim(),
      photo_meta: { capture_source: c.source, captured_at: c.capturedAt, uploaded_at: new Date().toISOString() },
      device_location: f.status === "ok" ? { latitude: f.latitude, longitude: f.longitude, accuracy_m: f.accuracy_m, observed_at: f.observed_at, mode: f.mode } : null,
      device_location_error: f.status === "ok" ? null : f.code };
    const form = new FormData();
    form.append("payload", JSON.stringify(payload));
    form.append("photo", c.blob, "completion.jpg");
    try {
      const res = await upload(`/tasks/${t.task_id}/completion`, form);
      const comp = res.completion;
      if (comp.accepted) { delete renderTask.drafts[`${t.task_id}:${t.attempt}`]; toast("Evidence submitted", comp.outcome === "PASS" ? "pass" : "info"); rerender(); return; }
      // Not accepted: keep the form so the worker can move and try again.
      submit.disabled = false;
      draft.result = comp;
      clear(resultBox, outcomeOf(comp), h("div", { class: "facts" },
        h("div", {}, h("span", { class: "lbl" }, "Distance"), h("strong", {}, fmtM(comp.distance_m))),
        h("div", {}, h("span", { class: "lbl" }, "GPS accuracy"), h("strong", {}, comp.accuracy_m ? `±${Math.round(comp.accuracy_m)} m` : "—")),
        h("div", {}, h("span", { class: "lbl" }, "Allowed radius"), h("strong", {}, `${comp.radius_m} m`))),
        h("p", { class: "muted" }, "Nothing was submitted for review. Move closer, retake the photo and try again."));
      draft.cap = null; drawCap();
    } catch (err) {
      submit.disabled = false;
      clear(resultBox, banner("fail", h("strong", {}, "Not submitted. "), err.message));
    }
  });

  const attemptsDone = (inc.completions || []);
  const last = attemptsDone.filter((c) => c.accepted).slice(-1)[0];
  clear(main,
    pageHead({ crumbs: [["Home", "#/"], ["Tasks", "#/tasks"], [inc.incident_id]], title: inc.title,
      subtitle: h("span", { class: "row wrap" }, inc.category_label, h("span", { class: "mono muted" }, inc.incident_id), inc.is_demo ? demoTag() : null),
      right: [chip(t.status), h("a", { class: "btn", href: `#/incidents/${inc.incident_id}` }, "Report details")] }),
    isWorker && t.status === "ASSIGNED" ? card({}, h("div", { class: "row between wrap" }, h("div", { class: "stack tight" }, h("h2", {}, "Ready to start?"),
      h("span", { class: "muted" }, "Go to the marked spot. You'll verify your position when you take the completion photo.")),
      button("Start work", { class: "btn primary", onclick: async () => { try { await api(`/tasks/${t.task_id}/start`, { method: "POST" }); rerender(); } catch (e) { toast(e.message, "fail"); } } }, "arrowRight"))) : null,
    t.rework_reason && ["ASSIGNED", "IN_PROGRESS"].includes(t.status) ? banner("review", h("strong", {}, "Sent back for rework: "), t.rework_reason) : null,
    last && !editable ? card({}, h("h2", {}, t.status === "RESOLVED" ? "Resolved" : "Waiting for the supervisor"), outcomeOf(last)) : null,
    h("div", { class: "grid two" },
      h("div", { class: "stack", style: { gap: "22px" } },
        card({ class: "card flush" }, h("div", { class: "pad row between wrap" }, h("h2", {}, "The spot"), h("span", { class: "muted" }, mapProviderName())),
          mapEl, h("div", { class: "pad stack" }, legend(["target", "me"]), livePanel,
            h("div", { class: "row wrap" },
              isWorker ? button("Check my position", { class: "btn primary", onclick: check }, "crosshair") : null,
              h("a", { class: "btn", target: "_blank", rel: "noopener", href: `https://www.google.com/maps/dir/?api=1&destination=${target[0]},${target[1]}` }, icon("navigate", 17), "Directions"),
              ),
            isWorker && simulationOn() ? h("div", { class: "row wrap" }, h("span", { class: "chip demo" }, "Simulate"),
              SIM_PRESETS.map((p) => button(p.label, { class: "btn small", onclick: () => { draft.preset = p; if (draft.cap?.fix) draft.cap.fix = simFix(); else draft.fix = simFix(); drawLive(); drawMap(); drawCap(); } }))) : null)),
        card({}, h("h2", {}, "The report"), h("p", {}, inc.description),
          inc.asset_identifier ? h("p", { class: "muted" }, `${inc.asset_label || "Asset"}: ${inc.asset_identifier}`) : null,
          h("div", { class: "stack tight" }, h("span", { class: "lbl" }, "Steps"), h("ol", { style: { margin: 0, paddingLeft: "20px" } }, inc.instructions.map((s) => h("li", {}, s)))),
          inc.photos[0] ? h("figure", { class: "photo" }, photo(inc.photos[0].url, "Citizen's photo"), h("figcaption", {}, "Photo from the report")) : null)),
      h("div", { class: "stack", style: { gap: "22px" } },
        editable ? card({}, h("h2", {}, "Completion evidence"), capBox,
          h("label", { class: "field", for: "desc" }, "What did you do?", desc), resultBox, submit,
          h("p", { class: "hint" }, `You must be within ${limits.geofence_radius_m} m of the spot. The distance is recalculated on the server from your reported position.`)) : null,
        attemptsDone.length ? card({}, h("h2", {}, "Attempts"), attemptsDone.map((c) => h("div", { class: "stack tight", style: { padding: "8px 0", borderBottom: "1px solid var(--line)" } },
          h("div", { class: "row between" }, h("span", {}, `Attempt ${c.attempt} · ${fmtTime(c.submitted_at)}`), chip(c.outcome)),
          h("span", { class: "muted" }, c.message), c.review_decision ? h("span", {}, `Supervisor: ${label(c.review_decision)}${c.review_reason ? ` – ${c.review_reason}` : ""}`) : null))) : null)));

  drawCap(); drawLive();
  setTimeout(async () => { map = await createMap(mapEl, { center: target, zoom: 19 }); drawMap(); });
  if (editable) { const perm = await permissionState(); if (perm === "denied") clear(resultBox, banner("review", "Location is blocked for this site. Allow it in the address-bar site settings, then try again.")); }
}
