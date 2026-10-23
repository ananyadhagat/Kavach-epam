import { api, session } from "../api.js";
import { mapProviderName } from "../maps.js";
import { banner, button, card, clear, h, kv, pageHead, toast } from "../ui.js";

export async function renderSettings(ctx) {
  const { main, rerender } = ctx;
  const cfg = session.config, ranges = cfg.limit_ranges;
  const limits = await api("/settings");
  const radius = h("input", { type: "range", id: "radius", min: ranges.geofence_radius_m[0], max: ranges.geofence_radius_m[1], step: 1, value: limits.geofence_radius_m });
  const acc = h("input", { type: "range", id: "acc", min: ranges.max_accuracy_m[0], max: ranges.max_accuracy_m[1], step: 5, value: limits.max_accuracy_m });
  const rText = h("strong", {}, `${limits.geofence_radius_m} m`), aText = h("strong", {}, `±${limits.max_accuracy_m} m`);
  radius.addEventListener("input", () => { rText.textContent = `${radius.value} m`; });
  acc.addEventListener("input", () => { aText.textContent = `±${acc.value} m`; });

  clear(main, pageHead({ title: "Settings", subtitle: "Location rules and environment." }),
    h("div", { class: "grid halves" },
      card({}, h("h2", {}, "Geofence"),
        h("p", { class: "muted" }, "A worker's reported position must be within this radius of the incident. It's a business rule, not a promise that GPS is this precise."),
        h("label", { class: "field", for: "radius" }, h("span", { class: "row between" }, "Allowed radius", rText), radius,
          h("span", { class: "hint" }, `${ranges.geofence_radius_m[0]}–${ranges.geofence_radius_m[1]} m`)),
        h("label", { class: "field", for: "acc" }, h("span", { class: "row between" }, "Weakest GPS accuracy accepted", aText), acc,
          h("span", { class: "hint" }, "Readings weaker than this are never treated as a pass; they go to a supervisor.")),
        button("Save", { class: "btn primary", onclick: async () => {
          try { session.config.limits = await api("/settings", { method: "PUT", json: { geofence_radius_m: Number(radius.value), max_accuracy_m: Number(acc.value) } });
            toast("Saved. New checks use these values.", "pass"); } catch (e) { toast(e.message, "fail"); }
        } }, "check")),
      card({}, h("h2", {}, "Environment"),
        kv([["Map", mapProviderName()], ["Sign-in", cfg.auth_mode === "demo" ? "Demo roles (no sign-in)" : "Token"], ["Mode", cfg.environment],
          ["Simulated GPS", cfg.simulation_allowed ? (cfg.simulated_may_pass ? "Allowed; can pass in demo" : "Allowed; never passes") : "Refused"]]),
        cfg.maps.provider !== "google" ? banner("info", "Set GOOGLE_MAPS_BROWSER_KEY in .env to use Google Maps. Without it, OpenStreetMap is used and everything still works.") : null,
        cfg.auth_mode === "demo" ? button("Reset demo data", { class: "btn danger", onclick: async () => {
          if (!confirm("Delete every report, task and photo record in the local database and reload the demo data?")) return;
          try { await api("/demo/reset", { method: "POST" }); toast("Demo data reset", "pass"); location.hash = "#/"; rerender(); } catch (e) { toast(e.message, "fail"); }
        } }, "refresh") : null)));
}
