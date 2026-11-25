/* Worker's before photo and step checklist (optional, additive). Both are
   saved on the phone when offline and sent later, like other worker actions.
   Supervisors see the same card read-only on the review screen. */

import { cachedGet, sendOrQueue, session } from "../api.js";
import { capturePhoto, simulatedFix, simulationOn } from "../capture.js";
import { photo } from "../components.js";
import { newKey } from "../outbox.js";
import { banner, button, card, clear, fmtTime, h, icon, toast } from "../ui.js";

export function workCheckCard(taskId, { target = null, showBefore = true, showSteps = true, readOnly = false } = {}) {
  const host = h("div", { class: "stack" }, h("div", { class: "skeleton", style: { height: "70px" } }));
  const path = `/kavach/tasks/${encodeURIComponent(taskId)}/work-check`;
  let data = null;

  const takeBefore = async (mode) => {
    const res = await capturePhoto({ mode, simulated: simulationOn() && target ? () => simulatedFix(target) : null });
    if (!res) return;
    const f = res.fix;
    const payload = { photo_meta: { capture_source: res.source, captured_at: res.capturedAt, uploaded_at: new Date().toISOString() },
      device_location: f?.status === "ok" ? { latitude: f.latitude, longitude: f.longitude, accuracy_m: f.accuracy_m, observed_at: f.observed_at, mode: f.mode } : null,
      device_location_error: f?.status === "ok" ? null : (f?.code || "POSITION_UNAVAILABLE") };
    try {
      const r = await sendOrQueue(`/kavach/tasks/${taskId}/before-photo`, { kind: "before_photo", label: "Before photo", taskId, idempotencyKey: newKey(),
        form: { payload: JSON.stringify(payload), blob: res.blob, filename: "before.jpg" } });
      if (r.queued) { data.before_photo = { local: URL.createObjectURL(res.blob), queued: true }; toast("Before photo saved on this phone; it will be sent later.", "info"); }
      else { data = r; toast("Before photo saved", "pass"); }
      draw();
    } catch (e) { toast(e.message, "fail"); }
  };

  const tick = async (id, on) => {
    const s = data.steps.find((x) => x.id === id);
    s.done = on;
    const completed = data.steps.filter((x) => x.done).map((x) => x.id);
    try {
      const r = await sendOrQueue(`/kavach/tasks/${taskId}/checklist`, { kind: "checklist", label: "Checklist", taskId,
        json: { completed }, replaceKey: `checklist:${taskId}` });
      if (!r.queued) data = r;
    } catch (e) { s.done = !on; toast(e.message, "fail"); }
    draw();
  };

  const draw = () => {
    const b = data.before_photo, editable = data.editable && !readOnly;
    clear(host,
      showBefore ? h("div", { class: "stack tight" }, h("strong", {}, "Before photo"),
        b ? h("div", { class: "stack tight" }, b.local ? h("img", { class: "preview", src: b.local, alt: "Before photo (waiting to send)" }) : photo(b.url, "Before photo"),
          h("span", { class: "hint" }, b.queued ? "Waiting to send" : `Taken ${fmtTime(b.taken_at)}`))
          : editable ? h("div", { class: "capture-box", style: { padding: "18px" } }, h("p", { class: "muted" },
            "Optional: photograph the problem before you start, from where you'll take the completion photo. It lets the before/after comparison work."),
          h("div", { class: "row wrap center" }, button("Take before photo", { class: "btn", onclick: () => takeBefore("camera") }, "camera"),
            button("Upload", { class: "btn small", onclick: () => takeBefore("gallery") }, "upload")))
            : h("p", { class: "muted" }, "No before photo was taken."),
        b && editable && !b.queued ? button("Retake before photo", { class: "btn small", onclick: () => takeBefore("camera") }, "camera") : null) : null,
      showSteps && data.steps.length ? h("div", { class: "stack tight" }, h("strong", {}, "Steps done"),
        h("div", { class: "stack tight" }, data.steps.map((s) => h("label", { class: "choice" },
          h("input", { type: "checkbox", checked: s.done, disabled: !editable, onchange: (e) => tick(s.id, e.target.checked) }), s.label))),
        h("span", { class: "hint" }, readOnly ? "Ticked by the worker. A tick is their claim; the photos and GPS are the evidence."
          : "Tick what you did. Unticked steps are treated as unknown, not as not done.")) : null);
  };

  cachedGet(path).then((d) => { data = d; draw(); }).catch((e) => clear(host, banner("fail", e.message)));
  return host;
}

export function workCheckReview(taskId) {
  return card({}, h("h2", {}, icon("tasks", 18), " Worker's before photo and steps"), workCheckCard(taskId, { readOnly: true }));
}

export const isWorkerSession = () => session.me?.role === "WORKER";
