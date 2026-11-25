/* KAVACH home page: the Digital Serenity hero, the nine-stage workflow, live public numbers,
   what you can report, GeoSatya + worker allocation, women's safety, the team wall and a closing call.
   Every button goes somewhere real; the numbers come from the public stats API. */

import { api, devAccess, session } from "../api.js";
import { clear, h, icon } from "../ui.js";
import { countUp, hours, reveal } from "./brand.js";
import { infoOf, selectCategory } from "./categories.js";
import { serenityHero } from "./serenity.js";
import { teamShowcase } from "./team.js";

const reduceMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const goReport = () => { location.hash = session.me?.role === "CITIZEN" ? "#/report" : "#/public-report"; };
const scrollToId = (id) => document.getElementById(id)?.scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "start" });

const section = (id, cls, ...children) => h("section", { id, class: `aur-sec ${cls || ""}` }, h("div", { class: "wrap" }, ...children));
const head = (eyebrow, title, lead) => h("div", { class: "aur-head reveal" }, h("p", { class: "aur-eyebrow" }, eyebrow), h("h2", {}, title), lead ? h("p", { class: "aur-lede" }, lead) : null);
const glassCard = (ic, title, text, cls = "") => h("div", { class: `aur-card glass reveal ${cls}` }, h("span", { class: "aur-ico" }, icon(ic, 22)), h("h3", {}, title), h("p", {}, text));

const FLOW = [["camera", "Report", "Photo + phone GPS"], ["review", "Understand", "Incident Intelligence"], ["crosshair", "Locate", "GeoSatya checks"],
  ["route", "Route", "Right team & authority"], ["bell", "Alert", "Worker notified"], ["navigate", "Respond", "Live journey"],
  ["shield", "Verify", "15 m geofence"], ["pass", "Resolve", "Supervisor approves"], ["chart", "Learn", "Public dashboard"]];

const HOME_CATS = [["road_damage", "Roads"], ["garbage", "Garbage"], ["drainage", "Drainage"], ["water_leakage", "Water leakage"],
  ["streetlight", "Streetlights"], ["sanitation", "Sanitation"], ["infrastructure", "Public infrastructure"], ["safety_hazard", "Public safety"]];

export async function renderHome({ main, onCleanup }) {
  const dashboard = session.me ? "#/" : devAccess() ? "#/" : "#/signin";
  const hero = serenityHero({
    top: "Report · Understand · Locate",
    title: "Every complaint, verified on the ground.",
    subtitle: "From a citizen's photo to the right worker, checked within fifteen metres by GeoSatya.",
    bottom: "Route · Alert · Respond · Verify · Resolve",
    actions: [
      h("button", { class: "aur-btn primary", type: "button", onclick: goReport }, icon("camera", 18), "Report an issue"),
      h("button", { class: "aur-btn", type: "button", onclick: () => scrollToId("flow") }, "See how it works", icon("arrowRight", 16)),
      h("a", { class: "aur-btn ghost", href: dashboard }, icon("dashboard", 17), session.me || devAccess() ? "Open dashboard" : "Sign in"),
    ],
  });
  const team = teamShowcase({ autoplay: true, compact: true });
  const nums = [h("strong", {}, "—"), h("strong", {}, "—"), h("strong", {}, "—"), h("strong", {}, "—")];
  const statsBox = h("div", { class: "aur-stats glass reveal" },
    h("div", {}, nums[0], h("span", {}, "public reports")), h("div", {}, nums[1], h("span", {}, "resolved and verified")),
    h("div", {}, nums[2], h("span", {}, "reported in the last 7 days")), h("div", {}, nums[3], h("span", {}, "median time to resolve")));

  clear(main, h("div", { class: "aur-home" },
    hero.el,

    section("flow", "", head("One workflow", "Report → Learn, in nine checked steps",
      "Seven team agents and GeoSatya carry every complaint from a photo to a verified repair. People approve; the server checks."),
    h("ol", { class: "aur-flow reveal" }, FLOW.map(([ic, t, d], i) => h("li", { style: { "--i": i } },
      h("span", { class: "aur-flow-ico" }, icon(ic, 20)), h("strong", {}, t), h("small", {}, d)))),
    statsBox,
    h("p", { class: "aur-note reveal" }, h("a", { href: "#/stats" }, "Open the public dashboard", icon("arrowRight", 14)))),

    section("report", "alt", head("What you can report", "Choose a problem to start",
      "The camera opens first; your phone's GPS is read at the same moment. No gallery uploads, no dropped pins."),
    h("div", { class: "aur-cats" }, HOME_CATS.map(([id, name]) => h("button", { class: "aur-cat glass reveal", type: "button",
      onclick: () => { selectCategory(id); goReport(); } }, h("span", { class: "aur-ico" }, icon(infoOf(id)?.icon || "dots", 22)),
      h("strong", {}, name), h("small", {}, infoOf(id)?.options?.slice(0, 2).join(", ") || ""))))),

    section("geosatya", "", h("div", { class: "aur-split" },
      h("div", { class: "reveal" }, head("GeoSatya + dispatch", "The right worker, proven at the right spot"),
        h("ul", { class: "aur-ticks" }, ["Workers ranked by distance, availability, skills and workload", "Location must be fresh and accurate, never simulated",
          "Completion photo must be taken within 15 m of the complaint", "Supervisors approve; every decision is in the audit trail"].map((t) => h("li", {}, icon("check", 17), t))),
        h("div", { class: "row wrap", style: { gap: "10px", marginTop: "18px" } },
          h("a", { class: "aur-btn primary", href: dashboard }, icon("live", 17), "Open the live operations map"))),
      h("div", { class: "aur-radar-demo reveal", "aria-hidden": "true" }, h("div", { class: "radar mini" },
        h("span", { class: "radar-ring r1" }), h("span", { class: "radar-ring r2" }), h("span", { class: "radar-ring r3" }), h("span", { class: "radar-sweep" }),
        h("span", { class: "radar-core" }, icon("search", 22)),
        [[28, 30], [70, 24], [22, 66], [76, 64]].map(([x, y], i) => h("span", { class: "radar-blip", style: { left: `${x}%`, top: `${y}%`, animationDelay: `${i * 0.5}s` } }, icon("user", 16)))),
      h("p", { class: "aur-caption" }, "Finding the nearest available worker…")))),

    section("women", "alt", h("div", { class: "aur-split rev" },
      h("div", { class: "reveal" }, head("Women's safety", "Trusted Allies, one-tap SOS, a voice note"),
        h("ul", { class: "aur-ticks" }, ["Only the people you choose, with your consent", "Your phone's real GPS while the SOS is on",
          "Record a voice note so allies hear what is happening", "Call 100, 108 or 112 from the same screen"].map((t) => h("li", {}, icon("check", 17), t))),
        h("p", { class: "aur-fine" }, "KAVACH does not replace the police or emergency services. In danger, call 112."),
        h("a", { class: "aur-btn primary", href: session.me?.role === "CITIZEN" ? "#/safety" : "#/women", style: { marginTop: "14px" } }, icon("heart", 17), "Open Women's Safety")),
      h("div", { class: "aur-sos-demo glass reveal", "aria-hidden": "true" }, h("span", { class: "sos-orb" }, "SOS"), h("p", {}, "Hold for one second"), h("small", {}, "5-second cancel countdown")))),

    section("team", "", team.el),

    section("start", "", h("div", { class: "aur-cta glass reveal" },
      h("h2", {}, "Ready when the city needs it."),
      h("p", { class: "aur-lede" }, "Report a problem in under a minute, or open the operations dashboard."),
      h("div", { class: "row wrap center", style: { gap: "10px" } },
        h("button", { class: "aur-btn primary", type: "button", onclick: goReport }, icon("camera", 18), "Report an issue"),
        h("a", { class: "aur-btn", href: "#/track" }, icon("search", 17), "Track a complaint"),
        h("a", { class: "aur-btn ghost", href: dashboard }, icon("dashboard", 17), "Open dashboard"))))));

  onCleanup(hero.destroy);
  onCleanup(team.destroy);
  onCleanup(reveal(main));
  api("/kavach/public/stats").then((s) => {
    countUp(nums[0], s.total); countUp(nums[1], s.resolved); countUp(nums[2], s.reported_this_week);
    nums[3].textContent = hours(s.median_resolution_hours);
  }).catch(() => statsBox.remove());
}
