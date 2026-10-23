/* Photo + location capture.

Location is requested only when the user starts a capture (never in the
background, never tracked). We record, separately and honestly:
  - the image capture time          (device clock; only the in-app camera knows it)
  - the location observation time   (the position's own timestamp)
so a reviewer can see how far apart they were. A position read before the
shutter is never described as measured at the shutter instant; if the fix is
older than the freshness limit when the photo is taken, it is refreshed first. */

import { preference, session } from "./api.js";
import { button, clear, h, icon } from "./ui.js";

const GEO_TEXT = {
  PERMISSION_DENIED: "Location permission is blocked for this site. Click the lock (or tune) icon beside the address bar, set Location to Allow, then press Retry.",
  POSITION_UNAVAILABLE: "Your device couldn't work out its position. Move near a window or outdoors, then press Retry.",
  TIMEOUT: "Getting a GPS fix took too long. Press Retry, ideally outdoors.",
  UNSUPPORTED: "This page can't use location. Location needs https:// or http://localhost, and a browser that supports it.",
};

export const permissionState = async () => {
  try { return (await navigator.permissions.query({ name: "geolocation" })).state; } catch { return "unknown"; }
};

/* One high-accuracy reading, never a cached one, with a timeout. */
export function locate({ timeout = 15000 } = {}) {
  return new Promise((resolve) => {
    const fail = (code) => resolve({ status: "error", code, message: GEO_TEXT[code] });
    if (!window.isSecureContext || !navigator.geolocation) return fail("UNSUPPORTED");
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ status: "ok", mode: "LIVE", latitude: pos.coords.latitude, longitude: pos.coords.longitude,
        accuracy_m: pos.coords.accuracy, observed_at: new Date(pos.timestamp).toISOString() }),
      (err) => fail({ 1: "PERMISSION_DENIED", 2: "POSITION_UNAVAILABLE", 3: "TIMEOUT" }[err.code] || "POSITION_UNAVAILABLE"),
      { enableHighAccuracy: true, timeout, maximumAge: 0 },
    );
  });
}

/* ------- simulation: labelled test coordinates, never presented as GPS ------- */
export const simulationOn = () => !!session.config?.simulation_allowed && preference("simulate") === "on";
export const DEMO_CENTER = [23.2599, 77.4126];
export const SIM_PRESETS = [
  { id: "at", label: "At the spot", north: 2, east: 3, accuracy: 8 },
  { id: "near", label: "12 m away", north: 9, east: 8, accuracy: 8 },
  { id: "far", label: "45 m away", north: 30, east: 32, accuracy: 8 },
  { id: "weak", label: "Weak GPS (±80 m)", north: 3, east: 2, accuracy: 80 },
];
export function simulatedFix(center, preset = SIM_PRESETS[0]) {
  const lat = center[0] + preset.north / 111320;
  const lon = center[1] + preset.east / (111320 * Math.cos((center[0] * Math.PI) / 180));
  return { status: "ok", mode: "SIMULATED", latitude: lat, longitude: lon, accuracy_m: preset.accuracy, observed_at: new Date().toISOString() };
}

export function haversine(a, b) {
  const r = (d) => (d * Math.PI) / 180;
  const x = Math.sin(r(b[0] - a[0]) / 2) ** 2 + Math.cos(r(a[0])) * Math.cos(r(b[0])) * Math.sin(r(b[1] - a[1]) / 2) ** 2;
  return 2 * 6371008.8 * Math.asin(Math.min(1, Math.sqrt(x)));
}

/* Preview of the server's rule, for instant feedback. The server decides. */
export function previewCheck(fix, target, limits) {
  if (!fix || fix.status !== "ok") return null;
  const distance = haversine(target, [fix.latitude, fix.longitude]);
  const acc = fix.accuracy_m;
  let state = "inside";
  if (distance - acc > limits.geofence_radius_m) state = "outside";
  else if (acc > limits.max_accuracy_m) state = "weak";
  else if (distance > limits.geofence_radius_m) state = "edge";
  return { distance, state };
}

const cameraError = (e) => ({
  NotAllowedError: "Camera permission was denied. Allow the camera for this site, or use the buttons below.",
  NotFoundError: "No camera was found on this device. Use the buttons below.",
}[e?.name] || "The camera couldn't be opened here. Use the buttons below.");

/* mode "camera": live preview with shutter (falls back to file buttons).
   mode "gallery": straight to the file chooser.
   Resolves {blob, source, capturedAt, fix} or null if cancelled. */
export function capturePhoto({ mode = "camera", simulated = null, freshnessMs = (session.config?.location_freshness_s || 30) * 1000, onStatus } = {}) {
  return new Promise((resolve) => {
    let fixPromise = null, stream = null, dialog = null, done = false, statusEl = null, loose = null;
    const stop = () => stream?.getTracks().forEach((t) => t.stop());
    const finish = (value) => { if (done) return; done = true; stop(); dialog?.close(); dialog?.remove(); loose?.remove(); resolve(value); };

    const setStatus = (kind, text, retry) => {
      onStatus?.(kind, text);
      if (!statusEl) return;
      clear(statusEl,
        kind === "wait" ? h("span", { class: "spinner" }) : kind === "ok" ? h("span", { class: "pulse" }) : icon(kind === "sim" ? "info" : "warn", 16),
        h("span", { style: { flex: 1 } }, text),
        retry ? h("button", { class: "btn small light", type: "button", onclick: () => { fixPromise = startLocation(); } }, "Retry") : null);
    };
    const startLocation = async () => {
      if (simulated) {
        const f = simulated();
        setStatus("sim", `Simulated location (±${f.accuracy_m} m): demo only, not real GPS`);
        return f;
      }
      setStatus("wait", "Getting your location… allow it if asked");
      const f = await locate();
      f.status === "ok" ? setStatus("ok", `Location ready · GPS ±${Math.round(f.accuracy_m)} m`) : setStatus("bad", f.message, true);
      return f;
    };
    const freshFix = async () => {
      let f = await fixPromise;
      const stale = f.status === "ok" && Date.now() - new Date(f.observed_at).getTime() > freshnessMs;
      if (!simulated && (f.status !== "ok" || stale)) f = await (fixPromise = startLocation());
      return f;
    };
    const fromFile = (source) => async (e) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      setStatus("wait", "Getting your location…");
      // A file has no known capture instant; its modified time is not it.
      finish({ blob: file, source, capturedAt: null, fix: await freshFix() });
    };
    const fileInput = (source, capture) => h("input", { class: "visually-hidden", type: "file", accept: "image/jpeg,image/png,image/webp",
      capture: capture || null, onchange: fromFile(source) });

    if (mode === "gallery") {
      const input = loose = fileInput("GALLERY");
      document.body.append(input);
      input.addEventListener("cancel", () => finish(null));
      fixPromise = startLocation();       // asked now: the user just chose to add a photo
      input.click();
      return;
    }

    const video = h("video", { autoplay: true, playsinline: true, muted: true });
    const message = h("div", { class: "message", hidden: true });
    statusEl = h("div", { class: "status", role: "status" });
    const shutter = h("button", { class: "shutter", type: "button", disabled: true, "aria-label": "Take photo", onclick: async () => {
      shutter.disabled = true;
      const capturedAt = new Date();       // device clock, at the shutter
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth; canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0);
      const blob = await new Promise((r) => canvas.toBlob(r, "image/jpeg", 0.9));
      finish({ blob, source: "CAMERA_LIVE", capturedAt: capturedAt.toISOString(), fix: await freshFix() });
    } });
    const cameraInput = fileInput("CAMERA_INPUT", "environment"), galleryInput = fileInput("GALLERY");
    dialog = h("dialog", { class: "camera", "aria-label": "Take a photo" },
      h("div", { class: "stage" }, video, message, statusEl),
      h("div", { class: "bar" },
        h("div", { class: "row center" }, shutter),
        h("div", { class: "row wrap center" },
          button("Phone camera app", { class: "btn small light", onclick: () => cameraInput.click() }, "camera"),
          button("Choose a photo", { class: "btn small light", onclick: () => galleryInput.click() }, "image"),
          button("Cancel", { class: "btn small light", onclick: () => finish(null) })),
        cameraInput, galleryInput));
    document.body.append(dialog);
    dialog.addEventListener("cancel", (e) => { e.preventDefault(); finish(null); });
    dialog.showModal();
    fixPromise = startLocation();
    (async () => {
      if (!navigator.mediaDevices?.getUserMedia) {
        message.textContent = "The live camera needs https:// or http://localhost. Use the buttons below.";
        message.hidden = false; video.hidden = true; return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
        if (done) return stop();
        video.srcObject = stream;
        await video.play();
        shutter.disabled = false;
      } catch (e) { message.textContent = cameraError(e); message.hidden = false; video.hidden = true; }
    })();
  });
}
