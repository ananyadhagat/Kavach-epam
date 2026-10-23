import { protectedImage } from "./api.js";
import { chip, fmtM, h, icon, label, simTag } from "./ui.js";

const STEPS = ["SUBMITTED", "ASSIGNED", "IN_PROGRESS", "AWAITING_VERIFICATION", "RESOLVED"];
const STEP_TEXT = { SUBMITTED: "Submitted", ASSIGNED: "Assigned", IN_PROGRESS: "In progress", AWAITING_VERIFICATION: "Verifying", RESOLVED: "Resolved" };

export function lifecycle(status) {
  const now = STEPS.indexOf(status);
  const items = [];
  STEPS.forEach((s, i) => {
    if (i) items.push(h("i", { "aria-hidden": "true" }, "›"));
    items.push(h("span", { class: i === now ? "now" : i < now ? "done" : "" }, STEP_TEXT[s]));
  });
  return h("div", { class: "lifecycle", "aria-label": `Status: ${STEP_TEXT[status] || status}` }, items);
}

export const dots = (status) => h("span", { class: "dots", title: STEP_TEXT[status] || status },
  STEPS.map((_, i) => h("i", { class: i <= STEPS.indexOf(status) ? "on" : "" })));

export function photo(url, alt, cls = "preview") {
  const img = h("img", { class: cls, alt });
  protectedImage(url).then((src) => { img.src = src; }).catch(() => { img.alt = `${alt} (unavailable)`; });
  return img;
}

export const categoryIcon = (name) => h("span", { class: "ico" }, icon(name || "dots", 20));

/* What a location flag means, in plain words. */
export const FLAG_TEXT = {
  USER_SELECTED_LOCATION: "Location chosen on the map (not device GPS)",
  SIMULATED_LOCATION: "Simulated location (demo)",
  LOW_GPS_ACCURACY: "Weak GPS accuracy",
  PHOTO_FROM_GALLERY: "Photo not taken in the app: location is where it was uploaded",
  PHOTO_GPS_CONFLICT: "Photo's own GPS disagrees with the device location",
};

export const REASON_TEXT = {
  WITHIN_RADIUS: "Inside the permitted radius",
  OUTSIDE_RADIUS: "Outside the permitted radius",
  POOR_GPS_ACCURACY: "GPS accuracy too weak to confirm the position",
  BOUNDARY_UNCERTAIN: "At the edge of the radius; GPS can't place the worker inside it",
  ACCURACY_NOT_REPORTED: "The device didn't report GPS accuracy",
  SOURCE_CONFLICT: "Photo GPS, device GPS and incident location disagree",
  EXIF_FAR_FROM_TARGET: "The photo's own GPS is far from the incident",
  PHOTO_LOCATION_UNVERIFIED: "Where the photo was taken can't be confirmed",
  DUPLICATE_PHOTO: "This photo was submitted before",
  SIMULATED_LOCATION: "Simulated location",
  SIMULATED_LOCATION_NOT_ACCEPTED: "Simulated location can't verify presence",
  LOCATION_UNAVAILABLE: "No usable location",
  PERMISSION_DENIED: "Location permission denied",
  TIMEOUT: "Location timed out",
  POSITION_UNAVAILABLE: "Position unavailable",
  UNSUPPORTED: "Location unsupported",
  NO_TARGET: "The incident has no location to compare with",
};

export const reasonChips = (codes) => h("div", { class: "row wrap", style: { gap: "6px" } },
  (codes || []).map((c) => h("span", { class: "code", title: c }, REASON_TEXT[c] || label(c))));

const OUTCOME = {
  PASS: { cls: "pass", icon: "check", title: "Verified on site" },
  FAIL: { cls: "fail", icon: "x", title: "Not accepted" },
  REVIEW_REQUIRED: { cls: "review", icon: "warn", title: "Needs supervisor review" },
  NOT_CHECKED: { cls: "info", icon: "info", title: "Location not checked" },
};
export function outcomeBanner(outcome, message, { simulated = false } = {}) {
  const o = OUTCOME[outcome] || OUTCOME.NOT_CHECKED;
  return h("div", { class: `outcome ${o.cls}`, role: outcome === "FAIL" ? "alert" : "status" },
    h("span", { class: "ico" }, icon(o.icon, 22)),
    h("div", { class: "stack tight" }, h("span", { class: "big" }, o.title, simulated ? " " : null, simulated ? simTag() : null), h("p", {}, message)));
}

/* "Device GPS ±12 m" / "Chosen on the map" / "Simulated ±8 m" */
export function locationSource(loc) {
  if (loc.source === "USER_SELECTED_PIN") return h("span", { class: "chip review" }, icon("pin", 14), "Chosen on the map: not verified GPS");
  if (loc.mode === "SIMULATED") return h("span", { class: "row", style: { gap: "6px" } }, simTag(), h("span", { class: "muted" }, `±${Math.round(loc.accuracy_m)} m`));
  return h("span", { class: "chip pass" }, icon("crosshair", 14), loc.accuracy_m ? `Device GPS ±${Math.round(loc.accuracy_m)} m` : "Device GPS");
}

export const flagChips = (flags) => (flags || []).length
  ? h("div", { class: "row wrap", style: { gap: "6px" } }, flags.map((f) => h("span", { class: "chip review" }, FLAG_TEXT[f] || label(f))))
  : null;

/* The honest timing line: how far apart the photo and the location reading were. */
export function timingLine(capturedAt, observedAt, source) {
  if (source === "GALLERY") return "This photo came from the gallery. The location is where you are now, not where it was taken.";
  if (source === "CAMERA_INPUT") return "Photo taken in your camera app; location read right after you chose it.";
  if (!capturedAt || !observedAt) return null;
  const diff = (new Date(observedAt) - new Date(capturedAt)) / 1000;
  const when = Math.abs(diff) < 1 ? "at about the same moment as the photo" : `${Math.abs(Math.round(diff))} s ${diff < 0 ? "before" : "after"} the photo`;
  return `Photo ${new Date(capturedAt).toLocaleTimeString()} · location read ${when}.`;
}

export function distanceFacts(distance, accuracy, radius) {
  return h("div", { class: "facts" },
    h("div", {}, h("span", { class: "lbl" }, "Distance"), h("strong", {}, fmtM(distance))),
    h("div", {}, h("span", { class: "lbl" }, "GPS accuracy"), h("strong", {}, accuracy ? `±${Math.round(accuracy)} m` : "—")),
    h("div", {}, h("span", { class: "lbl" }, "Allowed radius"), h("strong", {}, `${radius} m`)));
}
