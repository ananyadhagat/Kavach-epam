/* Profile (every role), Share my location (workers) and Available workers (supervisors). */

import { api, session, signOut } from "../api.js";
import { availabilityCard } from "../live.js";
import { button, card, chip, clear, emptyState, fmtAgo, fmtTime, h, icon, kv, label, pageHead } from "../ui.js";
import { ROLE_INFO, roleKey } from "./brand.js";

export async function renderProfile({ main }) {
  const me = await api("/auth/me").catch(() => ({ ...session.me, permissions: [] }));
  const info = ROLE_INFO[roleKey(me)] || ROLE_INFO.CITIZEN;
  clear(main, pageHead({ title: "Profile", subtitle: "Your account and what it can do." }),
    card({}, h("div", { class: "row wrap", style: { gap: "14px" } }, h("span", { class: "join-ico" }, icon(info.icon, 24)),
      h("div", { class: "stack tight grow" }, h("h2", {}, me.display_name), h("span", { class: "muted" }, info.label))),
      kv([["Signed in with", me.login || "Demo identity (development only)"], ["Last sign-in", me.last_login_at ? fmtTime(me.last_login_at) : "—"],
        ["Workspace", session.ctx?.workspace?.name || "Open civic platform"]])),
    me.permissions?.length ? card({}, h("h2", {}, "What you can do"), h("ul", { class: "perm-list" }, me.permissions.map((p) => h("li", {}, icon("check", 15), p))),
      h("p", { class: "hint" }, "The server checks your role on every request. Anything else is refused, whatever the screen shows.")) : null,
    card({}, h("h2", {}, "Sign out"), h("p", { class: "muted" }, "Signs you out on every device where you are signed in."),
      h("div", {}, button("Sign out", { class: "btn", onclick: () => signOut() }, "logout"))));
}

export async function renderShareLocation(ctx) {
  clear(ctx.main, pageHead({ title: "Share my location", subtitle: "One reading when you press the button, so dispatch can offer you nearby jobs. It is not tracking." }),
    await availabilityCard(ctx),
    card({}, h("h2", {}, "During a job"), h("p", { class: "muted" }, "Open the task and press Start journey: your location is shared while you travel to the spot and stops when you submit the completion photo."),
      h("div", {}, h("a", { class: "btn", href: "#/tasks" }, icon("tasks", 17), "My tasks"))));
}

export async function renderWorkersList({ main }) {
  const workers = await api("/workers");
  const free = workers.filter((w) => w.available && w.active_tasks < w.max_active_tasks);
  const where = (w) => w.location_note || (w.location_age_s == null ? "Location not shared"
    : `Location shared ${fmtAgo(new Date(Date.now() - w.location_age_s * 1000).toISOString())}${w.location_fresh ? "" : " · too old for dispatch"}`);
  const initials = (n) => String(n || "?").replace(/\(.*\)/, "").trim().split(/\s+/).map((x) => x[0]).join("").slice(0, 2).toUpperCase();
  const row = (w, i) => {
    const ready = free.includes(w);
    const el = h("article", { class: `wcard2 glass${ready ? " eligible" : ""}`, style: { "--i": i } },
      h("div", { class: "wc-top" },
        h("span", { class: "wc-av" }, initials(w.name), h("i", { class: `wc-dot ${w.available ? "on" : "off"}` })),
        h("div", { class: "wc-id" }, h("strong", {}, w.name), h("small", {}, where(w))),
        h("span", { class: `wc-badge ${ready ? "ok" : w.available ? "no" : "off"}` }, ready ? "Can take a task" : w.available ? "At capacity" : "Unavailable")),
      h("dl", { class: "wc-facts" },
        h("div", {}, h("dt", {}, "Workload"), h("dd", {}, `${w.active_tasks}/${w.max_active_tasks}`, h("span", { class: "wc-load" }, h("i", { style: { width: `${Math.min(100, (100 * w.active_tasks) / Math.max(1, w.max_active_tasks))}%` } })))),
        h("div", {}, h("dt", {}, "Location"), h("dd", {}, w.location_fresh ? "Fresh" : w.location_age_s == null ? "None" : "Old")),
        h("div", {}, h("dt", {}, "Status"), h("dd", {}, w.available ? "On duty" : "Off duty"))),
      (w.skills || []).length ? h("div", { class: "wc-skills" }, w.skills.map((x) => h("span", { class: "wc-skill" }, label(x)))) : h("p", { class: "hint" }, "No skills set"));
    return el;
  };
  clear(main, pageHead({ title: "Available workers", subtitle: `${free.length} of ${workers.length} can take a new task now. To allocate one to a complaint, open the complaint and use “Find a worker”.`,
    right: [h("a", { class: "btn", href: "#/board" }, icon("alert", 17), "Active complaints"), h("a", { class: "btn primary", href: "#/" }, icon("live", 17), "Live map")] }),
  workers.length ? h("div", { class: "ws-grid" }, [...free, ...workers.filter((w) => !free.includes(w))].map(row))
    : card({}, emptyState("No workers yet", "Workers appear here after they register with the worker access code.")));
}
