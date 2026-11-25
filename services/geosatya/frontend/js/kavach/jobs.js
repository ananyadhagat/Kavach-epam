/* Worker: jobs nobody has taken yet that match their skills and are close to the location they shared. */

import { api } from "../api.js";
import { availabilityCard } from "../live.js";
import { banner, button, card, clear, emptyState, fmtAgo, fmtM, h, icon, pageHead, toast } from "../ui.js";

export async function renderJobs(ctx) {
  const { main } = ctx;
  const [d, availability] = await Promise.all([api("/kavach/jobs/available"), availabilityCard(ctx)]);
  const claim = async (job) => {
    try {
      const r = await api(`/kavach/jobs/${encodeURIComponent(job.incident_id)}/claim`, { method: "POST" });
      toast("Job taken. Head to the location when you are ready.", "pass");
      location.hash = `#/tasks/${r.task_id}`;
    } catch (e) { toast(e.message, "fail"); ctx.rerender(); }
  };
  clear(main,
    pageHead({ title: "Available jobs", subtitle: `Open complaints within ${d.radius_km} km of your shared location that match your skills.`,
      right: [h("a", { class: "btn", href: "#/tasks" }, "My tasks")] }),
    availability,
    d.note ? banner("review", d.note) : null,
    d.jobs.length ? h("div", { class: "joblist" }, d.jobs.map((j) => h("div", { class: "job" },
      h("span", { class: "ico" }, icon(j.icon, 20)),
      h("div", { class: "grow" }, h("strong", {}, j.title), h("span", { class: "muted" }, `${j.category_label} · ${fmtM(j.distance_m)} away · reported ${fmtAgo(j.reported_at)}${j.work_minutes ? ` · about ${j.work_minutes} min of work` : ""}`)),
      button("Take this job", { class: "btn primary", onclick: () => claim(j) }, "check"))))
      : d.note ? null : card({}, emptyState("No open jobs near you", "New complaints that match your skills will appear here. Pull down or reopen this page to refresh.")));
}
