/* Supervisor dispatch board: open incidents with assignment phase, tracking
   freshness, ETA/ETR and what needs attention. Actions stay on the incident page. */

import { api } from "../api.js";
import { button, card, chip, clear, demoTag, emptyState, fmtAgo, h, label } from "../ui.js";
import { viewSwitch } from "./livemap.js";

const FLAG = {
  UNASSIGNED: ["fail", "Unassigned"], ACCEPTANCE_OVERDUE: ["fail", "Not accepted in time"], TRACKING_STALE: ["review", "Tracking stale"],
  WORKER_STATIONARY: ["review", "Worker not moving"], ETR_OVERDUE: ["review", "Past estimate"], AWAITING_EVIDENCE: ["review", "Awaiting rework"],
  AWAITING_REVIEW: ["info", "Awaiting review"],
};
const mins = (m) => (m == null ? "—" : m < 60 ? `${Math.round(m)} min` : `${Math.floor(m / 60)} h ${Math.round(m % 60)} min`);

export async function renderBoard({ main, onCleanup }) {
  let filter = null;
  const body = h("div", { class: "stack" });
  const draw = (b) => {
    const rows = b.incidents.filter((r) => !filter || r.flags.includes(filter));
    clear(body,
      h("div", { class: "row wrap" }, button(`All (${b.incidents.length})`, { class: `btn small ${filter ? "" : "primary"}`, onclick: () => { filter = null; draw(b); } }),
        Object.entries(b.counts).filter(([, n]) => n).map(([f, n]) => button(`${FLAG[f][1]} (${n})`, { class: `btn small ${filter === f ? "primary" : ""}`, onclick: () => { filter = f; draw(b); } }))),
      rows.length ? h("div", { class: "table-wrap" }, h("table", { class: "mini board" },
        h("tr", {}, ["Incident", "Priority", "Phase", "Worker", "Tracking", "ETA", "ETR", "Verification", "Needs attention"].map((x) => h("th", {}, x))),
        rows.map((r) => h("tr", {},
          h("td", {}, h("a", { href: `#/incidents/${r.incident_id}` }, h("strong", {}, r.title)), h("div", { class: "muted mono" }, r.incident_id, " ", r.is_demo ? demoTag() : null), h("div", { class: "muted" }, r.category_label)),
          h("td", {}, h("span", { class: `chip ${r.priority === "HIGH" ? "fail" : r.priority === "MEDIUM" ? "review" : ""}` }, r.priority)),
          h("td", {}, r.phase_text, r.since_assigned_min != null ? h("div", { class: "muted" }, `assigned ${mins(r.since_assigned_min)} ago`) : null,
            r.in_progress_min != null ? h("div", { class: "muted" }, `working ${mins(r.in_progress_min)}`) : null),
          h("td", {}, r.worker_name || "—", r.worker_available === false ? h("div", { class: "muted" }, "unavailable") : null),
          h("td", {}, r.tracking_active ? (r.tracking_stale ? "Stale" : "Live") : "Off", r.last_location_age_s != null ? h("div", { class: "muted" }, `${mins(r.last_location_age_s / 60)} ago`) : null),
          h("td", {}, r.eta ? (r.eta.minutes_low != null && r.eta.state === "AVAILABLE" ? `≈ ${r.eta.minutes_low}–${r.eta.minutes_high} min` : label(r.eta.state)) : "—"),
          h("td", {}, r.etr.state === "ESTIMATED" ? `≈ ${mins(r.etr.remaining_min)}` : label(r.etr.state)),
          h("td", {}, r.verification_outcome ? chip(r.verification_outcome) : "—", r.review_decision ? h("div", {}, chip(r.review_decision)) : null),
          h("td", {}, h("div", { class: "row wrap", style: { gap: "4px" } }, r.flags.map((f) => h("span", { class: `chip ${FLAG[f][0]}` }, FLAG[f][1]))))))))
        : card({}, emptyState("Nothing here", filter ? "No incident has this flag." : "No incidents yet.")),
      h("p", { class: "hint" }, `Updated ${fmtAgo(b.generated_at)} · refreshes every 30 s · acceptance timeout ${b.acceptance_timeout_min} min. ETA is approximate (straight line); open an incident to assign, reassign, cancel or review.`));
  };
  const load = async () => { if (document.visibilityState !== "hidden") draw(await api("/dispatch/board")); };
  clear(main, h("header", { class: "page-head" }, h("div", { class: "stack tight" }, viewSwitch("board"), h("h1", {}, "Dispatch board"),
    h("p", { class: "muted" }, "Every open incident, its assignment and what needs attention."))), body);
  await load();
  const timer = setInterval(() => load().catch(() => {}), 30000);
  onCleanup(() => clearInterval(timer));
}
