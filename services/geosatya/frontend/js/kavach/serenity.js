/* Digital Serenity, ported from the supplied React landing component
   (components/ui/digital-serenity-animated-landing-page.tsx) and tuned for KAVACH:
   a drawing grid with pulsing detail dots, corner marks, floating particles, word-by-word
   typography, a mouse-following glow and click ripples.

   Differences from the original, on purpose:
   - everything is scoped to the hero element (no document-wide listeners left behind);
   - the glow moves with transform inside requestAnimationFrame (one write per frame, no React state);
   - ripples are capped, removed on animationend, and never block clicks;
   - prefers-reduced-motion shows the final state with no motion;
   - floating particles start when the hero is on screen, not on the first scroll. */

import { h } from "../ui.js";

const SVGNS = "http://www.w3.org/2000/svg";
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function gridSvg(id) {
  const svg = document.createElementNS(SVGNS, "svg");
  svg.setAttribute("class", "ser-grid");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = `<defs><pattern id="${id}" width="60" height="60" patternUnits="userSpaceOnUse"><path d="M 60 0 L 0 0 0 60" fill="none" class="ser-cell"/></pattern></defs>
    <rect width="100%" height="100%" fill="url(#${id})"/>
    <line x1="0" y1="20%" x2="100%" y2="20%" class="ser-line" style="animation-delay:.5s"/>
    <line x1="0" y1="80%" x2="100%" y2="80%" class="ser-line" style="animation-delay:1s"/>
    <line x1="20%" y1="0" x2="20%" y2="100%" class="ser-line" style="animation-delay:1.5s"/>
    <line x1="80%" y1="0" x2="80%" y2="100%" class="ser-line" style="animation-delay:2s"/>
    <line x1="50%" y1="0" x2="50%" y2="100%" class="ser-line faint" style="animation-delay:2.5s"/>
    <line x1="0" y1="50%" x2="100%" y2="50%" class="ser-line faint" style="animation-delay:3s"/>
    <circle cx="20%" cy="20%" r="2" class="ser-dot" style="animation-delay:3s"/>
    <circle cx="80%" cy="20%" r="2" class="ser-dot" style="animation-delay:3.2s"/>
    <circle cx="20%" cy="80%" r="2" class="ser-dot" style="animation-delay:3.4s"/>
    <circle cx="80%" cy="80%" r="2" class="ser-dot" style="animation-delay:3.6s"/>
    <circle cx="50%" cy="50%" r="1.5" class="ser-dot" style="animation-delay:4s"/>`;
  return svg;
}

/* Words that rise in one by one. `lines` is [[text, className?], ...]; delays continue across lines. */
function words(text, start, step) {
  return text.split(" ").map((w, i) => h("span", { class: "ser-word", style: { animationDelay: `${start + i * step}ms` } }, w));
}

/* Returns { el, destroy }. top / title / subtitle / bottom are plain strings; actions are nodes. */
export function serenityHero({ top, title, subtitle, bottom, actions, aside }) {
  const titleWords = title.split(" ").length, subStart = 700 + titleWords * 150 + 250;
  const subWords = subtitle.split(" ").length, bottomStart = subStart + subWords * 110 + 250;
  const glow = h("div", { class: "ser-glow", "aria-hidden": "true" });
  const ripples = h("div", { class: "ser-ripples", "aria-hidden": "true" });
  const floats = [["25%", "15%", ".5s"], ["60%", "85%", "1s"], ["40%", "10%", "1.5s"], ["75%", "90%", "2s"], ["18%", "62%", "2.4s"], ["86%", "34%", "2.8s"]]
    .map(([t, l, d]) => h("div", { class: "ser-float", style: { top: t, left: l, animationDelay: d } }));
  const el = h("section", { class: "ser", "aria-labelledby": "ser-title" },
    gridSvg(`ser-grid-${Math.random().toString(36).slice(2, 7)}`),
    ["tl", "tr", "bl", "br"].map((c, i) => h("div", { class: `ser-corner ${c}`, style: { animationDelay: `${4 + i * 0.2}s` }, "aria-hidden": "true" }, h("i"))),
    floats, glow, ripples,
    h("div", { class: "ser-in" },
      h("div", { class: "ser-top" }, h("p", { class: "ser-mono" }, words(top, 0, 300)), h("div", { class: "ser-rule" })),
      h("div", { class: "ser-mid" },
        h("h1", { id: "ser-title", class: "ser-title" }, h("span", { class: "ser-l1" }, words(title, 700, 150)), h("span", { class: "ser-l2" }, words(subtitle, subStart, 110))),
        h("span", { class: "ser-tick left", style: { animationDelay: `${(bottomStart - 400) / 1000}s` }, "aria-hidden": "true" }),
        h("span", { class: "ser-tick right", style: { animationDelay: `${(bottomStart - 200) / 1000}s` }, "aria-hidden": "true" }),
        actions ? h("div", { class: "ser-actions", style: { animationDelay: `${bottomStart / 1000}s` } }, actions) : null),
      h("div", { class: "ser-bottom" }, h("div", { class: "ser-rule" }), h("p", { class: "ser-mono" }, words(bottom, bottomStart, 200)),
        h("div", { class: "ser-trio", style: { animationDelay: `${(bottomStart + 900) / 1000}s` }, "aria-hidden": "true" }, h("i"), h("i"), h("i")))),
    aside || null);

  if (reduced()) { el.classList.add("still"); return { el, destroy() {} }; }

  // Mouse-following glow: one transform per animation frame.
  let raf = 0, gx = 0, gy = 0;
  const move = (e) => {
    const box = el.getBoundingClientRect();
    gx = e.clientX - box.left; gy = e.clientY - box.top;
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; glow.style.transform = `translate3d(${gx}px, ${gy}px, 0) translate(-50%, -50%)`; glow.style.opacity = "1"; });
  };
  const leave = () => { glow.style.opacity = "0"; };
  // Click ripples inside the hero only; at most 6 at a time.
  const click = (e) => {
    if (ripples.childElementCount >= 6) ripples.firstElementChild?.remove();
    const box = el.getBoundingClientRect();
    const r = h("i", { style: { left: `${e.clientX - box.left}px`, top: `${e.clientY - box.top}px` } });
    r.addEventListener("animationend", () => r.remove(), { once: true });
    ripples.append(r);
  };
  el.addEventListener("pointermove", move);
  el.addEventListener("pointerleave", leave);
  el.addEventListener("click", click);
  // Particles drift only while the hero is visible.
  const io = "IntersectionObserver" in window ? new IntersectionObserver(([e]) => el.classList.toggle("live", e.isIntersecting), { threshold: 0.05 }) : null;
  io ? io.observe(el) : el.classList.add("live");
  return {
    el,
    destroy() { cancelAnimationFrame(raf); el.removeEventListener("pointermove", move); el.removeEventListener("pointerleave", leave); el.removeEventListener("click", click); io?.disconnect(); },
  };
}
