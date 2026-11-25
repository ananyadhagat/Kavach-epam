/* Citizen complaint, camera first.
   1. Choose a category.  2. Capture a photograph (the phone's GPS is read at the
   same moment).  3. Describe the problem.  Submit is enabled only when all of it
   is there. The server stores the photo privately, records the GPS and any EXIF
   GPS as separate evidence and runs the GeoSatya check; this page never marks
   anything as verified by itself. No gallery uploads, no simulated GPS. */

import { api, session, upload } from "../api.js";
import { LOCATION_BLOCKED_HELP, capturePhoto } from "../capture.js";
import { newKey } from "../outbox.js";
import { banner, button, card, clear, fmtTime, h, icon, pageHead, toast } from "../ui.js";
import { field } from "./widgets.js";
import { infoOf, selectCategory, selectedCategory } from "./categories.js";

const WHY_GPS = "KAVACH records where the photo was taken so the right team goes to the right spot, and so fake reports can be caught. "
  + "Your location is read only while you take the photo; it is not tracked.";

export async function renderCitizenReport({ main, onCleanup }) {
  const cat = session.catalog ||= await api("/kavach/catalog");
  const cats = cat.categories.filter((c) => c.scope !== "event");
  const remembered = selectedCategory();
  const maxAccuracy = session.config?.limits?.max_accuracy_m || 25;
  const state = { category: cats.some((c) => c.id === remembered) ? remembered : null, shot: null, sending: false, lowOk: false };

  const grid = h("div", { class: "cats" });
  const desc = h("textarea", { id: "c-desc", required: true, minlength: 10, maxlength: 2000, rows: 3 });
  const landmark = h("input", { type: "text", id: "c-land", maxlength: 200, placeholder: "Nearby shop, gate or pole number (optional)" });
  const photoBox = h("div", { class: "shot-box", "aria-live": "polite" });
  const why = h("p", { class: "status-line", id: "c-why", "aria-live": "polite" });
  const progress = h("div", { class: "progress", hidden: true }, h("span"));
  const submit = h("button", { class: "btn primary big", type: "submit", disabled: true, "aria-describedby": "c-why" }, icon("check", 18), "Submit complaint");
  const key = newKey();

  const fixOk = () => state.shot?.fix?.status === "ok";
  const accurate = () => fixOk() && state.shot.fix.accuracy_m <= maxAccuracy;
  // The reason the button is disabled, or null when everything is ready.
  const blocker = () => {
    if (!state.category) return "Choose a category.";
    if (!state.shot) return "Photograph required.";
    if (!fixOk()) return "Location required.";
    if (!accurate() && !state.lowOk) return `GPS accuracy is ±${Math.round(state.shot.fix.accuracy_m)} m; ±${maxAccuracy} m or better is needed. Retake the photo, or choose to send it for manual review.`;
    if (desc.value.trim().length < 10) return "Describe the problem (at least 10 characters).";
    return null;
  };
  const refresh = () => {
    const b = blocker();
    submit.disabled = !!b || state.sending;
    why.textContent = b || "Ready to submit. The server will check the photo and location.";
    why.classList.toggle("ok", !b);
  };

  const take = async () => {
    const res = await capturePhoto({ mode: "camera", allowGallery: false, simulated: null, title: "Capture a photograph of the problem" });
    if (!res) return;   // cancelled: keep the previous photo, if any
    if (state.shot?.preview) URL.revokeObjectURL(state.shot.preview);
    state.shot = { ...res, preview: URL.createObjectURL(res.blob) };
    state.lowOk = false;
    drawShot();
  };

  function drawShot() {
    const s = state.shot;
    if (!s) {
      clear(photoBox, h("div", { class: "shot-empty" }, h("span", { class: "ico big" }, icon("camera", 30)),
        h("strong", {}, "Capture a photograph of the problem"),
        h("span", { class: "muted" }, "The camera opens and your phone's GPS is read at the same moment."),
        button("Capture photo", { class: "btn primary big", onclick: take }, "camera")));
      refresh(); return;
    }
    const f = s.fix;
    let gps;
    if (f.status !== "ok") {
      gps = banner("fail", h("strong", {}, f.code === "PERMISSION_DENIED" ? "Location permission is needed. " : "Location not captured. "),
        f.code === "PERMISSION_DENIED" ? `${WHY_GPS} ${LOCATION_BLOCKED_HELP}` : f.message,
        h("div", { class: "row wrap", style: { marginTop: "8px" } }, button("Retry", { class: "btn small", onclick: take }, "refresh")));
    } else if (f.accuracy_m > maxAccuracy) {
      const ack = h("input", { type: "checkbox", id: "c-low", checked: state.lowOk, onchange: (e) => { state.lowOk = e.target.checked; refresh(); } });
      gps = banner("review", h("strong", {}, `Weak GPS: ±${Math.round(f.accuracy_m)} m. `),
        `KAVACH needs ±${maxAccuracy} m or better to confirm the spot. Move into open sky, away from tall buildings, and retake the photo.`,
        h("div", { class: "row wrap", style: { marginTop: "8px" } }, button("Retake photo", { class: "btn small primary", onclick: take }, "camera"),
          h("label", { class: "row", for: "c-low", style: { gap: "6px" } }, ack, "Send anyway: a supervisor checks it (not verified)")));
    } else {
      gps = h("div", { class: "gps-ok" }, icon("pin", 18), h("div", { class: "stack tight" },
        h("strong", {}, `Location captured · ±${Math.round(f.accuracy_m)} m`),
        h("span", { class: "muted mono" }, `${f.latitude.toFixed(6)}, ${f.longitude.toFixed(6)} · ${fmtTime(f.observed_at, true)}`),
        h("span", { class: "hint" }, "Recorded automatically when the photo was taken. The server checks it.")));
    }
    clear(photoBox, h("div", { class: "shot" }, h("img", { class: "preview", src: s.preview, alt: "Your photo of the problem" }),
      h("div", { class: "stack", style: { gap: "10px" } }, gps,
        h("span", { class: "hint" }, `Photo taken ${s.capturedAt ? fmtTime(s.capturedAt, true) : "with the phone camera app"}`),
        button("Retake photo", { class: "btn small", onclick: take }, "camera"))));
    refresh();
  }

  const pick = (id) => {
    state.category = id; selectCategory(id);
    grid.querySelectorAll(".cat").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.id === id)));
    const c = cats.find((x) => x.id === id);
    desc.placeholder = c?.description_placeholder || "What is the problem? One or two lines is enough.";
    refresh();
  };
  clear(grid, cats.map((c) => h("button", { class: "cat", type: "button", "data-id": c.id, "aria-pressed": "false", onclick: () => pick(c.id) },
    h("span", { class: "ico" }, icon(c.icon, 20)), infoOf(c.id)?.name || c.label)));
  desc.addEventListener("input", refresh);

  const send = async (e) => {
    e.preventDefault();
    if (blocker() || state.sending) { refresh(); return; }
    state.sending = true; refresh();
    const s = state.shot, f = s.fix;
    const c = cats.find((x) => x.id === state.category);
    const text = desc.value.trim();
    const payload = {
      category: state.category, title: `${infoOf(c.id)?.name || c.label}: ${text.slice(0, 60)}${text.length > 60 ? "…" : ""}`.slice(0, 120),
      description: text, landmark: landmark.value.trim() || null,
      device_location: { latitude: f.latitude, longitude: f.longitude, accuracy_m: f.accuracy_m, observed_at: f.observed_at, mode: "LIVE" },
      photos_meta: [{ capture_source: s.source, captured_at: s.capturedAt, uploaded_at: new Date().toISOString() }],
    };
    const form = new FormData();
    form.append("payload", JSON.stringify(payload));
    form.append("photos", s.blob, "complaint.jpg");
    progress.hidden = false;
    try {
      const res = await upload("/kavach/public/reports", form, (p) => { progress.firstChild.style.width = `${Math.round(p * 100)}%`; }, { "Idempotency-Key": key });
      selectCategory(null);
      URL.revokeObjectURL(s.preview);
      done(main, res);
    } catch (ex) {
      state.sending = false; progress.hidden = true; refresh();
      why.textContent = ex.message; why.classList.remove("ok");
      toast(ex.message, "fail");
    }
  };

  clear(main,
    pageHead({ crumbs: [["Home", "#/"]], title: "Report an issue", subtitle: "Pick what it is, take a photo, add a line. Location is recorded with the photo." }),
    h("form", { class: "stack", style: { gap: "18px" }, onsubmit: send, novalidate: true },
      card({}, h("h2", {}, h("span", { class: "step-no" }, "1"), "What is the problem?"), grid),
      card({}, h("h2", {}, h("span", { class: "step-no" }, "2"), "Photograph"), photoBox),
      card({}, h("h2", {}, h("span", { class: "step-no" }, "3"), "Describe it"),
        h("div", { class: "form-grid" }, field("What's happening?", desc, null, "full"), field("Landmark", landmark, null, "full"))),
      h("div", { class: "submit-bar" }, why, progress, submit)));
  if (state.category) pick(state.category);
  drawShot();
  onCleanup(() => { if (state.shot?.preview && !state.sending) URL.revokeObjectURL(state.shot.preview); });
}

const CHECK_TEXT = {
  LOCATION_VERIFIED: ["pass", "Location verified", "The photo and the phone's GPS agree and the reading was accurate and fresh."],
  NEEDS_REVIEW: ["review", "Sent for a supervisor's check", "Some checks did not pass, so a supervisor looks at it before it counts as verified."],
};

function done(main, inc) {
  const check = inc.geosatya_check || {};
  const [tone, head, text] = CHECK_TEXT[check.status] || CHECK_TEXT.NEEDS_REVIEW;
  const a = inc.authority?.authority;
  const copy = button("Copy", { class: "btn small", onclick: async () => {
    try { await navigator.clipboard.writeText(inc.incident_id); toast("Reference copied", "pass"); } catch { toast("Copy it from the screen", "info"); }
  } }, "copy");
  const g = check.gps;
  clear(main, card({ style: { alignItems: "center", textAlign: "center", padding: "36px 20px", gap: "16px" } },
    h("span", { class: "ico", style: { width: "64px", height: "64px", borderRadius: "50%", background: "var(--navy)", color: "#fff" } }, icon("check", 32)),
    h("h1", {}, "Complaint submitted"),
    h("div", { class: "stack tight", style: { alignItems: "center" } }, h("span", { class: "lbl" }, "Reference ID"),
      h("div", { class: "row" }, h("span", { class: "code-big" }, inc.incident_id), copy)),
    banner(tone, h("strong", {}, `GeoSatya: ${head}. `), text,
      check.reasons?.length ? h("ul", { style: { margin: "6px 0 0", paddingLeft: "18px", textAlign: "left" } }, check.reasons.map((r) => h("li", {}, r.text))) : null),
    h("dl", { class: "kv", style: { textAlign: "left", maxWidth: "520px", width: "100%" } },
      h("dt", {}, "Status"), h("dd", {}, inc.task ? "Assigned to a field worker" : "Waiting for assignment"),
      h("dt", {}, "GPS"), h("dd", {}, g ? `${g.latitude.toFixed(6)}, ${g.longitude.toFixed(6)} (±${Math.round(g.accuracy_m)} m)` : "—"),
      h("dt", {}, "Photo GPS (EXIF)"), h("dd", {}, check.exif?.note || "—"),
      h("dt", {}, "Photo stored"), h("dd", {}, "Privately; only you and the responsible team can see it"),
      h("dt", {}, "Authority"), h("dd", {}, a?.name || "KAVACH civic team")),
    h("div", { class: "row wrap center" }, h("a", { class: "btn primary big", href: `#/incidents/${inc.incident_id}` }, icon("live", 18), "Track complaint"),
      h("a", { class: "btn big", href: "#/reports" }, "My complaints"))));
}
