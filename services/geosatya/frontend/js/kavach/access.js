/* Development access: choose an identity, register an organization or an
   event organizer account, or join a workspace with an invite code.
   There are no passwords yet; identities only work while AUTH_MODE=demo and
   the server still enforces every role and workspace boundary. */

import { api, refreshUsers, session, switchUser } from "../api.js";
import { banner, button, card, clear, h, icon, toast } from "../ui.js";
import { ROLE_INFO, initials, roleKey } from "./brand.js";
import { field, pointPicker, select } from "./widgets.js";

const KNOWN = { "WS-DEMO-ORG": "Demo City Municipal Corporation (sample)", "WS-DEMO-EVT": "City Half Marathon 2026 (sample)" };
const ROLE_ORDER = ["CITIZEN", "WORKER", "SUPERVISOR", "ORG_ADMIN", "EVENT_ORGANIZER", "PLATFORM_ADMIN"];

const pageTop = (eyebrow, title, text) => h("section", { class: "page-hero" }, h("div", { class: "wrap", style: { position: "relative", zIndex: 1 } },
  h("span", { class: "eyebrow" }, eyebrow), h("h1", { style: { marginTop: "10px" } }, title), text ? h("p", {}, text) : null));

const devNote = () => h("div", { class: "dev-note" }, icon("key", 20), h("div", {}, h("strong", {}, "Development access. "),
  "Sign-in and OTP are switched off while Kavach is being built. Pick who you want to be; the server still checks every permission."));

async function enterAs(userId, next = "#/") {
  await switchUser(userId);
  location.hash = next;
}

export async function renderEnter({ main }) {
  if (session.config.auth_mode !== "demo") {
    clear(main, pageTop("Sign in", "Sign in to Kavach"), h("div", { class: "wrap pub-body" }, banner("info", "This server uses token sign-in.")));
    return;
  }
  await refreshUsers().catch(() => {});
  const groups = new Map();
  for (const u of session.users) {
    const key = u.role === "CITIZEN" ? "Citizens" : u.platform_role === "PLATFORM_ADMIN" ? "Kavach platform"
      : !u.workspace_id ? (u.platform_role === "EVENT_ORGANIZER" ? "Event organizers" : "Open civic team (GeoSatya)")
      : u.workspace_id.startsWith("EV") || u.workspace_id === "WS-DEMO-EVT" ? `Event · ${KNOWN[u.workspace_id] || u.workspace_id}`
      : `Organization · ${KNOWN[u.workspace_id] || u.workspace_id}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(u);
  }
  const who = (u) => {
    const info = ROLE_INFO[roleKey(u)] || ROLE_INFO.CITIZEN;
    return h("button", { class: "who", type: "button", onclick: () => enterAs(u.user_id) },
      h("span", { class: "av", style: { "--c": info.color } }, initials(u.display_name)),
      h("span", { class: "grow" }, h("strong", {}, u.display_name), h("span", { class: "muted" }, info.label)), icon("arrowRight", 18));
  };
  const order = (k) => ["Citizens", "Open civic team (GeoSatya)"].indexOf(k) + 1 || (k.startsWith("Organization") ? 3 : k.startsWith("Event") ? 4 : 5);
  clear(main, pageTop("Sign in", "Who are you today?", "Choose an experience to explore. Each one opens its own workspace with its own permissions."),
    h("div", { class: "wrap pub-body" }, devNote(),
      [...groups.entries()].sort((a, b) => order(a[0]) - order(b[0])).map(([name, users]) => h("div", { class: "access-group" },
        h("h3", {}, name), h("div", { class: "access" }, users.sort((a, b) => ROLE_ORDER.indexOf(roleKey(a)) - ROLE_ORDER.indexOf(roleKey(b))).map(who)))),
      card({}, h("h2", {}, "New here?"), h("div", { class: "row wrap" },
        h("a", { class: "btn primary", href: "#/register/organization" }, icon("building", 17), "Register an organization"),
        h("a", { class: "btn", href: "#/register/organizer" }, icon("calendar", 17), "Create an event organizer account"),
        h("a", { class: "btn", href: "#/join" }, icon("key", 17), "Join with an invite code")))));
}

const formError = () => h("p", { class: "field-error", "aria-live": "polite" });

export async function renderRegisterOrg({ main, onCleanup }) {
  const cat = session.catalog ||= await api("/kavach/catalog");
  const f = {
    name: h("input", { type: "text", id: "o-name", required: true, minlength: 3, maxlength: 120, placeholder: "e.g. Riverside Municipal Council" }),
    legal: h("input", { type: "text", id: "o-legal", maxlength: 160 }),
    category: select("o-cat", cat.org_categories.map((c) => [c.id, c.label]), "MUNICIPAL_BODY"),
    desc: h("textarea", { id: "o-desc", maxlength: 1000, rows: 3, placeholder: "What does your organization look after?" }),
    admin: h("input", { type: "text", id: "o-admin", required: true, minlength: 2, maxlength: 80, placeholder: "Your name" }),
    email: h("input", { type: "email", id: "o-email", maxlength: 160 }),
    phone: h("input", { type: "tel", id: "o-phone", maxlength: 20 }),
    address: h("input", { type: "text", id: "o-addr", maxlength: 200 }),
    verify: h("textarea", { id: "o-verify", maxlength: 300, rows: 2, placeholder: "Registration number, official letter or contact we can check (optional)" }),
    radius: select("o-radius", [["2000", "2 km"], ["5000", "5 km"], ["10000", "10 km"], ["25000", "25 km"], ["50000", "50 km"]], "10000"),
  };
  const picker = pointPicker({ radius: 10000, label: "Click the map at the centre of your service area" });
  f.radius.addEventListener("change", () => picker.setRadius(Number(f.radius.value)));
  const err = formError();
  const submit = h("button", { class: "btn primary big", type: "submit" }, "Create organization workspace");
  clear(main, pageTop("Register an organization", "Set up your autonomous workspace", "Your incidents, departments and workers stay private to your organization."),
    h("div", { class: "wrap pub-body" }, devNote(),
      h("form", { class: "card stack", onsubmit: async (e) => {
        e.preventDefault(); err.textContent = "";
        const p = picker.state.point;
        submit.disabled = true;
        try {
          const r = await api("/kavach/register/organization", { method: "POST", json: {
            name: f.name.value, legal_name: f.legal.value || null, category: f.category.value, description: f.desc.value,
            admin_name: f.admin.value, contact_email: f.email.value || null, phone: f.phone.value || null, address: f.address.value || null,
            verification_details: f.verify.value || null, center_latitude: p?.[0] ?? null, center_longitude: p?.[1] ?? null,
            radius_m: Number(f.radius.value) } });
          toast(`Workspace created for ${r.workspace.name}`, "pass");
          await enterAs(r.user_id, "#/");
        } catch (ex) { err.textContent = ex.message; submit.disabled = false; }
      } },
      h("h2", {}, "Organization"),
      h("div", { class: "form-grid" }, field("Organization name", f.name), field("Legal name", f.legal, "If different"),
        field("Category", f.category), field("Address", f.address), field("About", f.desc, null, "full")),
      h("h2", {}, "Service area"), picker.el, field("Radius", f.radius, "Reports inside this area can be routed to you once an authority mapping is configured."),
      h("h2", {}, "Administrator"),
      h("div", { class: "form-grid" }, field("Your name", f.admin), field("Email", f.email), field("Phone", f.phone)),
      h("h2", {}, "Verification"),
      field("Verification details", f.verify, "Organizations start as unverified (or pending if you add details). Kavach's team verifies identity separately; registering never implies government affiliation."),
      err, h("div", {}, submit))));
  await picker.mount();
  onCleanup(() => picker.destroy());
}

export async function renderRegisterOrganizer({ main }) {
  const f = {
    name: h("input", { type: "text", id: "e-name", required: true, minlength: 2, maxlength: 80, placeholder: "Your name" }),
    company: h("input", { type: "text", id: "e-co", required: true, minlength: 2, maxlength: 120, placeholder: "Company or organizing group" }),
    email: h("input", { type: "email", id: "e-email", maxlength: 160 }), phone: h("input", { type: "tel", id: "e-phone", maxlength: 20 }),
  };
  const err = formError();
  clear(main, pageTop("Event organizers", "Create your organizer account", "Then create your first event, invite your team and go live."),
    h("div", { class: "wrap pub-body" }, devNote(),
      h("form", { class: "card stack", style: { maxWidth: "720px" }, onsubmit: async (e) => {
        e.preventDefault(); err.textContent = "";
        try {
          const r = await api("/kavach/register/event-organizer", { method: "POST", json: { name: f.name.value, company: f.company.value,
            contact_email: f.email.value || null, phone: f.phone.value || null } });
          sessionStorage.setItem("kavach.company", r.company);
          await enterAs(r.user_id, "#/events/new");
        } catch (ex) { err.textContent = ex.message; }
      } },
      h("div", { class: "form-grid" }, field("Your name", f.name), field("Company", f.company), field("Email", f.email), field("Phone", f.phone)),
      err, h("div", {}, h("button", { class: "btn primary big", type: "submit" }, "Create account and set up an event")))));
}

export async function renderJoin({ main, params }) {
  const code = h("input", { type: "text", id: "j-code", required: true, minlength: 6, maxlength: 16, value: params[0] || "", placeholder: "8-character code",
    style: { textTransform: "uppercase", fontFamily: "var(--mono)", letterSpacing: ".2em" }, autocomplete: "off" });
  const name = h("input", { type: "text", id: "j-name", required: true, minlength: 2, maxlength: 80, placeholder: "Your name" });
  const phone = h("input", { type: "tel", id: "j-phone", maxlength: 20 });
  const err = formError();
  clear(main, pageTop("Join a team", "Join with your invite code", "Your organizer or supervisor gives you a one-time code. You'll only see that workspace and your own tasks."),
    h("div", { class: "wrap pub-body" }, devNote(),
      h("form", { class: "card stack", style: { maxWidth: "560px" }, onsubmit: async (e) => {
        e.preventDefault(); err.textContent = "";
        try {
          const r = await api("/kavach/join", { method: "POST", json: { code: code.value.trim().toUpperCase(), name: name.value, phone: phone.value || null } });
          toast(`Welcome to ${r.workspace.name}`, "pass");
          await enterAs(r.user_id, "#/");
        } catch (ex) { err.textContent = ex.message; }
      } }, field("Invite code", code), field("Your name", name), field("Phone", phone, "Optional"), err,
      h("div", {}, h("button", { class: "btn primary big", type: "submit" }, "Join")))));
}

export { enterAs };
export const signOutButton = () => button("Sign out", { class: "btn small" }, "logout");
