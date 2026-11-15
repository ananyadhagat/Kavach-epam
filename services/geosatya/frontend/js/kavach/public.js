/* KAVACH public site. Every number here comes from the live API; the public
   endpoints expose only aggregates and status, never personal details,
   descriptions, exact locations or private event/organization data. */

import { api, session } from "../api.js";
import { createMap } from "../maps.js";
import { banner, card, clear, demoTag, emptyState, fmtAgo, fmtTime, h, icon } from "../ui.js";
import { countUp, hours, reveal } from "./brand.js";
import { agentStatus } from "./agents-ui.js";

const STEPS = [
  { icon: "pin", title: "Report with your location", text: "Pick a category, describe the problem and share your device location (or drop a pin). No photo is needed.", by: "GeoSatya location capture" },
  { icon: "info", title: "Understand the report", text: "Incident Intelligence reads the report, structures it and sets a priority. Rules, not the AI, make the final call.", by: "Incident Intelligence agent" },
  { icon: "globe", title: "Route to the right authority", text: "Configured jurisdictions decide who is responsible: the city, a state highway or a national highway division.", by: "Kavach jurisdiction routing" },
  { icon: "route", title: "Dispatch the best worker", text: "Not just the nearest dot on a map: availability, skills, workload, location freshness and road travel time all count.", by: "Dispatch agent ranking" },
  { icon: "live", title: "Track live: ETA and ETR", text: "The worker shares their location only during the job. You see when they'll arrive and when the work should be done.", by: "Live tracking" },
  { icon: "shield", title: "Verified on the ground", text: "Completion is checked against the reported spot: distance, GPS accuracy and freshness. Uncertain cases go to a supervisor.", by: "GeoSatya verification" },
  { icon: "check", title: "You see it resolved", text: "Follow your complaint stage by stage with your reference number, from received to resolved.", by: "Public tracking" },
];

async function catalog() {
  session.catalog ||= await api("/kavach/catalog");
  return session.catalog;
}

/* ------------------------------------------------------------- landing */
export async function renderHome({ main, onCleanup }) {
  const [stats, cat] = await Promise.all([api("/kavach/public/stats").catch(() => null), catalog()]);
  const mapEl = h("div", { class: "map", role: "img", "aria-label": "Map of reported areas" });
  const n = { total: h("strong", {}), resolved: h("strong", {}), rate: h("strong", {}), median: h("strong", {}) };

  const orbit = orbitSection();
  const civic = cat.categories.filter((c) => c.scope !== "event");
  clear(main,
    h("section", { class: "k-hero" },
      h("div", { class: "visual" }, mapEl,
        h("div", { class: "float-card a" }, h("span", { class: "ico" }, icon("live", 20)),
          h("div", {}, h("strong", {}, stats ? String(stats.open) : "—"), "open civic reports")),
        h("div", { class: "float-card b" }, h("span", { class: "ico" }, icon("shield", 20)),
          h("div", {}, h("strong", {}, "Geo-verified"), "completion at the right spot"))),
      h("div", { class: "copy" },
        h("span", { class: "hero-badge" }, h("span", { class: "pulse" }), "Live: civic reports, events and field teams"),
        h("h1", {}, "One shield for every ", h("em", {}, "street, event"), " and campus."),
        h("p", {}, "Kavach turns a report into the right worker at the right place, tracks them live, and checks on the ground that the job was really done."),
        h("div", { class: "actions" },
          h("a", { class: "btn primary big", href: "#/public-report" }, icon("plus", 18), "Report an issue"),
          h("a", { class: "btn big ghost", href: "#/track" }, icon("search", 18), "Track a complaint")))),
    h("div", { class: "wrap" },
      h("div", { class: "k-stats reveal" },
        h("div", {}, n.total, h("span", {}, "civic reports received")),
        h("div", {}, n.resolved, h("span", {}, "resolved and verified")),
        h("div", {}, n.rate, h("span", {}, "resolution rate")),
        h("div", {}, n.median, h("span", {}, "median time to resolve"))),
      h("p", { class: "k-stats-note" }, stats?.includes_demo_data ? "Live figures from this Kavach instance, including demo records." : "Live figures from this Kavach instance.")),

    h("section", { class: "section" }, h("div", { class: "wrap" },
      h("div", { class: "reveal" }, h("span", { class: "eyebrow" }, "Three ways to use Kavach"),
        h("h2", { class: "big" }, "One platform. Three kinds of customer."),
        h("p", { class: "lead", style: { marginTop: "10px" } }, "Each works in its own private workspace on shared, proven infrastructure: dispatch, live maps and on-the-ground verification.")),
      h("div", { class: "models" },
        model("Citizens", "user", "linear-gradient(135deg,#F7C36A,#F08A24)", ["Report potholes, garbage, leaks, broken lights", "Location from your phone, no photo needed",
          "The right authority is suggested automatically", "Track every stage with a reference number"], "#/public-report", "Report an issue", "reveal d1"),
        model("Event organizers", "calendar", "linear-gradient(135deg,#B48BF0,#6D28D9)", ["Create an event with venue, dates and zones", "Invite temporary workers with a code",
          "See your team live on the map", "Medical, crowd and security incidents dispatched in seconds"], "#/solutions/events", "Event solutions", "reveal d2"),
        model("Organizations", "building", "linear-gradient(135deg,#1F8C80,#0B2F2C)", ["Nagar Nigam, departments, campuses, facility teams", "Departments, supervisors and workers",
          "Your own categories, service area and targets", "Fully independent and isolated workspace"], "#/solutions/organizations", "Organization solutions", "reveal d3")))),

    h("section", { class: "section mint" }, h("div", { class: "wrap" },
      h("div", { class: "reveal", style: { textAlign: "center" } }, h("span", { class: "eyebrow" }, "How it works"),
        h("h2", { class: "big" }, "From a report to a verified fix")), orbit.el)),

    h("section", { class: "section" }, h("div", { class: "wrap" },
      h("div", { class: "reveal" }, h("span", { class: "eyebrow" }, "What you can report"),
        h("h2", { class: "big" }, "Resolution targets you can see"),
        h("p", { class: "lead", style: { marginTop: "10px" } }, "Hover or tap a category to see its target time. ", h("span", { class: "muted" }, cat.target_note))),
      h("div", { class: "rings-grid" }, civic.map((c, i) => h("div", { class: `reveal d${i % 4}` },
        h("button", { class: "ring", type: "button", "aria-label": `${c.label}: target ${hours(c.target_hours)}`, onclick: (e) => e.currentTarget.classList.toggle("flip") },
          h("span", { class: "face front" }, icon(c.icon, 46)),
          h("span", { class: "face back" }, h("strong", {}, c.label), `Target: ${hours(c.target_hours)}`)),
        h("div", { class: "ring-name" }, c.label)))))),

    h("section", { class: "section mint" }, h("div", { class: "wrap trust" },
      h("div", { class: "stack reveal", style: { gap: "18px" } }, h("span", { class: "eyebrow" }, "Powered by GeoSatya"),
        h("h2", { class: "big" }, "Proof that the work happened where it should"),
        h("div", { class: "checks" },
          checkRow("crosshair", "Geofence check", "The completion location must be inside the radius around the reported spot, measured on the server."),
          checkRow("navigate", "GPS accuracy", "A blurry fix can't prove anything. Low accuracy goes to a supervisor instead of passing."),
          checkRow("clock", "Freshness", "Old or replayed positions are rejected. Simulated coordinates are always labelled."),
          checkRow("review", "Human review", "PASS, REVIEW REQUIRED or FAIL, with the full audit trail for every decision."))),
      h("div", { class: "geo-demo reveal d2", "aria-hidden": "true" }, h("span", { class: "sweep" }),
        h("span", { class: "center" }, icon("pin", 28)),
        h("span", { class: "dotw", style: { background: "#16A34A", left: "57%", top: "44%" } }),
        h("span", { class: "tag", style: { left: "61%", top: "36%", background: "#E1F5EA", color: "#0B7A47" } }, "PASS · 5 m"),
        h("span", { class: "dotw", style: { background: "#D97706", left: "24%", top: "64%" } }),
        h("span", { class: "tag", style: { left: "8%", top: "72%", background: "#FFF1D6", color: "#8A5400" } }, "REVIEW · ±80 m"),
        h("span", { class: "dotw", style: { background: "#DC2626", left: "80%", top: "80%" } }),
        h("span", { class: "tag", style: { left: "66%", top: "86%", background: "#FDE9E7", color: "#B42318" } }, "FAIL · 240 m")))),

    h("section", { class: "section" }, h("div", { class: "wrap" }, h("div", { class: "ws-banner reveal" },
      h("div", {}, h("h1", {}, "Bring Kavach to your city, event or campus"),
        h("p", { style: { marginTop: "8px", position: "relative", zIndex: 1 } }, "Start a workspace in minutes. Plans and pricing are being finalised; everything is free while Kavach is in development.")),
      h("div", { class: "actions" }, h("a", { class: "btn primary big", href: "#/register/organization" }, "Register an organization"),
        h("a", { class: "btn big", href: "#/register/organizer" }, "I organize events"))))));

  countUp(n.total, stats?.total);
  countUp(n.resolved, stats?.resolved);
  countUp(n.rate, stats?.resolution_rate, { suffix: "%" });
  if (stats?.median_resolution_hours != null) n.median.textContent = hours(stats.median_resolution_hours); else n.median.textContent = "—";
  onCleanup(reveal(main));
  onCleanup(orbit.start());

  setTimeout(async () => {
    const map = await createMap(mapEl, { center: [23.2599, 77.4126], zoom: 12 });
    onCleanup(() => map.destroy());
    const areas = stats?.areas || [];
    areas.forEach((a, i) => map.circle(`a${i}`, [a.latitude, a.longitude], 250 + Math.min(a.count, 20) * 60, "area"));
    if (areas.length) map.fit(areas.map((a) => [a.latitude, a.longitude]));
    if (areas.length === 1) map.setView([areas[0].latitude, areas[0].longitude], 13);
  });
}

function model(title, ic, color, points, href, cta, cls) {
  return h("article", { class: `model ${cls}`, style: { "--c": color } }, h("span", { class: "mico" }, icon(ic, 26)), h("h3", {}, title),
    h("ul", {}, points.map((p) => h("li", {}, icon("check", 16), p))), h("a", { class: "btn primary", href }, cta, icon("arrowRight", 16)));
}

function checkRow(ic, title, text) {
  return h("div", { class: "check-row" }, h("span", { class: "ico" }, icon(ic, 20)), h("div", {}, h("strong", {}, title), h("p", { class: "muted", style: { fontSize: "14px" } }, text)));
}

/* A rotating ring of steps, in the style of the reference site. */
function orbitSection() {
  let i = 0, timer = null;
  const track = h("div", { class: "track" });
  const caption = h("div", { class: "caption", "aria-live": "polite" });
  const count = h("span", { class: "count" });
  const draw = () => {
    const nodes = STEPS.map((s, k) => {
      const d = (k - i + STEPS.length) % STEPS.length;
      const rel = d > STEPS.length / 2 ? d - STEPS.length : d;
      return { s, k, rel };
    }).filter((x) => Math.abs(x.rel) <= 2).sort((a, b) => a.rel - b.rel);
    clear(track, nodes.map(({ s, k, rel }) => h("button", { class: `node${rel === 0 ? " on" : Math.abs(rel) === 1 ? " near" : ""}`, type: "button",
      "aria-label": s.title, "aria-current": rel === 0 ? "step" : null, onclick: () => { go(k); } }, icon(s.icon, rel === 0 ? 64 : 28))));
    const s = STEPS[i];
    clear(caption, h("div", { class: "fade-swap" }, h("h3", {}, s.title), h("p", {}, s.text), h("p", { class: "by" }, s.by)));
    count.textContent = `${i + 1} / ${STEPS.length}`;
  };
  const go = (k) => { i = (k + STEPS.length) % STEPS.length; draw(); restart(); };
  const restart = () => { clearInterval(timer); if (!matchMedia("(prefers-reduced-motion: reduce)").matches) timer = setInterval(() => { i = (i + 1) % STEPS.length; draw(); }, 4200); };
  draw();
  const el = h("div", { class: "orbit" }, h("div", { class: "rings" }), track, caption,
    h("div", { class: "arrows" }, h("button", { type: "button", "aria-label": "Previous step", onclick: () => go(i - 1) }, icon("arrowLeft", 18)), count,
      h("button", { type: "button", "aria-label": "Next step", onclick: () => go(i + 1) }, icon("arrowRight", 18))));
  return { el, start: () => { restart(); return () => clearInterval(timer); } };
}

const pageHero = (eyebrow, title, text, ...extra) => h("section", { class: "page-hero" }, h("div", { class: "wrap", style: { position: "relative", zIndex: 1 } },
  h("span", { class: "eyebrow" }, eyebrow), h("h1", { style: { marginTop: "10px" } }, title), text ? h("p", {}, text) : null, ...extra));
const feature = (ic, title, text) => h("div", { class: "feature reveal" }, h("span", { class: "ico" }, icon(ic, 20)), h("strong", {}, title), h("p", { class: "muted" }, text));

/* ----------------------------------------------------------- solutions */
export async function renderEventSolutions({ main, onCleanup }) {
  clear(main, pageHero("Event solutions", "Run your event's field team like a control room",
    "Concerts, festivals, marathons, exhibitions and conferences: create the event, invite your workers and handle every incident live.",
    h("div", { class: "row wrap", style: { marginTop: "22px" } }, h("a", { class: "btn primary big", href: "#/register/organizer" }, "Create an organizer account"),
      h("a", { class: "btn big", href: "#/enter" }, "Try the demo event"))),
  h("div", { class: "wrap pub-body" },
    h("div", { class: "feature-grid" },
      feature("calendar", "Event workspace", "Name, category, venue on the map, dates and a boundary. Each event is its own private workspace."),
      feature("zone", "Operational zones", "Stages, gates, medical tents, water stations: mark them once and see them on every map."),
      feature("key", "Invite codes for workers", "Temporary staff join with a one-time code. They only ever see that event and their own tasks."),
      feature("users", "Roles and skills", "First aid, security, crowd control, maintenance: dispatch matches the incident to the right skill."),
      feature("live", "Live operations", "Registered, active, available, assigned, on break and offline workers, with incidents on one map."),
      feature("medical", "Event incident types", "Medical assistance, crowd management, security, missing person and operational issues, with priority."),
      feature("clock", "ETA and ETR", "How long until help arrives, and until the issue is resolved, kept separately and updated live."),
      feature("chart", "Reports", "Incidents by category and by day, response and resolution, for the debrief after the event.")),
    card({ class: "card reveal" }, h("h2", {}, "Plans"), h("p", { class: "muted" }, "Kavach is built to support per-event, duration-based, worker-count-based and enterprise plans. Pricing is not set yet, so nothing is charged during development."),
      h("a", { class: "btn", href: "#/stats" }, "See the public dashboard"))));
  onCleanup(reveal(main));
}

export async function renderOrgSolutions({ main, onCleanup }) {
  clear(main, pageHero("Organization solutions", "Your own autonomous operations workspace",
    "For Nagar Nigam and municipal bodies, government departments, road and infrastructure teams, campuses and facility managers.",
    h("div", { class: "row wrap", style: { marginTop: "22px" } }, h("a", { class: "btn primary big", href: "#/register/organization" }, "Register an organization"),
      h("a", { class: "btn big", href: "#/enter" }, "Try the demo organization"))),
  h("div", { class: "wrap pub-body" },
    h("div", { class: "feature-grid" },
      feature("building", "Organization → departments", "Model your own structure: departments, supervisors and field workers, not a fixed template."),
      feature("map", "Service area", "Set where you operate. Public reports inside your jurisdiction can be routed straight to you."),
      feature("list", "Your categories and targets", "Choose the incident categories you handle and set your own resolution targets."),
      feature("route", "Smart assignment", "Skills, availability, workload, location freshness and road travel time, with supervisor override and a reason."),
      feature("shield", "GeoSatya verification", "Completion is checked on the ground and reviewed by a supervisor, with a full audit trail."),
      feature("users", "Isolated workspace", "Your incidents, workers and locations are never visible to another organization or event.")),
    card({ class: "card reveal" }, h("h2", {}, "Verification"),
      h("p", { class: "muted" }, "Registering creates a workspace marked unverified or pending. Kavach's platform team verifies an organization's identity separately. Being on Kavach never implies endorsement by, or affiliation with, a government body."))));
  onCleanup(reveal(main));
}

/* ----------------------------------------------------------------- about */
const MODULES = [
  ["GeoSatya (location verification, incidents, worker tasks, review)", "Divyansh", "geosatya-location-verification", "Core of Kavach.", "GEOSATYA"],
  ["Incident Intelligence (structuring and priority)", "shreyakaushik878-cloud", "incident-intelligence-agent", "Runs after every report; its severity sets the priority.", "INCIDENT_INTELLIGENCE"],
  ["Duplicate Detection", "Yash Dadlani", "duplicate-detection-agent", "Runs on public reports; similar reports are grouped under one primary.", "DUPLICATE_DETECTION"],
  ["Supervisor", "Karanveer Singh Malhotra", "supervisor-agent", "Recommends department, priority, ward and deadlines (advisory).", "SUPERVISOR"],
  ["Sanitation Planning", "Namrata Digarse", "sanitation-work", "Builds a task plan with resources for waste incidents (advisory).", "SANITATION"],
  ["Dispatch (worker ranking)", "ananyadhagat", "dispatch-work", "Ranking algorithm used for every assignment; the 31 Oct update is still to be merged.", "GEOSATYA"],
  ["Verification (visual evidence)", "MrBadDrip", "verification-agent", "Runs inside Kavach on every completion photo: image quality, before/after alignment and GPS (advisory).", "VERIFICATION"],
  ["Field Worker Execution", "shwetamishra1910", "Field-worker-agent", "Reviewed; needs PostgreSQL and overlaps GeoSatya's worker flow.", null],
];

export async function renderAbout({ main, onCleanup }) {
  const status = await agentStatus();
  clear(main, pageHero("About Kavach", "AI-assisted civic intelligence, with humans in charge",
    "Kavach is a student team project. AI suggests and describes; deterministic rules and people make the decisions."),
  h("div", { class: "wrap pub-body" },
    card({ class: "card reveal" }, h("h2", {}, "Who built what"), h("p", { class: "muted" }, "Every module keeps its original author and branch. The status is what is actually wired into this app today."),
      h("div", { class: "attrib" }, h("div", { class: "lbl" }, h("span", {}, "Module"), h("span", {}, "Developer"), h("span", {}, "Branch"), h("span", {}, "Status")),
        MODULES.map(([m, dev, br, st, key]) => {
          const live = key === "GEOSATYA" ? { configured: true, reachable: true } : status.find((x) => x.agent === key);
          return h("div", {}, h("strong", {}, m), h("span", {}, dev), h("span", { class: "mono" }, br),
            h("span", { class: "stack tight" }, h("span", { class: "muted" }, st),
              key ? h("span", { class: `dot ${live?.reachable ? "live" : live?.configured ? "offline" : ""}` },
                live?.reachable ? "Connected on this server" : live?.configured ? "Configured, not answering" : "Not connected on this server") : h("span", { class: "dot" }, "Not integrated yet")));
        }))),
    card({ class: "card reveal" }, h("h2", {}, "Privacy"),
      h("ul", { class: "plain", style: { fontSize: "14.5px", display: "grid", gap: "6px" } },
        h("li", {}, "Workers' locations are shared only during an assigned job, and only with their own workspace."),
        h("li", {}, "The public dashboard shows counts and ~1 km areas, never exact points, names or descriptions."),
        h("li", {}, "Event and organization incidents stay private to that workspace."),
        h("li", {}, "No complaint is described as sent to a government authority unless that really happened."))),
    banner("review", "Development build: sign-in uses demo identities without passwords. Real authentication will replace this before any public launch.")));
  onCleanup(reveal(main));
}

/* ------------------------------------------------------- public tracking */
export async function renderTrack({ main, params, onCleanup }) {
  const ref = (params[0] || "").trim();
  const input = h("input", { type: "search", id: "ref", value: ref, placeholder: "Reference number, e.g. GS-1A2B3C", "aria-label": "Complaint reference number", autocomplete: "off" });
  const result = h("div", { class: "stack" });
  clear(main, pageHero("Track a complaint", "Where is my complaint?", "Enter the reference number you got when you reported. Only the status is shown, never personal details.",
    h("form", { class: "track-search", onsubmit: (e) => { e.preventDefault(); const v = input.value.trim(); if (v) location.hash = `#/track/${encodeURIComponent(v.toUpperCase())}`; } },
      input, h("button", { class: "btn primary big", type: "submit" }, icon("search", 18), "Track"))),
  h("div", { class: "wrap pub-body" }, result));
  if (!ref) {
    const mine = session.me?.role === "CITIZEN" ? await api("/incidents").catch(() => []) : [];
    clear(result, mine.length ? card({}, h("h2", {}, "Your recent reports"), h("div", { class: "items" }, mine.slice(0, 6).map((i) =>
      h("a", { class: "item", href: `#/track/${i.incident_id}` }, h("div", { class: "grow" }, h("strong", {}, i.title), h("span", { class: "muted mono" }, i.incident_id)),
        h("span", { class: "chip" }, i.status_text)))))
      : card({}, emptyState("Enter a reference number", "It looks like GS-1A2B3C and is shown right after you submit a report.")));
    return;
  }
  clear(result, card({}, h("div", { class: "skeleton", style: { height: "120px" } })));
  let t;
  try { t = await api(`/kavach/public/track/${encodeURIComponent(ref)}`); }
  catch (err) { clear(result, card({}, emptyState("No public report found", err.status === 404 ? "Check the reference number. Event and organization-internal incidents are not public." : err.message))); return; }
  const forwarding = { NOT_FORWARDED: "Not forwarded outside Kavach", ROUTED_IN_KAVACH: "Handled by the authority's team on Kavach", FORWARDED_MANUALLY: "Forwarded to the authority by a Kavach supervisor" }[t.forwarding_status];
  clear(result,
    card({ class: "card" },
      h("div", { class: "row between wrap" }, h("div", { class: "stack tight" }, h("span", { class: "lbl" }, "Reference"), h("strong", { class: "mono", style: { fontSize: "18px" } }, t.reference)),
        h("div", { class: "row wrap" }, t.is_demo ? demoTag() : null, h("span", { class: "chip info" }, t.category_label))),
      h("div", { class: "stages", style: { marginTop: "10px" } }, t.stages.map((s) => h("div", { class: `st${s.done ? " done" : ""}${s.current ? " current" : ""}` },
        h("span", { class: "bub" }, s.done ? icon("check", 18) : null), h("span", {}, s.label, h("br"), h("small", {}, s.at ? fmtTime(s.at) : ""))))),
      h("div", { class: "facts" },
        h("div", {}, h("span", { class: "muted" }, "Reported"), h("strong", {}, fmtAgo(t.reported_at))),
        h("div", {}, h("span", { class: "muted" }, "Last update"), h("strong", {}, fmtAgo(t.updated_at))),
        h("div", {}, h("span", { class: "muted" }, "Responsible authority (suggested)"), h("strong", { style: { fontSize: "15px" } }, t.authority?.name || "Kavach civic team")))),
    banner(t.forwarding_status === "NOT_FORWARDED" && t.authority && !t.authority.on_kavach ? "review" : "info", forwarding,
      t.authority && !t.authority.on_kavach && t.forwarding_status === "NOT_FORWARDED" ? ". Kavach has no direct connection to this authority; a supervisor forwards it manually." : "."),
    session.me?.role === "CITIZEN" ? h("a", { class: "btn primary", href: `#/incidents/${t.reference}`, style: { alignSelf: "flex-start" } }, "Open live tracking (your report)") : null);
  void onCleanup;
}

/* ------------------------------------------------------ public dashboard */
export async function renderStats({ main, onCleanup }) {
  const s = await api("/kavach/public/stats");
  const mapEl = h("div", { class: "map tall", role: "img", "aria-label": "Map of reported areas" });
  const max = Math.max(1, ...s.by_category.map((c) => c.count));
  const n = [h("strong", {}), h("strong", {}), h("strong", {}), h("strong", {})];
  clear(main, pageHero("Public dashboard", "Civic reporting, in the open", "Aggregated figures for public civic reports on this Kavach instance. Event and organization-internal incidents are excluded."),
    h("div", { class: "wrap pub-body" },
      h("div", { class: "k-stats", style: { marginTop: "-56px" } },
        h("div", {}, n[0], h("span", {}, "reports")), h("div", {}, n[1], h("span", {}, "resolved")),
        h("div", {}, n[2], h("span", {}, "reported in the last 7 days")), h("div", {}, n[3], h("span", {}, "median time to resolve"))),
      s.includes_demo_data ? banner("demo", "Includes demo records created for testing.") : null,
      h("div", { class: "grid two" },
        card({ class: "card flush reveal" }, h("div", { class: "pad row between" }, h("h2", {}, "Where reports come from"), h("span", { class: "muted" }, "~1 km areas")), mapEl),
        card({ class: "card reveal d1" }, h("h2", {}, "By category"),
          s.by_category.length ? h("div", { class: "bars" }, s.by_category.map((c) => h("div", { class: "bar-row" }, h("span", {}, c.label),
            h("span", { class: "track" }, h("span", { "data-w": String((100 * c.count) / max) })), h("strong", {}, String(c.count)))))
            : emptyState("No reports yet"),
          h("h2", { style: { marginTop: "8px" } }, "By stage"),
          h("div", { class: "bars" }, s.by_status.map((c) => h("div", { class: "bar-row" }, h("span", {}, c.label),
            h("span", { class: "track" }, h("span", { "data-w": String(s.total ? (100 * c.count) / s.total : 0) })), h("strong", {}, String(c.count)))))))));
  countUp(n[0], s.total); countUp(n[1], s.resolved); countUp(n[2], s.reported_this_week);
  n[3].textContent = hours(s.median_resolution_hours);
  requestAnimationFrame(() => main.querySelectorAll("[data-w]").forEach((el) => { el.style.width = `${el.dataset.w}%`; }));
  onCleanup(reveal(main));
  setTimeout(async () => {
    const map = await createMap(mapEl, { center: [23.2599, 77.4126], zoom: 11 });
    onCleanup(() => map.destroy());
    s.areas.forEach((a, i) => map.circle(`a${i}`, [a.latitude, a.longitude], 300 + Math.min(a.count, 25) * 70, "area"));
    if (s.areas.length > 1) map.fit(s.areas.map((a) => [a.latitude, a.longitude]));
    else if (s.areas.length === 1) map.setView([s.areas[0].latitude, s.areas[0].longitude], 13);
  });
}
