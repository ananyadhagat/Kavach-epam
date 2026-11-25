/* Team live demo sign-in (TEAM_DEMO=1 on the server, development only).
   It looks like a sign-in so the demo feels real, but the password is not checked: whoever is
   picked is signed in. The server only offers the ten team members in this mode. */

import { refreshUsers, session, switchUser } from "../api.js";
import { clear, h, icon, toast } from "../ui.js";
import { TEAM } from "./team-data.js";

export const TEAM_PASSWORD = "kavach123";
const ROLE = { SUPERVISOR: "Supervisor", CITIZEN: "Citizen", WORKER: "Field worker" };
const ORDER = ["SUPERVISOR", "CITIZEN", "WORKER"];
const photoOf = (name) => TEAM.find((m) => m.name === name)?.image || "";
const initials = (n) => n.split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();

export async function renderTeamLogin({ main }) {
  await refreshUsers().catch(() => {});
  const people = [...session.users].sort((a, b) => ORDER.indexOf(a.role) - ORDER.indexOf(b.role) || a.display_name.localeCompare(b.display_name));
  let picked = null;
  const pass = h("input", { type: "password", id: "team-pass", autocomplete: "current-password", placeholder: "Password", value: "" });
  const err = h("p", { class: "field-error", role: "alert" });
  const go = h("button", { class: "btn primary big block", type: "submit" }, icon("arrowRight", 18), "Sign in");
  const grid = h("div", { class: "tl-grid", role: "radiogroup", "aria-label": "Who are you?" });
  const draw = () => clear(grid, ORDER.map((role) => {
    const group = people.filter((u) => u.role === role);
    return group.length ? h("div", { class: "tl-group" }, h("p", { class: "tl-role" }, role === "WORKER" ? "Field workers" : role === "CITIZEN" ? "Citizens" : "Supervisor"),
      h("div", { class: "tl-people" }, group.map((u) => {
        const img = photoOf(u.display_name);
        return h("button", { type: "button", class: "tl-person", role: "radio", "aria-checked": String(picked === u.user_id),
          onclick: () => { picked = u.user_id; err.textContent = ""; draw(); pass.focus(); } },
          img ? h("img", { src: img, alt: "", width: 44, height: 44 }) : h("span", { class: "tl-ini" }, initials(u.display_name)),
          h("span", {}, h("strong", {}, u.display_name), h("small", {}, ROLE[u.role] || u.role)));
      }))) : null;
  }));
  const form = h("form", { class: "tl-form stack", onsubmit: async (e) => {
    e.preventDefault();
    if (!picked) { err.textContent = "Tap your name first."; return; }
    if (!pass.value) { err.textContent = "Enter the password."; pass.focus(); return; }
    go.disabled = true;
    // Team demo: any password is accepted (this only looks like a sign-in).
    session.afterSignIn = "#/";
    try { await switchUser(picked); toast(`Welcome, ${session.me?.display_name}`, "pass"); }
    catch (ex) { go.disabled = false; err.textContent = ex.message; }
  } },
  h("label", { class: "field", for: "team-pass" }, "Password", pass, h("span", { class: "hint" }, `Team password: ${TEAM_PASSWORD}`)), err, go);
  draw();
  clear(main, h("div", { class: "tl-page" }, h("section", { class: "tl-card glass" },
    h("img", { class: "tl-logo", src: "icons/kavach-logo-light.webp", alt: "KAVACH", width: 180, height: 57 }),
    h("h1", {}, "Sign in"), h("p", { class: "muted" }, "Team Codyssey live demo. Tap your name, then sign in."),
    people.length ? grid : h("p", { class: "banner review" }, "No team accounts were found on this server."), form)));
}
