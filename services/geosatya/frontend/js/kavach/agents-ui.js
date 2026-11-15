/* Team agents card (staff): Duplicate Detection, Supervisor and Sanitation
   results for one incident, with who built each agent. Advisory only. */

import { api } from "../api.js";
import { banner, button, card, chip, clear, fmtAgo, fmtTime, h, icon, kv, label, toast } from "../ui.js";

const NAMES = { DUPLICATE_DETECTION: "Duplicate Detection", SUPERVISOR: "Supervisor", SANITATION: "Sanitation Planning", VERIFICATION: "Visual verification" };
const ICONS = { DUPLICATE_DETECTION: "copy", SUPERVISOR: "review", SANITATION: "trash", VERIFICATION: "camera" };
const V_TONE = { PASS: "PASS", FAIL: "FAIL", INCONCLUSIVE: "REVIEW_REQUIRED", MANUAL_REVIEW: "REVIEW_REQUIRED" };
const STATUS_TONE = { COMPLETED: "PASS", UNAVAILABLE: "REVIEW_REQUIRED", REJECTED: "FAIL", FAILED: "FAIL" };
const STATUS_TEXT = { COMPLETED: "Done", UNAVAILABLE: "Agent unavailable", REJECTED: "Input rejected", FAILED: "Failed",
  NOT_APPLICABLE: "Not applicable", NOT_CONFIGURED: "Not connected", NOT_RUN: "Not run yet" };

function body(a) {
  const s = a.summary;
  if (!s) return h("p", { class: "muted" }, a.error || (a.status === "NOT_CONFIGURED" ? "This server isn't connected to the agent." : STATUS_TEXT[a.status]));
  if (a.agent === "DUPLICATE_DETECTION") {
    return [kv([["Decision", chip(s.decision === "DUPLICATE" ? "REVIEW_REQUIRED" : s.decision === "NEW" ? "PASS" : "REVIEW_REQUIRED", label(s.decision))],
      ["Similarity", s.score != null ? `${Math.round(s.score * 100)}%` : "—"],
      ["Matches", s.matched_incident_id ? h("a", { href: `#/incidents/${s.matched_incident_id}`, class: "mono" }, s.matched_incident_id)
        : s.matched_elsewhere ? "A similar public report handled by another team" : "None"],
      ["Why", (s.reasons || []).map(label).join(", ") || "—"]])];
  }
  if (a.agent === "SUPERVISOR") {
    return [kv([["Department", label(s.department)], ["Priority", s.priority], ["Decision", chip(s.decision_status === "APPROVED_TO_PROCEED" ? "PASS" : "REVIEW_REQUIRED", label(s.decision_status))],
      ["Ward / route", s.ward && s.ward !== "UNRESOLVED_WARD" ? label(s.ward) : "Not resolved"],
      ["Respond by", s.response_deadline ? fmtTime(s.response_deadline) : "—"], ["Resolve by", s.resolution_deadline ? fmtTime(s.resolution_deadline) : "—"],
      ["Dispatch eligible", s.dispatch_eligible ? "Yes" : "No (advisory)"], ["Mode", s.mode === "mock" ? "Offline rules (no AI call)" : s.mode || "—"]]),
    s.rationale ? h("p", { class: "hint" }, s.rationale) : null];
  }
  if (a.agent === "VERIFICATION") {
    return [kv([["Result", chip(V_TONE[s.verification_status] || "", label(s.verification_status))],
      ["Score", s.score != null ? `${Math.round(s.score)} / 100${s.confidence != null ? ` · confidence ${Math.round(s.confidence)}%` : ""}` : "Not available"],
      ["Photos used", `${s.before_photos} before · ${s.after_photos} after`], ["GPS", s.gps_passed_on ? "Completion fix checked" : "No live fix passed on"],
      ["Before/after alignment", label(s.alignment || "—")], ["Vision", s.mode], ["Attempt", s.attempt]]),
    h("ul", { class: "plain" }, (s.remarks || []).map((r) => h("li", {}, r))),
    h("p", { class: "hint" }, "Runs on the real photos and GPS. Offline mode checks quality, alignment and location; whether the work is done needs AI vision or a person.")];
  }
  return [kv([["Plan", h("span", { class: "mono" }, s.plan_id)], ["Template", label(s.template)], ["Status", label(s.planning_status)],
    ["On hold for", (s.hold_reason_codes || []).map(label).join(", ") || "Nothing"]]),
  s.tasks?.length ? h("ol", { class: "plain" }, s.tasks.map((t) => h("li", {}, h("strong", {}, t.title),
    h("span", { class: "muted" }, ` · ${t.minutes != null ? `${t.minutes} min` : "time needs more data"}${t.resources?.length ? ` · ${t.resources.map(label).join(", ")}` : ""}`)))) : null,
  h("p", { class: "hint" }, s.adapter_note)];
}

export function teamAgentsCard(inc, { only = null, title = "Team agents" } = {}) {
  const host = h("div", { class: "stack" }, h("div", { class: "skeleton", style: { height: "90px" } }));
  const draw = (data) => clear(host,
    data.agents.filter((a) => !only || only.includes(a.agent)).filter((a) => !only || a.status !== "NOT_APPLICABLE").map((a) => h("div", { class: "stack tight", style: { padding: "12px 0", borderBottom: "1px solid var(--line)" } },
      h("div", { class: "row between wrap" }, h("div", { class: "row" }, h("span", { class: "ico" }, icon(ICONS[a.agent], 18)),
        h("div", { class: "stack tight" }, h("strong", {}, NAMES[a.agent]), h("span", { class: "hint" }, `Built by ${a.owner}${a.updated_at ? ` · ${fmtAgo(a.updated_at)}` : ""}`))),
      chip(STATUS_TONE[a.status] || "", STATUS_TEXT[a.status] || label(a.status))), body(a))));
  const load = () => api(`/kavach/incidents/${inc.incident_id}/agents`).then(draw).catch((e) => clear(host, banner("fail", e.message)));
  load();
  return card({}, h("div", { class: "row between wrap" }, h("h2", {}, title),
    button("Run again", { class: "btn small", onclick: async () => {
      try { draw(await api(`/kavach/incidents/${inc.incident_id}/agents/retry`, { method: "POST" })); toast("Agents re-run", "pass"); }
      catch (e) { toast(e.message, "fail"); }
    } }, "refresh")),
  h("p", { class: "hint" }, "Advice from the team's agents. It never changes the report, the location check or the assignment."), host);
}

export async function agentStatus() {
  try { return (await api("/kavach/agents/status")).agents; } catch { return []; }
}
