/* Citizen report: Issue → Photo & location (automatic) → Review. */

import { api, category, session, upload } from "../api.js";
import { DEMO_CENTER, LOCATION_BLOCKED_HELP, SIM_PRESETS, capturePhoto, locate, permissionState, simulatedFix, simulationOn } from "../capture.js";
import { categoryIcon, flagChips, locationSource, timingLine } from "../components.js";
import { createMap, legend, mapProviderName } from "../maps.js";
import { banner, button, card, chip, clear, fmtCoord, h, icon, pageHead, spinner, toast } from "../ui.js";

const STEPS = ["Issue", "Photo & location", "Review"];
const fresh = () => ({ category: null, title: "", description: "", asset: "", capture: null, pin: null, pinMode: false });
let draft = fresh();

const simulated = () => (simulationOn() ? () => simulatedFix(DEMO_CENTER, SIM_PRESETS[0]) : null);

export async function renderReport(ctx) {
  const { main, onCleanup } = ctx;
  let step = 0, map = null;
  onCleanup(() => map?.destroy());
  const body = h("div", { class: "stack", style: { gap: "22px" } });
  const stepper = h("ol", { class: "steps", "aria-label": "Steps" });
  clear(main, pageHead({ title: "Report an issue", subtitle: "Take a photo and we'll attach your location automatically." }), stepper, body);

  const go = (n) => { step = n; render(); };
  function render() {
    map?.destroy(); map = null;
    clear(stepper, STEPS.map((s, i) => h("li", { "aria-current": i === step ? "step" : null, class: i < step ? "done" : null }, h("span", {}, s))));
    clear(body, [stepIssue, stepPhoto, stepReview][step]());
  }

  /* ------------------------------------------------------------ 1 · issue */
  function stepIssue() {
    const cat = category(draft.category);
    const error = h("p", { class: "field-error", "aria-live": "polite" });
    const bind = (k) => (e) => { draft[k] = e.target.value; };
    return card({}, h("h2", {}, "What would you like to report?"),
      h("div", { class: "cats" }, session.categories.map((c) => h("button", {
        class: "cat", type: "button", "aria-pressed": draft.category === c.id ? "true" : "false",
        onclick: () => { draft.category = c.id; render(); } }, categoryIcon(c.icon), h("span", {}, c.label)))),
      cat ? h("div", { class: "stack" },
        h("label", { class: "field", for: "title" }, "Short title", h("input", { id: "title", type: "text", maxlength: 120, value: draft.title, placeholder: cat.title_placeholder, oninput: bind("title") })),
        h("label", { class: "field", for: "desc" }, "What's wrong?", h("textarea", { id: "desc", maxlength: 2000, value: draft.description, placeholder: cat.description_placeholder, oninput: bind("description") })),
        cat.asset_label ? h("label", { class: "field", for: "asset" }, cat.asset_label, h("span", { class: "hint" }, "Optional"),
          h("input", { id: "asset", type: "text", maxlength: 120, value: draft.asset, placeholder: cat.asset_hint, oninput: bind("asset") })) : null,
        error,
        h("div", { class: "row end" }, button("Next: photo", { class: "btn primary", onclick: () => {
          if (draft.title.trim().length < 3) { error.textContent = "Add a short title."; return; }
          if (draft.description.trim().length < 10) { error.textContent = "Describe the issue in a sentence or two."; return; }
          go(1);
        } }, "arrowRight"))) : null);
  }

  /* ----------------------------------------------------- 2 · photo + place */
  function stepPhoto() {
    const cap = draft.capture;
    const fixOk = cap?.fix?.status === "ok";
    const status = h("div", { "aria-live": "polite" });
    const mapEl = h("div", { class: "map", role: "img", "aria-label": "Map showing where the photo was taken" });

    const take = async (mode) => {
      clear(status, h("div", { class: "banner" }, h("span", { class: "spinner" }), "Opening…"));
      const res = await capturePhoto({ mode, simulated: simulated(), onStatus: (k, t) => clear(status, h("div", { class: "banner" }, h("span", { class: k === "wait" ? "spinner" : "pulse" }), t)) });
      if (!res) { clear(status); return; }
      if (draft.capture?.preview) URL.revokeObjectURL(draft.capture.preview);
      draft.capture = { ...res, preview: URL.createObjectURL(res.blob) };
      draft.pin = null; draft.pinMode = false;
      render();
    };
    const retryLocation = async () => {
      clear(status, h("div", { class: "banner" }, h("span", { class: "spinner" }), "Getting your location…"));
      draft.capture.fix = simulated() ? simulated()() : await locate();
      render();
    };

    if (!cap) {
      return card({}, h("h2", {}, "Add a photo of the issue"),
        h("div", { class: "capture-box" }, icon("camera", 34),
          h("p", { class: "muted" }, "We'll ask for your location when you take the photo, so the picture and the place stay together."),
          h("div", { class: "row wrap center" }, button("Take photo", { class: "btn primary big", onclick: () => take("camera") }, "camera"),
            button("Upload a photo", { class: "btn big", onclick: () => take("gallery") }, "upload")),
          simulationOn() ? h("span", { class: "chip demo" }, "Simulate GPS is on: a labelled demo location will be used") : null),
        status, h("div", { class: "row" }, button("Back", { onclick: () => go(0) }, "arrowLeft")));
    }

    const locBox = (() => {
      if (draft.pin) return h("div", { class: "loc-card warn" }, icon("pin", 20), h("div", { class: "stack tight" }, h("strong", {}, "Location chosen on the map"),
        h("span", { class: "muted" }, "This is your selection, not verified device GPS. It will be labelled that way.")));
      if (fixOk) return h("div", { class: "loc-card ok" }, icon("check", 20), h("div", { class: "stack tight" },
        h("strong", {}, cap.fix.mode === "SIMULATED" ? "Simulated location attached" : "Location attached"), locationSource({ source: "DEVICE_GEOLOCATION", mode: cap.fix.mode, accuracy_m: cap.fix.accuracy_m }),
        h("span", { class: "muted" }, timingLine(cap.capturedAt, cap.fix.observed_at, cap.source) || "")));
      return h("div", { class: "loc-card bad" }, icon("warn", 20), h("div", { class: "stack tight" }, h("strong", {}, "We couldn't get your location"), h("span", {}, cap.fix.message)));
    })();

    const content = h("div", { class: "grid two" },
      card({}, h("h2", {}, "Your photo"), h("img", { class: "preview", src: cap.preview, alt: "Your photo" }),
        h("div", { class: "row wrap" },
          button("Retake", { onclick: () => take("camera") }, "camera"), button("Use another file", { onclick: () => take("gallery") }, "upload"))),
      h("div", { class: "stack", style: { gap: "22px" } },
        card({ class: "card flush" }, h("div", { class: "pad row between wrap" }, h("h2", {}, "Where it was reported"), h("span", { class: "muted" }, mapProviderName())),
          mapEl, h("div", { class: "pad stack" }, locBox, status,
            !fixOk && !draft.pin ? h("div", { class: "row wrap" }, button("Retry location", { class: "btn primary", onclick: retryLocation }, "refresh"),
              button("Choose on the map instead", { onclick: () => { draft.pinMode = true; render(); } }, "pin")) : null,
            fixOk && !draft.pin ? button("Refresh location", { class: "btn small", onclick: retryLocation }, "refresh") : null,
            draft.pin ? button("Use device location instead", { class: "btn small", onclick: () => { draft.pin = null; draft.pinMode = false; retryLocation(); } }, "crosshair") : null,
            draft.pinMode && !draft.pin ? h("p", { class: "hint" }, "Click the map to mark the spot.") : null)),
        h("div", { class: "row between" }, button("Back", { onclick: () => go(0) }, "arrowLeft"),
          button("Next: review", { class: "btn primary", disabled: !(fixOk || draft.pin), onclick: () => go(2) }, "arrowRight"))));

    setTimeout(async () => {
      const here = fixOk ? [cap.fix.latitude, cap.fix.longitude] : draft.pin;
      map = await createMap(mapEl, { center: here || DEMO_CENTER, zoom: here ? 18 : 14,
        onClick: draft.pinMode ? (p) => { draft.pin = p; render(); } : null });
      if (fixOk && !draft.pin) {
        map.circle("acc", here, cap.fix.accuracy_m, cap.fix.mode === "SIMULATED" ? "simulated" : "me");
        map.marker("me", cap.fix.mode === "SIMULATED" ? "simulated" : "me", here, "Where the photo was taken");
      }
      if (draft.pin) map.marker("pin", "pin", draft.pin, "Location you chose");
      map.fit([here]);
    });
    return content;
  }

  /* ------------------------------------------------------------ 3 · review */
  function stepReview() {
    const cap = draft.capture, cat = category(draft.category), fixOk = cap.fix?.status === "ok";
    const status = h("div", { "aria-live": "polite" });
    const progress = h("div", { class: "progress", hidden: true }, h("span", { style: { width: "0%" } }));
    const submit = button("Submit report", { class: "btn primary big block" }, "check");
    const mapEl = h("div", { class: "map", style: { height: "220px" } });

    submit.addEventListener("click", async () => {
      submit.disabled = true; clear(status); progress.hidden = false;
      const f = cap.fix;
      const payload = {
        category: draft.category, title: draft.title.trim(), description: draft.description.trim(), asset_identifier: draft.asset.trim() || null,
        device_location: fixOk ? { latitude: f.latitude, longitude: f.longitude, accuracy_m: f.accuracy_m, observed_at: f.observed_at, mode: f.mode } : null,
        device_location_error: fixOk ? null : f.code,
        user_location: draft.pin ? { latitude: draft.pin[0], longitude: draft.pin[1] } : null,
        photos_meta: [{ capture_source: cap.source, captured_at: cap.capturedAt, uploaded_at: new Date().toISOString() }],
      };
      // A map pin is only used when device location failed; never sent alongside a real fix.
      if (fixOk) payload.user_location = null;
      const form = new FormData();
      form.append("payload", JSON.stringify(payload));
      form.append("photos", cap.blob, "photo.jpg");
      try {
        const incident = await upload("/incidents", form, (p) => { progress.firstChild.style.width = `${Math.round(p * 100)}%`; });
        URL.revokeObjectURL(cap.preview);
        draft = fresh(); step = 0;
        done(incident);
      } catch (e) {
        progress.hidden = true; submit.disabled = false;
        clear(status, banner("fail", h("strong", {}, "Your report was not submitted. "), e.message));
      }
    });

    setTimeout(async () => {
      const here = fixOk ? [cap.fix.latitude, cap.fix.longitude] : draft.pin;
      map = await createMap(mapEl, { center: here, zoom: 18 });
      map.marker("m", draft.pin ? "pin" : cap.fix.mode === "SIMULATED" ? "simulated" : "me", here, "Reported location");
      map.fit([here]);
    });
    return h("div", { class: "grid two" },
      card({}, h("h2", {}, "Check and send"),
        h("div", { class: "row" }, categoryIcon(cat.icon), h("div", { class: "stack tight" }, h("strong", {}, draft.title), h("span", { class: "muted" }, cat.label))),
        h("p", {}, draft.description), draft.asset ? h("p", { class: "muted" }, `${cat.asset_label}: ${draft.asset}`) : null,
        h("img", { class: "preview", src: cap.preview, alt: "Your photo" }),
        h("div", { class: "row between" }, button("Back", { onclick: () => go(1) }, "arrowLeft"))),
      card({ class: "card flush" }, h("div", { class: "pad" }, h("h2", {}, "Location")), mapEl,
        h("div", { class: "pad stack" },
          draft.pin ? chip("REVIEW_REQUIRED", "Chosen on the map: not verified GPS") : locationSource({ source: "DEVICE_GEOLOCATION", mode: cap.fix.mode, accuracy_m: cap.fix.accuracy_m }),
          h("span", { class: "mono muted" }, fmtCoord(...(draft.pin || [cap.fix.latitude, cap.fix.longitude]))),
          progress, status, submit)));
  }

  /* ----------------------------------------------------------------- done */
  function done(incident) {
    clear(stepper);
    clear(body, card({ style: { alignItems: "center", textAlign: "center", padding: "40px 24px" } },
      h("span", { class: "chip pass" }, icon("check", 14), "Report submitted"),
      h("div", { class: "stack tight", style: { alignItems: "center" } }, h("span", { class: "lbl" }, "Your reference number"),
        h("span", { class: "mono", style: { fontSize: "34px", fontWeight: 600, letterSpacing: ".04em" } }, incident.incident_id)),
      h("p", { class: "muted" }, incident.task ? `A field worker has been assigned (${incident.task.worker_name}).` : "It's waiting to be assigned."),
      flagChips(incident.location.flags),
      h("div", { class: "row wrap center" }, h("a", { class: "btn primary", href: `#/incidents/${incident.incident_id}` }, "See my report"),
        button("Report another", { onclick: () => { draft = fresh(); step = 0; render(); } }, "plus"))));
  }

  const perm = await permissionState();
  render();
  if (perm === "denied") body.prepend(banner("review", LOCATION_BLOCKED_HELP, " You can also choose the spot on the map."));
}
