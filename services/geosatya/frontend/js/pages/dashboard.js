import { cachedGet, firstUser, session, switchUser } from "../api.js";
import { categoryIcon } from "../components.js";
import { availabilityCard } from "../live.js";
import { renderLiveDashboard } from "./livemap.js";
import { banner, button, card, chip, clear, demoTag, emptyState, fmtAgo, h, icon, toast } from "../ui.js";

const COPY = {
  CITIZEN: { title: "See something broken? Report it in seconds.", text: "Take a photo and your location is attached automatically. We turn it into a task for a field worker.", cta: ["Report an issue", "#/report", "camera"] },
  WORKER: { title: "Your tasks, verified on the ground.", text: "Open a task, go to the marked spot, and take the completion photo there. We check you're really at the location.", cta: ["Open my tasks", "#/tasks", "tasks"] },
  SUPERVISOR: { title: "Review what the checks couldn't settle.", text: "Evidence that passed is one click to approve. Anything uncertain shows the distance, accuracy and photos side by side.", cta: ["Verification queue", "#/queue", "queue"] },
};

export async function renderDashboard(ctx) {
  if (session.me.role === "SUPERVISOR") return renderLiveDashboard(ctx);  // supervisors land on the live map
  const { main } = ctx;
  const d = await cachedGet("/dashboard");
  const availability = session.me.role === "WORKER" ? await availabilityCard(ctx) : null;
  const installed = window.matchMedia?.("(display-mode: standalone)").matches || navigator.standalone;
  const install = session.me.role === "WORKER" && !installed ? card({ class: "card install" },
    h("div", { class: "row between wrap" }, h("div", { class: "stack tight" }, h("h2", {}, "Install the field app"),
      h("span", { class: "muted" }, "Opens from your home screen like an app and keeps working with a weak signal: jobs you've opened stay readable, and what you do offline is sent when you're back online.")),
      session.installPrompt
        ? button("Install app", { class: "btn primary", onclick: async () => {
          session.installPrompt.prompt();
          const choice = await session.installPrompt.userChoice.catch(() => null);
          session.installPrompt = null;
          toast(choice?.outcome === "accepted" ? "Installed" : "Not installed", choice?.outcome === "accepted" ? "pass" : "info");
        } }, "upload")
        : h("span", { class: "hint", style: { maxWidth: "320px" } }, "On Android (Chrome): menu ⋮ → Install app. On iPhone (Safari): Share → Add to Home Screen. Needs https:// (or localhost)."))) : null;
  const me = session.me, copy = COPY[me.role];
  const stat = (n, text, href) => h(href ? "a" : "div", { class: "card stat", href, style: { textDecoration: "none", color: "inherit" } }, h("span", { class: "n" }, String(n)), h("span", {}, text));
  clear(main,
    d.offlineSince ? banner("review", `You're offline. Showing what was last loaded ${fmtAgo(d.offlineSince)}.`) : null,
    h("section", { class: "hero stack" }, h("span", { class: "lbl", style: { color: "#9DB0D6" } }, `Hello, ${me.display_name.split(" ")[0]}`), h("h1", {}, copy.title), h("p", {}, copy.text),
      h("div", { class: "row wrap" }, h("a", { class: "btn primary big", href: copy.cta[1] }, icon(copy.cta[2], 18), copy.cta[0]))),
    h("div", { class: "grid stats" },
      stat(d.total, me.role === "CITIZEN" ? "My reports" : "Reports", me.role === "CITIZEN" ? "#/reports" : null),
      stat(d.open, me.role === "CITIZEN" ? "In progress" : "Open tasks", me.role === "CITIZEN" ? null : "#/tasks"),
      stat(d.awaiting, "Being verified", me.role === "SUPERVISOR" ? "#/queue" : null),
      stat(d.resolved, "Resolved")),
    install,
    availability,
    card({}, h("div", { class: "row between wrap" }, h("h2", {}, "Recent"), me.role === "CITIZEN" ? null : h("span", { class: "muted" }, "Latest activity")),
      d.recent.length ? h("div", { class: "items" }, d.recent.map((i) => h("a", { class: "item", href: `#/incidents/${i.incident_id}` }, categoryIcon(i.category_icon),
        h("div", { class: "grow" }, h("strong", {}, i.title), h("span", { class: "muted mono" }, i.incident_id), " ", i.is_demo ? demoTag() : null, h("div", { class: "muted" }, `${i.category_label} · ${fmtAgo(i.updated_at)}`)),
        chip(i.status, i.status_text))))
        : emptyState("Nothing yet", me.role === "CITIZEN" ? "Your reports will show up here." : "Activity will show up here.")),
    session.config.auth_mode === "demo" ? card({}, h("h2", {}, "Try the demo"),
      h("ol", { class: "stack", style: { margin: 0, paddingLeft: "20px", gap: "8px" } },
        h("li", {}, "As a citizen, report a pothole. It becomes a worker task by itself.", " ", button("Open as citizen", { class: "btn small", onclick: () => { switchUser(firstUser("CITIZEN").user_id); location.hash = "#/report"; } })),
        h("li", {}, "As the assigned worker, take the completion photo at the spot, then try again from far away.", " ", button("Open as worker", { class: "btn small", onclick: () => { switchUser(firstUser("WORKER").user_id); location.hash = "#/tasks"; } })),
        h("li", {}, "As the supervisor, review the evidence and approve.", " ", button("Open as supervisor", { class: "btn small", onclick: () => { switchUser(firstUser("SUPERVISOR").user_id); location.hash = "#/queue"; } })))) : null);
}
