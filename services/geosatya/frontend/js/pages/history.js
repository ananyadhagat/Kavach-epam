import { api } from "../api.js";
import { card, clear, emptyState, fmtTime, h, label, pageHead } from "../ui.js";

export async function renderHistory({ main }) {
  const filter = h("input", { type: "search", id: "inc", placeholder: "Filter by incident number, e.g. GS-ABC123", "aria-label": "Incident number" });
  const body = h("div", {});
  const load = async () => {
    const q = filter.value.trim() ? `?incident_id=${encodeURIComponent(filter.value.trim())}` : "";
    const data = await api(`/evidence-history${q}`);
    clear(body, data.events.length ? h("div", { class: "table-wrap" }, h("table", { class: "list" },
      h("thead", {}, h("tr", {}, ["When", "Who", "What", "Incident", "Details"].map((t) => h("th", { scope: "col" }, t)))),
      h("tbody", {}, data.events.map((e) => h("tr", {},
        h("td", { class: "muted" }, fmtTime(e.time, true)), h("td", {}, e.actor), h("td", {}, h("strong", {}, label(e.action))),
        h("td", {}, e.incident_id ? h("a", { class: "mono", href: `#/incidents/${e.incident_id}` }, e.incident_id) : "—"),
        h("td", { class: "muted" }, Object.entries(e.details).filter(([, v]) => v != null && v !== "")
          .map(([k, v]) => `${label(k)}: ${Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : v}`).join(" · "))))))
    ) : emptyState("No events match"));
  };
  clear(main, pageHead({ title: "Evidence history", subtitle: "Every report, check, decision and correction, in order. Coordinates are never written here." }),
    card({}, h("form", { class: "row wrap", onsubmit: (e) => { e.preventDefault(); load(); } }, filter, h("button", { class: "btn primary", type: "submit" }, "Filter")), body));
  await load();
}
