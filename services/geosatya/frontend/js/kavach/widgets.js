/* Shared KAVACH form widgets: a map point picker and a report location
   control (device GPS first, a labelled map pin as the fallback). */

import { createMap } from "../maps.js";
import { DEMO_CENTER, LOCATION_BLOCKED_HELP, locate, simulatedFix, simulationOn } from "../capture.js";
import { button, clear, fmtCoord, h, icon } from "../ui.js";

/* Click the map to choose a point; optional radius circle. */
export function pointPicker({ center, radius = null, kind = "area", label = "Click the map to set the location", onChange } = {}) {
  const mapEl = h("div", { class: "map", style: { height: "300px", borderRadius: "14px" }, role: "application", "aria-label": label });
  const info = h("span", { class: "hint" }, label);
  const state = { point: center || null, radius };
  let map = null;
  const draw = () => {
    if (!map || !state.point) return;
    map.marker("p", "pin", state.point, "Selected location");
    if (state.radius) map.circle("r", state.point, state.radius, kind);
    info.textContent = `Selected: ${fmtCoord(state.point[0], state.point[1])}${state.radius ? ` · radius ${state.radius >= 1000 ? `${state.radius / 1000} km` : `${state.radius} m`}` : ""}`;
  };
  const useMine = button("Use my location", { class: "btn small", onclick: async () => {
    const fix = await locate();
    if (fix.status !== "ok") { info.textContent = fix.message; return; }
    state.point = [fix.latitude, fix.longitude]; map?.setView(state.point, 15); draw(); onChange?.(state);
  } }, "crosshair");
  const el = h("div", { class: "stack", style: { gap: "8px" } }, mapEl, h("div", { class: "row between wrap" }, info, useMine));
  const mount = async () => {
    map = await createMap(mapEl, { center: state.point || DEMO_CENTER, zoom: state.point ? 14 : 12,
      onClick: (ll) => { state.point = ll; draw(); onChange?.(state); } });
    draw();
    return map;
  };
  return { el, state, mount, setRadius: (r) => { state.radius = r; draw(); }, destroy: () => map?.destroy() };
}

/* Where the problem is. Device GPS first (with accuracy), a map pin otherwise.
   Returns { el, mount, value() } where value() is the payload fields. */
export function reportLocation({ hint } = {}) {
  const state = { device: null, error: null, pin: null };
  const status = h("div", { class: "loc-card" });
  const mapEl = h("div", { class: "map", style: { height: "280px", borderRadius: "14px" }, role: "application", "aria-label": "Map: tap to choose the spot" });
  let map = null;
  const draw = () => {
    const d = state.device;
    if (d) {
      clear(status, icon("crosshair", 22), h("div", { class: "stack tight" },
        h("strong", {}, d.mode === "SIMULATED" ? "Simulated location (testing only)" : "Your device location is attached"),
        h("span", { class: "muted" }, `${fmtCoord(d.latitude, d.longitude)} · accuracy ±${Math.round(d.accuracy_m)} m`),
        state.pin ? h("span", { class: "hint" }, "You also moved the pin. The device location stays the primary location; the pin is kept as a labelled note.") : null));
      status.className = `loc-card ${d.accuracy_m > 50 ? "warn" : "ok"}`;
    } else if (state.pin) {
      clear(status, icon("pin", 22), h("div", { class: "stack tight" }, h("strong", {}, "Using the spot you chose on the map"),
        h("span", { class: "muted" }, `${fmtCoord(state.pin[0], state.pin[1])} · this is marked as a user-selected location`)));
      status.className = "loc-card warn";
    } else {
      clear(status, icon("pin", 22), h("div", { class: "stack tight" }, h("strong", {}, state.error ? "Location not available" : "Getting your location…"),
        h("span", { class: "muted" }, state.error || "Allow location when your browser asks. You can also tap the map.")));
      status.className = `loc-card ${state.error ? "bad" : ""}`;
    }
    if (map) {
      if (d) { map.marker("d", d.mode === "SIMULATED" ? "simulated" : "me", [d.latitude, d.longitude], "Your device location"); map.circle("acc", [d.latitude, d.longitude], d.accuracy_m, d.mode === "SIMULATED" ? "simulated" : "me"); }
      if (state.pin) map.marker("p", "pin", state.pin, "Selected spot"); else map.remove("p");
    }
  };
  const retry = button("Retry location", { class: "btn small", onclick: () => capture() }, "refresh");
  const capture = async () => {
    state.error = null; draw();
    const fix = simulationOn() ? simulatedFix(DEMO_CENTER) : await locate();
    if (fix.status === "ok") { state.device = fix; draw(); map?.fit([[fix.latitude, fix.longitude]]); }
    else { state.error = fix.code === "PERMISSION_DENIED" ? LOCATION_BLOCKED_HELP : fix.message; state.errorCode = fix.code; draw(); }
  };
  const el = h("div", { class: "stack", style: { gap: "10px" } }, status, mapEl,
    h("div", { class: "row between wrap" }, h("span", { class: "hint" }, hint || "Tap the map to place a pin if your location is off or unavailable."), retry));
  return {
    el, state,
    async mount(center) {
      map = await createMap(mapEl, { center: center || DEMO_CENTER, zoom: 15, onClick: (ll) => { state.pin = ll; draw(); } });
      draw();
      capture();
      return map;
    },
    ready: () => !!(state.device || state.pin),
    value() {
      const d = state.device;
      return {
        device_location: d ? { latitude: d.latitude, longitude: d.longitude, accuracy_m: d.accuracy_m, observed_at: d.observed_at, mode: d.mode } : null,
        device_location_error: d ? null : (state.errorCode || "POSITION_UNAVAILABLE"),
        user_location: state.pin ? { latitude: state.pin[0], longitude: state.pin[1] } : null,
      };
    },
    point: () => (state.device ? [state.device.latitude, state.device.longitude] : state.pin),
    destroy: () => map?.destroy(),
  };
}

export const field = (labelText, control, hintText, cls = "") => h("label", { class: `field ${cls}` }, labelText, control, hintText ? h("span", { class: "hint" }, hintText) : null);
export const select = (id, options, value, attrs = {}) => h("select", { id, ...attrs }, options.map(([v, t]) => h("option", { value: v, selected: v === value }, t)));
