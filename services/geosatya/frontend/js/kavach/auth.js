/* Sign-in and registration (KAVACH_Authentication_Authorization_Flows).
   Citizen:    register / sign in.
   Worker:     worker access code + registration, then normal sign-in.
   Supervisor: assigned credentials + supervisor access code (no sign-up).
   Access codes are checked only by the server; none is stored in this file. */

import { api, session, signedIn } from "../api.js";
import { card, clear, h, icon } from "../ui.js";
import { field } from "./widgets.js";

const pageTop = (eyebrow, title, text) => h("section", { class: "page-hero slim" }, h("div", { class: "wrap", style: { position: "relative", zIndex: 1 } },
  h("span", { class: "eyebrow" }, eyebrow), h("h1", { style: { marginTop: "8px" } }, title), text ? h("p", {}, text) : null));

const nextOf = (params) => {
  const m = /next=([a-z/-]+)/.exec(params?.[0] || "");
  return m ? `#/${m[1]}` : "#/";
};
const errorBox = () => h("p", { class: "field-error", role: "alert", "aria-live": "assertive" });
const loginInput = (id) => h("input", { type: "text", id, required: true, autocomplete: "username", inputmode: "email", maxlength: 160,
  placeholder: "name@example.com or 98XXXXXXXX" });
function passwordInput(id, autocomplete) {
  const input = h("input", { type: "password", id, required: true, minlength: 8, maxlength: 128, autocomplete });
  const toggle = h("button", { class: "btn small ghost", type: "button", "aria-label": "Show password", "aria-pressed": "false",
    onclick: () => { const show = input.type === "password"; input.type = show ? "text" : "password"; toggle.setAttribute("aria-pressed", String(show)); toggle.textContent = show ? "Hide" : "Show"; } }, "Show");
  return { input, el: h("div", { class: "pw" }, input, toggle) };
}

async function submitTo(path, body, err, btn, next) {
  err.textContent = ""; btn.disabled = true;
  try {
    const res = await api(path, { method: "POST", json: body });
    session.afterSignIn = next;   // used by the shell when it re-renders for the new user
    await signedIn(res);
  } catch (ex) {
    err.textContent = ex.message;
    btn.disabled = false;
    return ex;
  }
  return null;
}

/* The "+" entry: three ways in. */
export function renderStart({ main }) {
  const o = session.authOptions || {};
  const option = (ic, title, text, href, action, note) => h("article", { class: "join-card" },
    h("span", { class: "join-ico" }, icon(ic, 26)), h("h2", {}, title), h("p", {}, text),
    note ? h("p", { class: "hint" }, note) : null,
    h("a", { class: "btn primary", href }, action, icon("arrowRight", 17)));
  clear(main, pageTop("Join KAVACH", "How do you want to use KAVACH?", "Pick one. You can always sign in later from the same place."),
    h("div", { class: "wrap pub-body" },
      h("div", { class: "join-grid" },
        option("user", "Citizen", "Report problems in your area with a photo and track them until they are fixed.", "#/signup/citizen", "Register as a Citizen"),
        option("tasks", "Field worker", "See your assigned jobs, share your location while working and upload proof of the work.", "#/signup/worker",
          "Register as a Field Worker", o.worker_registration === false ? "Registration is closed on this server right now." : "You need the worker access code from your department."),
        option("review", "Supervisor", "Assign workers, watch live operations and approve completed work.", "#/signin/supervisor",
          "Sign in as a Supervisor", "Accounts are created by your administrator. You also need the supervisor access code.")),
      h("p", { class: "center muted", style: { marginTop: "22px" } }, "Already registered? ", h("a", { href: "#/signin" }, "Sign in"),
        o.demo_identities ? h("span", {}, " · Development: ", h("a", { href: "#/demo" }, "use a demo identity")) : null)));
}

export function renderCitizenSignup({ main, params }) {
  const name = h("input", { type: "text", id: "cs-name", required: true, minlength: 2, maxlength: 80, autocomplete: "name" });
  const login = loginInput("cs-login");
  const pw = passwordInput("cs-pw", "new-password");
  const err = errorBox();
  const btn = h("button", { class: "btn primary big", type: "submit" }, "Create citizen account");
  clear(main, pageTop("Citizen", "Create your citizen account", "Report issues with a photo and follow them until they are resolved."),
    h("div", { class: "wrap pub-body" }, h("form", { class: "card stack auth-form", onsubmit: (e) => { e.preventDefault();
      submitTo("/auth/citizen/register", { name: name.value, login: login.value, password: pw.input.value }, err, btn, nextOf(params)); } },
      field("Your name", name), field("Email or mobile number", login, "You sign in with this."),
      field("Password", pw.el, "At least 8 characters, with letters and numbers."), err, btn,
      h("p", { class: "muted" }, "Already have an account? ", h("a", { href: "#/signin" }, "Sign in")))));
}

export async function renderWorkerSignup({ main }) {
  const cat = session.catalog ||= await api("/kavach/catalog");
  const code = h("input", { type: "password", id: "ws-code", required: true, maxlength: 80, autocomplete: "off", spellcheck: "false" });
  const name = h("input", { type: "text", id: "ws-name", required: true, minlength: 2, maxlength: 80, autocomplete: "name" });
  const login = loginInput("ws-login");
  const pw = passwordInput("ws-pw", "new-password");
  const skills = h("div", { class: "skill-picks", role: "group", "aria-label": "Skills" }, cat.skills.map((s) => h("label", { class: "skill" },
    h("input", { type: "checkbox", value: s }), s.replace(/_/g, " "))));
  const err = errorBox();
  const btn = h("button", { class: "btn primary big", type: "submit" }, "Register as a field worker");
  const closed = session.authOptions?.worker_registration === false;
  clear(main, pageTop("Field worker", "Register as a field worker", "Your department gives you the worker access code. After this you sign in with your email or mobile and password."),
    h("div", { class: "wrap pub-body" }, closed ? card({}, h("p", {}, "Worker registration is not open on this server. Ask your supervisor.")) :
      h("form", { class: "card stack auth-form", onsubmit: (e) => { e.preventDefault();
        submitTo("/auth/worker/register", { access_code: code.value, name: name.value, login: login.value, password: pw.input.value,
          skills: [...skills.querySelectorAll("input:checked")].map((i) => i.value) }, err, btn, "#/"); } },
        field("Worker access code", code, "Checked by the server. It is not your password."),
        field("Your name", name), field("Email or mobile number", login), field("Password", pw.el, "At least 8 characters, with letters and numbers."),
        h("div", { class: "field" }, "Your skills", skills, h("span", { class: "hint" }, "Jobs are offered to you by skill. A supervisor can change them later.")),
        err, btn, h("p", { class: "muted" }, "Already registered? ", h("a", { href: "#/signin" }, "Sign in")))));
}

export function renderSignin({ main, params }) {
  const login = loginInput("si-login");
  const pw = passwordInput("si-pw", "current-password");
  const err = errorBox();
  const btn = h("button", { class: "btn primary big", type: "submit" }, "Sign in");
  clear(main, pageTop("Sign in", "Welcome back", "Citizens and field workers sign in here."),
    h("div", { class: "wrap pub-body" }, h("form", { class: "card stack auth-form", onsubmit: async (e) => {
      e.preventDefault();
      const ex = await submitTo("/auth/login", { login: login.value, password: pw.input.value }, err, btn, nextOf(params));
      if (ex?.code === "USE_STAFF_SIGN_IN") clear(err, ex.message, " ", h("a", { href: "#/signin/supervisor" }, "Supervisor sign-in"));
    } }, field("Email or mobile number", login), field("Password", pw.el), err, btn,
      h("p", { class: "muted" }, "New here? ", h("a", { href: "#/start" }, "Create an account"), " · Supervisor? ", h("a", { href: "#/signin/supervisor" }, "Sign in here")))));
}

export function renderSupervisorSignin({ main }) {
  const login = loginInput("ss-login");
  const pw = passwordInput("ss-pw", "current-password");
  const code = h("input", { type: "password", id: "ss-code", required: true, maxlength: 80, autocomplete: "off", spellcheck: "false" });
  const err = errorBox();
  const btn = h("button", { class: "btn primary big", type: "submit" }, "Sign in as supervisor");
  clear(main, pageTop("Supervisor", "Supervisor sign-in", "Use the account your administrator created for you, and the supervisor access code. Platform admins use the admin access code."),
    h("div", { class: "wrap pub-body" }, h("form", { class: "card stack auth-form", onsubmit: (e) => { e.preventDefault();
      submitTo("/auth/supervisor/login", { login: login.value, password: pw.input.value, access_code: code.value }, err, btn, "#/"); } },
      field("Email or mobile number", login), field("Password", pw.el), field("Access code", code, "Checked by the server."), err, btn,
      h("p", { class: "muted" }, "There is no supervisor sign-up. Ask your administrator for an account."))));
}
