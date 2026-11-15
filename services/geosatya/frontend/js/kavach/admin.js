/* Platform administration: tenants (counts and verification only, never a
   tenant's incidents or locations), plans and authority jurisdictions. */

import { api, session } from "../api.js";
import { banner, button, card, chip, clear, demoTag, emptyState, fmtTime, h, icon, label, pageHead, toast } from "../ui.js";
import { field, pointPicker, select } from "./widgets.js";

const VTONE = { VERIFIED: "PASS", PENDING: "REVIEW_REQUIRED", REJECTED: "FAIL", UNVERIFIED: "", DEMO: "SIMULATED" };

export async function renderAdmin(ctx) {
  const { main, onCleanup } = ctx;
  const o = await api("/kavach/admin/overview");
  const cat = session.catalog ||= await api("/kavach/catalog");
  const orgs = o.workspaces.filter((w) => w.kind === "ORGANIZATION"), events = o.workspaces.filter((w) => w.kind === "EVENT");
  const decide = async (w, status) => {
    const note = status === "REJECTED" ? prompt("Reason for rejecting (saved in the audit log):") : "";
    if (status === "REJECTED" && !note) return;
    try { await api(`/kavach/admin/workspaces/${w.workspace_id}/verification`, { method: "POST", json: { status, note: note || "" } }); toast(`${w.name}: ${label(status)}`, "pass"); ctx.rerender(); }
    catch (ex) { toast(ex.message, "fail"); }
  };
  const wsRow = (w) => h("tr", {}, h("td", {}, h("strong", {}, w.name), h("div", { class: "muted" }, `${w.category_label} · owner ${w.owner_name || "—"}`), w.is_demo ? demoTag() : null),
    h("td", {}, w.kind === "ORGANIZATION" ? chip(VTONE[w.verification_status], label(w.verification_status)) : h("span", { class: "chip" }, label(w.phase || ""))),
    h("td", {}, `${w.workers} / ${w.supervisors}`), h("td", {}, `${w.incidents.open} open · ${w.incidents.resolved} resolved`),
    h("td", {}, w.plan?.name || "—", h("div", { class: "muted" }, label(w.subscription_status))),
    h("td", {}, w.kind === "ORGANIZATION" && w.verification_status !== "DEMO" ? h("div", { class: "row wrap", style: { gap: "6px" } },
      w.verification_status !== "VERIFIED" ? button("Verify", { class: "btn small", onclick: () => decide(w, "VERIFIED") }, "check") : null,
      w.verification_status !== "REJECTED" ? button("Reject", { class: "btn small danger", onclick: () => decide(w, "REJECTED") }) : null,
      w.verification_note ? h("div", { class: "hint", style: { width: "100%" } }, `Submitted: ${w.verification_note}`) : null) : null));
  const table = (rows) => rows.length ? h("div", { class: "table-wrap" }, h("table", { class: "list" },
    h("thead", {}, h("tr", {}, ["Workspace", "Status", "Workers / supervisors", "Incidents", "Plan", ""].map((t) => h("th", {}, t)))), h("tbody", {}, rows.map(wsRow)))) : emptyState("None yet");

  // Authority editor
  const aName = h("input", { type: "text", id: "a-name", required: true, minlength: 3, maxlength: 160 });
  const aKind = select("a-kind", [["MUNICIPAL", "Municipal"], ["STATE_HIGHWAY", "State highway"], ["NATIONAL_HIGHWAY", "National highway"], ["UTILITY", "Utility"], ["OTHER", "Other"]], "MUNICIPAL");
  const aRadius = h("input", { type: "number", id: "a-rad", min: 0.5, max: 2000, step: 0.5, value: 10 });
  const aWs = select("a-ws", [["", "Not on Kavach (manual forwarding)"], ...orgs.map((w) => [w.workspace_id, w.name])], "");
  const aRoads = h("div", { class: "choice-grid" }, cat.road_types.filter((r) => r.id !== "UNKNOWN").map((r) => h("label", { class: "choice" }, h("input", { type: "checkbox", value: r.id }), r.label)));
  const aCats = h("div", { class: "choice-grid" }, cat.categories.filter((c) => c.scope !== "event").map((c) => h("label", { class: "choice" }, h("input", { type: "checkbox", value: c.id }), c.label)));
  const aNote = h("input", { type: "text", id: "a-note", maxlength: 200, placeholder: "Where this boundary came from" });
  const picker = pointPicker({ radius: 10000, label: "Click the centre of the jurisdiction" });
  aRadius.addEventListener("input", () => picker.setRadius(Number(aRadius.value) * 1000));

  clear(main, pageHead({ title: "Kavach platform", subtitle: "Tenants, verification, plans and public-authority jurisdictions" }),
    banner("info", "Platform administration shows tenant counts only. A tenant's incidents, workers' locations and evidence stay private to that tenant."),
    h("div", { class: "kpis" },
      ...[["Organizations", orgs.length, "building", "blue"], ["Events", events.length, "calendar", "violet"],
        ["Pending verification", orgs.filter((w) => w.verification_status === "PENDING").length, "review", "amber"],
        ["Public civic reports", o.civic_incidents, "alert", "green"]].map(([t, n, ic, tone]) =>
        h("div", { class: `kpi ${tone}` }, h("span", { class: "kico" }, icon(ic, 20)), h("strong", {}, String(n)), h("span", { class: "lbl" }, t)))),
    card({}, h("h2", {}, "Organizations"), table(orgs)),
    card({}, h("h2", {}, "Events"), table(events)),
    card({}, h("h2", {}, "Users by role"), h("div", { class: "facts" }, Object.entries(o.users).map(([r, n]) => h("div", {}, h("span", { class: "muted" }, label(r)), h("strong", {}, String(n)))))),
    card({}, h("h2", {}, "Plans"), h("p", { class: "muted" }, "Limits are enforced (workers, events). Prices are not set until the commercial model is confirmed; no payment gateway is connected."),
      h("div", { class: "grid stats" }, o.plans.map((p) => h("div", { class: "feature" }, h("strong", {}, p.name), h("span", { class: "muted" }, `${label(p.audience)} · ${label(p.billing_basis)}`),
        h("span", {}, `Workers: ${p.max_workers ?? "unlimited"} · Events: ${p.max_events ?? "unlimited"}`), h("span", { class: "chip" }, p.price))))),
    h("div", { class: "grid two" },
      card({}, h("h2", {}, "Authority jurisdictions"), h("p", { class: "muted" }, "Used to suggest the responsible authority for a public report. Kavach has no official integration with any government system."),
        o.authorities.length ? h("div", {}, o.authorities.map((a) => h("div", { class: "member-row" }, h("span", { class: "ico" }, icon("building", 18)),
          h("div", { class: "stack tight" }, h("strong", {}, a.name, " ", a.is_demo ? demoTag() : null),
            h("span", { class: "muted" }, `${label(a.kind)} · ${a.radius_km} km${a.road_types.length ? ` · ${a.road_types.map(label).join(", ")}` : ""}${a.categories.length ? ` · ${a.categories.length} categories` : " · all categories"}`),
            h("span", { class: "hint" }, a.on_kavach ? "Reports are routed to its Kavach workspace." : "Not on Kavach: reports are suggested and forwarded manually."), a.data_note ? h("span", { class: "hint" }, a.data_note) : null),
          button("Remove", { class: "btn small danger", onclick: async () => {
            if (!confirm(`Remove ${a.name}? Existing reports keep their suggestion.`)) return;
            await api(`/kavach/admin/authorities/${a.authority_id}`, { method: "DELETE" }); toast("Removed", "pass"); ctx.rerender();
          } })))) : emptyState("No authorities configured")),
      card({}, h("h2", {}, "Add an authority"), h("form", { class: "stack", onsubmit: async (e) => {
        e.preventDefault();
        const p = picker.state.point;
        if (!p) { toast("Click the map to set the centre", "fail"); return; }
        try {
          await api("/kavach/admin/authorities", { method: "POST", json: { name: aName.value, kind: aKind.value, center_latitude: p[0], center_longitude: p[1],
            radius_km: Number(aRadius.value), workspace_id: aWs.value || null, data_note: aNote.value || null,
            road_types: [...aRoads.querySelectorAll("input:checked")].map((i) => i.value), categories: [...aCats.querySelectorAll("input:checked")].map((i) => i.value) } });
          toast("Authority added", "pass"); ctx.rerender();
        } catch (ex) { toast(ex.message, "fail"); }
      } }, h("div", { class: "form-grid" }, field("Name", aName), field("Type", aKind), field("Radius (km)", aRadius), field("Kavach workspace", aWs)),
      picker.el, h("span", { class: "lbl" }, "Only these road types (none = any)"), aRoads, h("span", { class: "lbl" }, "Only these categories (none = all)"), aCats,
      field("Boundary source", aNote), h("div", {}, h("button", { class: "btn primary", type: "submit" }, "Add authority"))))),
    h("p", { class: "muted" }, `Generated ${fmtTime(new Date().toISOString())}`));
  await picker.mount();
  onCleanup(() => picker.destroy());
}
