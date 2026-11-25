/* Team Codyssey: an interactive lanyard wall (the supplied TeamLanyardRail, ported) and a
   readable profile panel for whoever is selected. Used as its own page (#/team) and on the home page. */

import { h, icon } from "../ui.js";
import { lanyardRail } from "./lanyard.js";
import { TEAM } from "./team-data.js";

const initials = (name) => name.split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();

/* The rail plus the profile panel. Returns { el, destroy }. */
export function teamShowcase({ autoplay = true, compact = false } = {}) {
  const panel = h("div", { class: "team-panel glass", "aria-live": "polite" });
  const show = (i) => {
    const m = i === null || i === undefined ? null : TEAM[i];
    if (!m) {
      panel.replaceChildren(h("div", { class: "team-panel-empty" }, icon("users", 22),
        h("p", {}, "Brush along the rail, pull a badge down, or click one to flip it and read what that person built.")));
      return;
    }
    const face = m.image ? h("img", { src: m.image, alt: `Photo of ${m.name}`, width: 96, height: 96 }) : h("span", { class: "team-initials", "aria-hidden": "true" }, initials(m.name));
    panel.replaceChildren(h("div", { class: `team-photo lr-tone-${m.tone}` }, face),
      h("div", { class: "team-info" },
        h("p", { class: "team-team" }, m.team), h("h3", {}, m.name), h("p", { class: "team-role" }, m.role),
        h("p", { class: "team-bio" }, m.bio),
        h("div", { class: "team-tags" }, m.tags.map((t) => h("span", { class: "team-tag" }, t)))));
  };
  const rail = lanyardRail({
    items: TEAM, autoplay,
    eyebrow: compact ? "Team Codyssey · Ten people" : null,
    heading: compact ? "The people who built KAVACH" : null,
    caption: "Hover along the rail to meet someone · pull a badge down · click to flip it",
    onSelect: show,
  });
  show(null);
  const el = h("div", { class: `team-showcase${compact ? " compact" : ""}` }, rail.el, panel,
    h("ul", { class: "team-roll", "aria-label": "Team members" }, TEAM.map((m, i) => h("li", {},
      h("button", { type: "button", class: "team-chip", onclick: () => rail.flip(i) },
        m.image ? h("img", { src: m.image, alt: "", width: 28, height: 28, loading: "lazy" }) : h("span", { class: "team-initials sm", "aria-hidden": "true" }, initials(m.name)),
        h("span", {}, h("strong", {}, m.name), h("small", {}, m.role)))))));
  return { el, destroy: rail.destroy };
}

export function renderTeam({ main, onCleanup }) {
  const show = teamShowcase({ autoplay: true });
  onCleanup?.(show.destroy);
  main.replaceChildren(h("div", { class: "aur-page" },
    h("header", { class: "aur-pagehead wrap" },
      h("p", { class: "aur-eyebrow" }, "Team Codyssey"),
      h("h1", {}, "Ten people, one platform."),
      h("p", { class: "aur-lede" }, "Each agent in KAVACH was built by one of us: from understanding a complaint to sending the right worker and checking the work on the ground. Namrata leads the team.")),
    h("div", { class: "wrap team-wide" }, show.el)));
}
