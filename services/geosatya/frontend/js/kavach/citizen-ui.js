/* Citizen complaint progress (Reported -> Verified -> Assigned -> In progress -> Resolved) and feedback. */

import { api } from "../api.js";
import { banner, button, card, clear, fmtAgo, h, icon, toast } from "../ui.js";

const STAGES = [
  ["Reported", "We have your complaint and its location."],
  ["Verified", "The report was checked: its location was recorded and its details analysed."],
  ["Assigned", "A worker has taken the job."],
  ["In progress", "The worker is on the way or working."],
  ["Resolved", "The work is finished and its location was verified."],
];

/* How far a complaint has got (0-4). Matches the public tracking page. */
export function stageIndex(inc) {
  const byStatus = { SUBMITTED: 0, ASSIGNED: 2, IN_PROGRESS: 3, AWAITING_VERIFICATION: 3, RESOLVED: 4 }[inc.status] ?? 0;
  if (byStatus === 0 && inc.intelligence?.status === "COMPLETED") return 1;
  return byStatus;
}

export function complaintStages(inc) {
  const now = stageIndex(inc);
  return h("ol", { class: "cstages", "aria-label": `Complaint progress: ${STAGES[now][0]}` }, STAGES.map(([name, hint], i) =>
    h("li", { class: `${i < now ? "done" : ""} ${i === now ? "now" : ""}`, title: hint, "aria-current": i === now ? "step" : null },
      h("span", { class: "cs-dot" }, i < now || (i === now && now === 4) ? icon("check", 16) : String(i + 1)), h("span", { class: "cs-name" }, name))));
}

/* After resolution the reporter can rate how it was handled. */
export function feedbackCard(inc) {
  if (inc.status !== "RESOLVED") return null;
  const host = h("div", { class: "stack" }, h("div", { class: "skeleton", style: { height: "70px" } }));
  let rating = 0;
  const comment = h("textarea", { id: "fb-comment", maxlength: 500, rows: 3, placeholder: "Anything you want to tell us? (optional)" });
  const stars = h("div", { class: "stars", role: "radiogroup", "aria-label": "Rating" }, [1, 2, 3, 4, 5].map((n) =>
    h("button", { class: "star", type: "button", role: "radio", "aria-checked": "false", "aria-label": `${n} out of 5`, onclick: () => { rating = n; paint(); } }, icon("star", 30))));
  const paint = () => stars.querySelectorAll(".star").forEach((b, i) => { b.classList.toggle("on", i < rating); b.setAttribute("aria-checked", String(i + 1 === rating)); });
  const send = button("Send feedback", { class: "btn primary", onclick: async () => {
    if (!rating) { toast("Choose a rating from 1 to 5 stars.", "fail"); return; }
    try { const r = await api(`/kavach/incidents/${inc.incident_id}/feedback`, { method: "POST", json: { rating, comment: comment.value } }); toast("Thank you for your feedback", "pass"); show(r); }
    catch (e) { toast(e.message, "fail"); }
  } });
  const show = (r) => {
    const f = r.feedback;
    if (!r.can_give && !f) { clear(host); host.closest("section")?.remove(); return; }
    rating = f?.rating || 0;
    clear(host, f ? h("div", { class: "stack tight" }, h("div", { class: "row" }, h("strong", {}, "Your feedback"), h("span", { class: "muted" }, fmtAgo(f.created_at))),
      f.comment ? h("p", { class: "muted", style: { margin: 0 } }, `“${f.comment}”`) : null) : null,
      r.can_give ? [stars, comment, h("div", {}, send)] : null);
    paint();
  };
  api(`/kavach/incidents/${inc.incident_id}/feedback`).then(show).catch((e) => clear(host, banner("fail", e.message)));
  return card({}, h("h2", {}, "How did we do?"), h("p", { class: "muted", style: { margin: 0 } }, "Your complaint is resolved. Tell us how it went."), host);
}
