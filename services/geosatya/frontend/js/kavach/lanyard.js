/* TeamLanyardRail, ported from the supplied React component (components/ui/team-lanyard-rail.tsx)
   to the app's plain ES modules. Same geometry, spring physics, swing, pull-down reel, drag along
   the rail, flip, carousel on narrow screens, autoplay, keyboard and reduced-motion behaviour.
   The DOM is built once per size; every frame only writes transforms (no re-render per frame). */

import { h } from "../ui.js";

const RATIO = 96 / 62, MAX_W = 124, MIN_RAIL_W = 100, EM = 11.2;
const RAIL_PITCH_MIN = 1.16, RAIL_PITCH_MAX = 1.62, CAROUSEL_PITCH = 1.2, GAP = 0.07, PERSPECTIVE = 900, MAX_STRETCH = 64;
const FIRST_DELAY = 1100, FLIP_DELAY = 700, SWING_K = 28, SWING_DAMP = 2.2, LAG = 0.12, REEL_K = 220, REEL_ZETA = 0.5;
const REST_Y = [9, -10, 7, -8, 10, -7, 8, -9], REST_Z = [-1.6, 1.2, -2, 1.5, -1, 1.8, -1.3, 2], DROPS = [6, 20, 0, 13, 22, 4, 16, 9];
const DEFAULT_LABELS = { flip: "Click or press Enter to flip the badge", back: "Click again or press Esc to turn it back", show: "Show" };
const SVGNS = "http://www.w3.org/2000/svg";
const KEYS = ["x", "vx", "px", "tx", "sw", "vsw", "beta", "ry", "vry", "tr", "rz", "vrz", "tz", "lift", "vlift", "tl", "pop", "vpop", "tp", "st", "vst"];

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
function hash(text) { let x = 2166136261; for (let i = 0; i < text.length; i++) { x ^= text.charCodeAt(i); x = Math.imul(x, 16777619); } return x >>> 0; }
function random(seed) {
  let a = seed || 1;
  return () => { a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
function qrPath(seed) {
  const size = 21, next = random(seed), corners = [[0, 0], [size - 7, 0], [0, size - 7]];
  let d = "";
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const corner = corners.find(([cx, cy]) => x >= cx && x < cx + 7 && y >= cy && y < cy + 7);
    const quiet = (x < 8 && y < 8) || (x >= size - 8 && y < 8) || (x < 8 && y >= size - 8);
    let on;
    if (corner) on = Math.max(Math.abs(x - corner[0] - 3), Math.abs(y - corner[1] - 3)) !== 2;
    else if (quiet) on = false;
    else if (x === 6 || y === 6) on = (x + y) % 2 === 0;
    else on = next() > 0.52;
    if (on) d += `M${x} ${y}h1v1h-1z`;
  }
  return d;
}
function barcode(seed) {
  const next = random(seed ^ 0x9e3779b9); let x = 0, d = "";
  while (x < 92) { const w = 1 + Math.floor(next() * 3); d += `M${x} 0h${w}v20h-${w}z`; x += w + 1 + Math.floor(next() * 2.2); }
  return { d, width: x };
}
function soft(distance, max) { const knee = max * 0.75; return distance <= knee ? distance : knee + (max - knee) * (1 - Math.exp(-(distance - knee) / (max - knee))); }

function geometry(W, items) {
  const u = W / MAX_W, H = W * RATIO, railR = Math.max(3, 4.2 * u), railY = 14 + railR, ring = 9 * u, pivotY = railY + ring * 0.8;
  const strapW = Math.max(8, 11 * u), crimp = 6 * u, reel = 21 * u, cordRest = 12 * u, clipH = 13 * u, clipW = 30 * u, base = 56 * u;
  const straps = items.map((item, i) => base + Math.max(0, item.drop ?? DROPS[i % DROPS.length] ?? 0) * u);
  const reelTops = straps.map((len) => pivotY + len + crimp * 0.6);
  const clipTops = reelTops.map((top) => top + reel * 0.82 + cordRest);
  const cardTops = clipTops.map((top) => top + clipH * 0.62);
  const pendulum = cardTops.map((top) => top + H / 2 - pivotY);
  const restLength = pivotY + base + crimp * 0.6 + reel * 0.82 + cordRest + clipH * 0.62 + H / 2 - pivotY;
  const bottom = Math.max(0, ...cardTops.map((top) => top + H));
  return { W, H, u, railR, railY, ring, pivotY, strapW, crimp, reel, cordRest, clipH, clipW, straps, reelTops, clipTops, cardTops, pendulum,
    swingK: pendulum.map((len) => (SWING_K * restLength) / len), couple: pendulum.map((len) => (0.25 * 57.3) / len),
    maxStretch: Math.round(MAX_STRETCH * Math.min(1, W / 118)), height: Math.ceil(bottom + 16 * u + 8) };
}
function layoutTargets(width, W, carousel, center, count) {
  if (!carousel) {
    const pitch = clamp((width - 40 - W * 0.6) / Math.max(1, count), W * RAIL_PITCH_MIN, W * RAIL_PITCH_MAX);
    const start = width / 2 - (pitch * (count - 1)) / 2;
    return { xs: Array.from({ length: count }, (_, i) => start + i * pitch), total: 0 };
  }
  const pitch = W * CAROUSEL_PITCH, total = pitch * count, cyclic = count > 2 && total >= width + W * 2, c = center ?? 0;
  const xs = Array.from({ length: count }, (_, i) => {
    let k = i - c;
    if (cyclic) { k = ((k % count) + count) % count; if (k >= count / 2) k -= count; }
    return width / 2 + k * pitch;
  });
  return { xs, total: cyclic ? total : 0 };
}
function spring(value, velocity, target, i, k, zeta, dt) {
  const v = velocity[i] ?? 0, x = value[i] ?? 0, next = v + (-k * (x - target) - 2 * zeta * Math.sqrt(k) * v) * dt;
  velocity[i] = next; value[i] = x + next * dt;
}
const badgeWidth = (s, W, i) => W * (1 + 0.08 * (s.pop[i] ?? 0));
const minGap = (s, W, a, b) => (badgeWidth(s, W, a) + badgeWidth(s, W, b)) / 2 + W * GAP;
const stops = (s, W, width, count) => [W * 0.32 + badgeWidth(s, W, 0) / 2, width - W * 0.32 - badgeWidth(s, W, count - 1) / 2];
function cardEdge(s, g, i, side) {
  const theta = ((s.sw[i] ?? 0) * Math.PI) / 180, psi = (((s.beta[i] ?? 0) + (s.rz[i] ?? 0)) * Math.PI) / 180, scale = 1 + 0.08 * (s.pop[i] ?? 0);
  const clipDepth = (g.clipTops[i] ?? 0) + (s.st[i] ?? 0) - 4 * (s.lift[i] ?? 0) - g.pivotY, offset = (g.cardTops[i] ?? 0) - (g.clipTops[i] ?? 0);
  const cx = (s.x[i] ?? 0) - clipDepth * Math.sin(theta), half = (g.W / 2) * scale * Math.cos(psi) * side;
  return [cx + half - offset * scale * Math.sin(psi), cx + half - (offset + g.H) * scale * Math.sin(psi), clipDepth + offset * scale, clipDepth + (offset + g.H) * scale];
}
const emptySim = () => Object.assign(Object.fromEntries(KEYS.map((k) => [k, []])), { drag: -1, grab: 0, pull: -1, free: 0, last: 0, raf: 0, carousel: null });

function svg(viewBox, cls, d, extra = {}) {
  const el = document.createElementNS(SVGNS, "svg");
  el.setAttribute("viewBox", viewBox); el.setAttribute("aria-hidden", "true"); el.setAttribute("class", cls);
  for (const [k, v] of Object.entries(extra)) el.setAttribute(k, v);
  if (d) { const p = document.createElementNS(SVGNS, "path"); p.setAttribute("d", d); p.setAttribute("fill", "currentColor"); el.append(p); }
  return el;
}
const span = (cls, style, ...kids) => h("span", { class: cls, style, "aria-hidden": cls.includes("lr-text") ? null : "true" }, ...kids);
const finish = () => [span("lr-gloss"), span("lr-shade")];
const band = (tall, tone) => span(`lr-band ${tone}${tall ? " tall" : ""}`, null, span("lr-band-line"));

function badgeFaces(item, tone) {
  const seed = hash(`${item.id}:${item.name}`), bars = barcode(seed), digits = String(seed % 1000000000).padStart(9, "0");
  const portrait = h("span", { class: "lr-ava-in" }, svg("0 0 40 40", "lr-silhouette", "M20 8a7 7 0 1 1 0 14a7 7 0 1 1 0-14zM6 38c1.5-8 7-12 14-12s12.5 4 14 12z"));
  if (item.image) {
    const img = h("img", { src: item.image, alt: "", draggable: "false", decoding: "async", class: "lr-img" });
    img.addEventListener("error", () => img.remove());
    portrait.append(img);
  }
  const front = h("span", { class: "lr-face front", "data-face": "front" }, band(true, tone), span("lr-hole"),
    h("span", { class: "lr-ava" }, portrait),
    h("span", { class: "lr-name" }, item.name), h("span", { class: "lr-role" }, item.role),
    item.team ? h("span", { class: "lr-team" }, item.team) : null,
    h("span", { class: "lr-foot" }, svg(`0 0 ${bars.width} 20`, "lr-bars", bars.d, { preserveAspectRatio: "none" }), h("span", { class: "lr-digits" }, digits)),
    ...finish());
  const back = h("span", { class: "lr-face back", "data-face": "back" }, band(false, tone), span("lr-hole"),
    h("span", { class: "lr-back-head" }, h("span", { class: "lr-bname" }, item.name), h("span", { class: "lr-brole" }, item.role)),
    item.bio ? h("span", { class: "lr-bio" }, item.bio) : null,
    (item.tags || []).length ? h("span", { class: "lr-tags" }, item.tags.slice(0, 3).map((t) => h("span", { class: "lr-tag" }, t))) : null,
    svg("-1 -1 23 23", "lr-qr", qrPath(seed)), ...finish());
  return [front, back, span("lr-edge left"), span("lr-edge right")];
}

/* Returns { el, destroy }. onSelect(index|null) fires when the badge facing front changes. */
export function lanyardRail({ items, eyebrow, heading, caption = "", autoplay = false, interval = 2800, labels = DEFAULT_LABELS, onSelect } = {}) {
  const count = items.length;
  const S = { active: null, flipped: null, focusIndex: 0, carouselIndex: 0, cyclic: false, reduced: matchMedia("(prefers-reduced-motion: reduce)").matches,
    playing: autoplay, size: { width: 0, W: MAX_W, carousel: false }, geo: geometry(MAX_W, items), prev: { active: null, flipped: null } };
  const sim = emptySim();
  const R = { slots: [], swings: [], straps: [], cords: [], hangs: [], buttons: [], flips: [], shadows: [] };
  const pointer = { id: -1, index: -1, x: 0, y: 0, mode: "", kind: "", lastX: 0, lastY: 0, lastT: 0, v: 0, swipe: 0, hoverX: 0, hoverT: 0, hoverHit: -1 };
  let pendingOpen = -1, autoTimer = 0, swayed = false;
  const uid = "lr" + Math.random().toString(36).slice(2, 8);

  const stage = h("div", { class: "lr-stage", "data-stage": "", role: "group", "aria-label": heading || "Team", "aria-roledescription": "lanyard rail" });
  const dots = h("div", { class: "lr-dots", role: "group", "aria-label": labels.show });
  const line1 = h("p", { class: "lr-line1" }, caption), line2 = h("p", { class: "lr-line2" }), srBio = h("span", { class: "visually-hidden" });
  const root = h("section", { class: "lr", "data-slot": "team-lanyard-rail" },
    span("lr-glow"), span("lr-dotgrid"),
    eyebrow || heading ? h("header", { class: "lr-head" }, eyebrow ? h("p", { class: "lr-eyebrow" }, eyebrow) : null, heading ? h("h2", {}, heading) : null) : null,
    stage, dots, h("div", { class: "lr-caption", id: `${uid}-caption`, "aria-live": "polite" }, line1, line2, srBio));

  /* ------------------------------------------------------------------ painting */
  function paint(i) {
    const s = sim, g = S.geo, slot = R.slots[i];
    if (!slot) return;
    slot.style.transform = `translate3d(${((s.x[i] ?? 0) - g.W / 2).toFixed(2)}px,0,0)`;
    const sw = s.sw[i] ?? 0;
    if (R.swings[i]) R.swings[i].style.transform = `rotate(${sw.toFixed(3)}deg)`;
    const st = s.st[i] ?? 0;
    if (R.cords[i]) R.cords[i].style.transform = `scaleY(${Math.max(0.12, (g.cordRest + st) / g.cordRest).toFixed(4)})`;
    const lift = s.lift[i] ?? 0, pop = s.pop[i] ?? 0;
    if (R.hangs[i]) R.hangs[i].style.transform = `translate3d(0,${(st - 4 * lift).toFixed(2)}px,0) rotate(${((s.beta[i] ?? 0) - sw + (s.rz[i] ?? 0)).toFixed(3)}deg) scale(${(1 + 0.08 * pop).toFixed(4)})`;
    const ry = s.ry[i] ?? 0, flip = R.flips[i], facing = Math.abs(Math.cos((ry * Math.PI) / 180));
    if (flip) {
      flip.style.transform = `perspective(${PERSPECTIVE}px) rotateY(${ry.toFixed(2)}deg)`;
      flip.style.setProperty("--shade", ((1 - facing) * 0.45).toFixed(3));
      const phi = ((((ry + 90) % 180) + 180) % 180) - 90;
      flip.style.setProperty("--gx", `${(phi * 0.9).toFixed(1)}%`);
    }
    const sh = R.shadows[i];
    if (sh) {
      sh.style.transform = `translate3d(${(g.W * 0.045 + lift * 3 * g.u).toFixed(2)}px,${(g.H * 0.03 + lift * 7 * g.u).toFixed(2)}px,0) scale(${(Math.max(0.12, facing) * (1 + 0.03 * lift + 0.05 * pop)).toFixed(3)},${(1 + 0.03 * lift + 0.05 * pop).toFixed(3)})`;
      sh.style.opacity = (0.72 + 0.28 * lift).toFixed(3);
    }
  }

  function step(now) {
    const s = sim, n = count, g = S.geo, { width, carousel } = S.size;
    const dt = s.last ? Math.min(0.1, (now - s.last) / 1000) : 1 / 60;
    s.last = now;
    const sub = Math.max(3, Math.ceil(dt / 0.006)), hh = dt / sub;
    let busy = false;
    for (let k = 0; k < sub; k++) {
      for (let i = 0; i < n; i++) {
        const before = s.vx[i] ?? 0;
        if (i !== s.drag) {
          const ax = now > s.free ? -130 * ((s.x[i] ?? 0) - (s.tx[i] ?? 0)) - 2 * Math.sqrt(130) * 0.86 * before : -3.2 * before;
          s.vx[i] = before + ax * hh; s.x[i] = (s.x[i] ?? 0) + s.vx[i] * hh;
        }
      }
      if (!carousel && n > 0) {
        const [left, right] = stops(s, g.W, width, n);
        if (s.drag >= 0) {
          const d = s.drag;
          for (let j = d - 1; j >= 0; j--) { const lim = s.x[j + 1] - minGap(s, g.W, j, j + 1); if (s.x[j] > lim) { s.x[j] = lim; s.vx[j] = Math.min(s.vx[j], s.vx[j + 1]); } }
          for (let j = d + 1; j < n; j++) { const lim = s.x[j - 1] + minGap(s, g.W, j - 1, j); if (s.x[j] < lim) { s.x[j] = lim; s.vx[j] = Math.max(s.vx[j], s.vx[j - 1]); } }
        } else {
          for (let pass = 0; pass < 3; pass++) for (let j = 0; j < n - 1; j++) {
            const a = s.x[j], b = s.x[j + 1], overlap = minGap(s, g.W, j, j + 1) - (b - a);
            if (overlap <= 0) continue;
            s.x[j] = a - overlap / 2; s.x[j + 1] = b + overlap / 2;
            if (s.vx[j] > s.vx[j + 1]) { const shared = (s.vx[j] + s.vx[j + 1]) / 2; s.vx[j] = shared; s.vx[j + 1] = shared; }
          }
          if (s.x[0] < left) { s.x[0] = left; s.vx[0] = Math.abs(s.vx[0]) * 0.3; }
          for (let j = 1; j < n; j++) s.x[j] = Math.max(s.x[j], s.x[j - 1] + minGap(s, g.W, j - 1, j));
          if (s.x[n - 1] > right) { s.x[n - 1] = right; s.vx[n - 1] = -Math.abs(s.vx[n - 1]) * 0.3; }
          for (let j = n - 2; j >= 0; j--) s.x[j] = Math.min(s.x[j], s.x[j + 1] - minGap(s, g.W, j, j + 1));
        }
      }
      for (let i = 0; i < n; i++) {
        const dv = (s.vx[i] ?? 0) - (s.px[i] ?? 0);
        s.px[i] = s.vx[i] ?? 0;
        if (i !== s.pull) {
          const sw = s.sw[i] ?? 0, vsw = clamp((s.vsw[i] ?? 0) + (g.couple[i] ?? 0.07) * clamp(dv, -900, 900), -90, 90);
          const next = vsw + (-(g.swingK[i] ?? SWING_K) * sw - SWING_DAMP * vsw) * hh;
          s.vsw[i] = next; s.sw[i] = clamp(sw + next * hh, -18, 18);
        }
        s.beta[i] = (s.beta[i] ?? 0) + ((s.sw[i] ?? 0) - (s.beta[i] ?? 0)) * Math.min(1, hh / LAG);
        spring(s.ry, s.vry, s.tr[i] ?? 0, i, 170, 0.62, hh);
        spring(s.rz, s.vrz, s.tz[i] ?? 0, i, 120, 0.8, hh);
        spring(s.lift, s.vlift, s.tl[i] ?? 0, i, 200, 0.75, hh);
        spring(s.pop, s.vpop, s.tp[i] ?? 0, i, 160, 0.55, hh);
        if (i !== s.pull) { spring(s.st, s.vst, 0, i, REEL_K, REEL_ZETA, hh); s.st[i] = Math.max(-g.cordRest * 0.85, s.st[i] ?? 0); }
      }
      for (let a = 0; a < n - 1; a++) {
        const b = a + 1;
        if (s.x[b] <= s.x[a]) continue;
        const [aTop, aBottom, aArmTop, aArmBottom] = cardEdge(s, g, a, 1), [bTop, bBottom, bArmTop, bArmBottom] = cardEdge(s, g, b, -1);
        const topExcess = aTop - bTop + 2, bottomExcess = aBottom - bBottom + 2, excess = Math.max(topExcess, bottomExcess);
        if (excess <= 0) continue;
        const arm = Math.max(40, topExcess > bottomExcess ? (aArmTop + bArmTop) / 2 : (aArmBottom + bArmBottom) / 2);
        const push = (Math.asin(clamp(excess / arm, 0, 1)) * 180) / Math.PI, share = a === s.pull ? 0 : b === s.pull ? 1 : 0.5;
        s.sw[a] = clamp(s.sw[a] + push * share, -18, 18); s.beta[a] += push * share;
        s.sw[b] = clamp(s.sw[b] - push * (1 - share), -18, 18); s.beta[b] -= push * (1 - share);
        const va = s.vsw[a], vb = s.vsw[b];
        if (vb - va > 0) { const mean = (va + vb) / 2; if (a !== s.pull) s.vsw[a] = mean + (vb - va) * 0.15; if (b !== s.pull) s.vsw[b] = mean - (vb - va) * 0.15; }
      }
    }
    for (let i = 0; i < n; i++) {
      paint(i);
      if (Math.abs(s.vx[i]) > 0.4 || (now > s.free && Math.abs(s.x[i] - s.tx[i]) > 0.25) || Math.abs(s.ry[i] - s.tr[i]) > 0.05 || Math.abs(s.vry[i]) > 0.05 ||
        Math.abs(s.rz[i] - s.tz[i]) > 0.02 || Math.abs(s.vrz[i]) > 0.05 || Math.abs(s.lift[i] - s.tl[i]) > 0.002 || Math.abs(s.vlift[i]) > 0.01 ||
        Math.abs(s.pop[i] - s.tp[i]) > 0.002 || Math.abs(s.vpop[i]) > 0.01 || Math.abs(s.sw[i]) > 0.02 || Math.abs(s.vsw[i]) > 0.05 ||
        Math.abs(s.beta[i] - s.sw[i]) > 0.01 || Math.abs(s.st[i]) > 0.05 || Math.abs(s.vst[i]) > 0.1) busy = true;
    }
    if (s.drag >= 0 || s.pull >= 0 || now < s.free) busy = true;
    if (busy) s.raf = requestAnimationFrame(step);
    else { s.raf = 0; s.last = 0; for (let i = 0; i < n; i++) { if (now > s.free) { s.x[i] = s.tx[i]; s.vx[i] = 0; s.px[i] = 0; } settle(i); paint(i); } }
  }
  function settle(i) {
    const s = sim;
    s.sw[i] = 0; s.vsw[i] = 0; s.beta[i] = 0; if (i !== s.pull) { s.st[i] = 0; s.vst[i] = 0; }
    s.ry[i] = s.tr[i]; s.vry[i] = 0; s.rz[i] = s.tz[i]; s.vrz[i] = 0; s.lift[i] = s.tl[i]; s.vlift[i] = 0; s.pop[i] = s.tp[i]; s.vpop[i] = 0;
  }
  function snap() { for (let i = 0; i < count; i++) { sim.x[i] = sim.tx[i]; sim.vx[i] = 0; sim.px[i] = 0; settle(i); paint(i); } }
  function kick() {
    if (S.reduced) { cancelAnimationFrame(sim.raf); sim.raf = 0; snap(); return; }
    if (!sim.raf) { sim.last = 0; sim.raf = requestAnimationFrame(step); }
  }
  const impulse = (i, amount) => { if (S.reduced || i < 0 || i >= count) return; sim.vsw[i] = (sim.vsw[i] ?? 0) + amount; kick(); };
  const tug = (i, amount) => { if (S.reduced || i < 0 || i >= count) return; sim.vst[i] = (sim.vst[i] ?? 0) + amount; kick(); };

  /* ------------------------------------------------------------------ state */
  function targets(fresh) {
    if (!S.size.width) return;
    const { width, W, carousel } = S.size, s = sim;
    const center = carousel ? (S.active ?? S.carouselIndex) : null;
    const { xs, total } = layoutTargets(width, W, carousel, center, count);
    S.cyclic = total > 0;
    fresh = fresh || s.x.length !== count || s.carousel !== carousel;
    s.carousel = carousel;
    for (let i = 0; i < count; i++) {
      const tx = xs[i] + (carousel ? pointer.swipe : 0);
      if (!fresh && total > 0) { const shift = Math.round((tx - (s.tx[i] ?? tx)) / total) * total; if (shift) s.x[i] += shift; }
      s.tx[i] = tx;
      const front = S.flipped === i || S.active === i;
      s.tr[i] = S.flipped === i ? 180 : S.active === i ? 0 : REST_Y[i % REST_Y.length];
      s.tz[i] = front ? 0 : REST_Z[i % REST_Z.length];
      s.tl[i] = front ? 1 : 0;
      s.tp[i] = S.flipped === i ? 1 : 0;
      if (fresh) { s.x[i] = tx; s.vx[i] = 0; s.px[i] = 0; settle(i); s.st[i] = 0; s.vst[i] = 0; }
    }
    for (const key of KEYS) s[key].length = count;
    if (fresh) for (let i = 0; i < count; i++) paint(i);
    kick();
  }

  function sync() {
    const { active, flipped } = S;
    R.slots.forEach((slot, i) => { slot.style.zIndex = flipped === i ? 40 : active === i ? 30 : 10 + i; });
    R.buttons.forEach((b, i) => {
      b.dataset.flipped = String(flipped === i); b.setAttribute("aria-pressed", String(flipped === i));
      if (active === i) b.dataset.active = "true"; else delete b.dataset.active;
      b.tabIndex = i === (active ?? S.focusIndex) ? 0 : -1;
    });
    const current = active ?? flipped, person = current === null ? null : items[current];
    const back = current !== null && current === flipped;
    line1.textContent = person ? `${person.name} — ${person.role}` : caption;
    line2.textContent = person ? (back ? labels.back : labels.flip) : "";
    srBio.textContent = back && person?.bio ? person.bio : "";
    root.dataset.active = active ?? ""; root.dataset.flipped = flipped ?? "";
    const center = S.size.carousel ? (active ?? S.carouselIndex) : null;
    [...dots.children].forEach((d, i) => { d.setAttribute("aria-current", String(center === i)); d.classList.toggle("on", center === i); });
    targets(false);
    // the neighbours sway when a badge comes forward or flips
    const old = S.prev, wrap = (i) => (S.cyclic ? ((i % count) + count) % count : i);
    if (old.active !== active) {
      if (active !== null) { impulse(wrap(active - 1), 16); impulse(wrap(active + 1), -16); }
      if (old.active !== null) { impulse(wrap(old.active - 1), -6); impulse(wrap(old.active + 1), 6); }
    }
    if (old.flipped !== flipped) {
      if (flipped !== null) { impulse(flipped, flipped % 2 ? 9 : -9); tug(flipped, 70); }
      if (old.flipped !== null) tug(old.flipped, 40);
    }
    if (old.active !== active || old.flipped !== flipped) onSelect?.(current);
    S.prev = { active, flipped };
  }
  function setActive(i) { if (S.active === i) return; S.active = i; if (i !== null) S.carouselIndex = i; sync(); }
  function setFlipped(i) { if (S.flipped === i) return; S.flipped = i; sync(); }
  function stop() { S.playing = false; clearTimeout(autoTimer); }
  function toggle(i) { stop(); const next = S.flipped === i ? null : i; if (next !== null) { S.active = i; S.carouselIndex = i; } S.flipped = next; sync(); }

  function play() {
    clearTimeout(autoTimer);
    if (!S.playing || S.reduced || !count || !S.size.width) return;
    const front = (i) => { setActive(i); autoTimer = setTimeout(() => flip(i), FLIP_DELAY); };
    const flip = (i) => { if (!S.playing) return; setFlipped(i); autoTimer = setTimeout(() => { if (!S.playing) return; setFlipped(null); front((i + 1) % count); }, interval); };
    autoTimer = S.active === null ? setTimeout(() => front(0), FIRST_DELAY) : setTimeout(() => flip(S.active), FLIP_DELAY);
  }

  /* ------------------------------------------------------------------ DOM */
  function build() {
    const g = S.geo, W = g.W, base = W / EM;
    stage.style.height = `${g.height}px`;
    for (const key of Object.keys(R)) R[key] = [];
    const rail = h("div", { class: "lr-rail", "aria-hidden": "true", style: { top: `${g.railY - g.railR}px`, height: `${g.railR * 2}px` } },
      h("div", { class: "lr-rail-shadow", style: { top: `${g.railR * 2 + 2}px` } }), h("div", { class: "lr-rail-bar" }), h("div", { class: "lr-rail-knurl" }),
      S.size.carousel ? null : [0, 1].map((side) => h("div", { class: "lr-bracket", style: { [side ? "right" : "left"]: "6px" } }, h("span", { class: "t" }), h("span", { class: "b" }))));
    const slots = items.map((item, i) => {
      const tone = `lr-tone-${((item.tone ?? (i % 5) + 1) - 1) % 5 + 1}`;
      const strap = g.straps[i], reelTop = g.reelTops[i], clipTop = g.clipTops[i], cardOffset = g.cardTops[i] - clipTop;
      const px = (v) => `${v}px`;
      const cord = h("span", { class: "lr-cord", style: { left: px(W / 2 - 0.75), top: px(reelTop + g.reel * 0.82), height: px(g.cordRest) } });
      const strapEl = h("span", { class: "lr-strap-wrap", "aria-hidden": "true" },
        h("span", { class: "lr-strap-shadow", style: { left: px(W / 2 - g.strapW / 2 + 3 * g.u), top: px(g.pivotY + 3), width: px(g.strapW), height: px(strap) } }),
        h("span", { class: "lr-strap", style: { left: px(W / 2 - g.strapW / 2), top: px(g.pivotY - 2), width: px(g.strapW), height: px(strap + 2) } },
          h("span", { class: "lr-stitch" }), h("span", { class: "lr-strap-top", style: { height: px(7 * g.u) } }), h("span", { class: "lr-strap-seam", style: { top: px(9 * g.u) } })),
        h("span", { class: "lr-loop", style: { left: px(W / 2 - g.strapW * 0.75), top: px(g.pivotY - 4 * g.u), width: px(g.strapW * 1.5), height: px(8 * g.u) } }),
        h("span", { class: "lr-crimp", style: { left: px(W / 2 - g.strapW / 2 - 1.5), top: px(g.pivotY + strap - g.crimp * 0.4), width: px(g.strapW + 3), height: px(g.crimp) } }),
        h("span", { class: "lr-reel", style: { left: px(W / 2 - g.reel / 2), top: px(reelTop), width: px(g.reel), height: px(g.reel) } }, h("span", { class: "lr-reel-ring" }), h("span", { class: "lr-reel-hub" })),
        cord);
      const shadow = h("span", { class: "lr-shadow" });
      const flip = h("span", { class: "lr-flip", "data-flip": "", style: { transform: `perspective(${PERSPECTIVE}px) rotateY(${REST_Y[i % REST_Y.length]}deg)` } }, badgeFaces(item, tone));
      const btn = h("button", { type: "button", class: "lr-badge", "data-badge": i, "data-flipped": "false", tabindex: i === 0 ? "0" : "-1",
        "aria-label": `${item.name}, ${item.role}`, "aria-describedby": `${uid}-caption`, "aria-pressed": "false",
        style: { top: px(cardOffset), width: px(W), height: px(g.H), fontSize: px(base) },
        onfocus: () => { S.focusIndex = i; if (pointer.id < 0) { stop(); setActive(i); } },
        onclick: (e) => { const pending = pendingOpen; pendingOpen = -1; if (e.detail === 0 || pending === i) toggle(i); } }, flip);
      const clip = h("span", { class: "lr-clip", "aria-hidden": "true", style: { left: px(W / 2 - g.clipW / 2), width: px(g.clipW), height: px(g.clipH + 10 * g.u) } },
        h("span", { class: "lr-clip-tab", style: { top: px(g.clipH * 0.7), width: px(g.clipW * 0.42), height: px(cardOffset - g.clipH * 0.7 + 1.02 * base) } }),
        h("span", { class: "lr-clip-head", style: { height: px(g.clipH) } }), h("span", { class: "lr-clip-shine" }),
        h("span", { class: "lr-clip-hole", style: { top: px(g.clipH * 0.14), width: px(g.clipH * 0.34), height: px(g.clipH * 0.34) } }));
      const hang = h("span", { class: "lr-hang", style: { top: px(clipTop), width: px(W), height: px(cardOffset + g.H), transformOrigin: `${W / 2}px 0px` } },
        h("span", { class: "lr-shadow-wrap", "aria-hidden": "true", style: { top: px(cardOffset), width: px(W), height: px(g.H), filter: `blur(${Math.max(4, 8 * g.u).toFixed(1)}px)` } }, shadow),
        btn, clip);
      const swing = h("span", { class: "lr-swing", style: { transformOrigin: `${W / 2}px ${g.pivotY}px` } }, strapEl, hang);
      const slot = h("div", { class: `lr-slot ${tone}`, "data-lanyard": i, style: { width: px(W), height: px(g.height), zIndex: 10 + i } },
        h("span", { class: "lr-ring", "aria-hidden": "true", style: { left: px(W / 2 - 4.5 * g.u), top: px(g.railY - g.ring), width: px(9 * g.u), height: px(g.ring * 2),
          borderWidth: `${Math.max(1.6, 2.2 * g.u).toFixed(2)}px` } }), swing);
      R.slots[i] = slot; R.swings[i] = swing; R.straps[i] = strapEl; R.cords[i] = cord; R.hangs[i] = hang; R.buttons[i] = btn; R.flips[i] = flip; R.shadows[i] = shadow;
      return slot;
    });
    stage.replaceChildren(rail, ...slots, ...(S.size.carousel ? [h("div", { class: "lr-fade left", "aria-hidden": "true" }), h("div", { class: "lr-fade right", "aria-hidden": "true" })] : []));
    root.dataset.mode = S.size.carousel ? "carousel" : "rail";
    dots.replaceChildren(...(S.size.carousel && count > 1 ? items.map((item, i) => h("button", { type: "button", class: "lr-dot", "aria-label": `${labels.show} ${item.name}`,
      onclick: () => { stop(); setActive(i); } })) : []));
    sim.x.length = 0;      // new DOM: start from the layout positions
    sync();
  }

  function measure(width) {
    const railW = Math.min(MAX_W, (width - 40) / (count * RAIL_PITCH_MIN + 0.4));
    const carousel = railW < MIN_RAIL_W;
    const W = Math.round((carousel ? clamp(width * 0.3, 96, 118) : railW) * 4) / 4;
    const old = S.size;
    if (Math.abs(old.width - width) < 0.5 && old.carousel === carousel && old.W === W) return;
    const rebuild = !old.width || old.W !== W || old.carousel !== carousel;
    S.size = { width, W, carousel };
    if (rebuild) { S.geo = geometry(W, items); build(); } else targets(false);
    if (!swayed && !S.reduced) {
      swayed = true;
      items.forEach((_, i) => setTimeout(() => impulse(i, (i % 2 ? -1 : 1) * (30 - (i % 4) * 3)), 60 + i * 70));
    }
    play();
  }

  /* ------------------------------------------------------------------ input */
  function nearest(clientX, clientY) {
    const box = stage.getBoundingClientRect(), x = clientX - box.left, y = clientY - box.top, g = S.geo;
    if (y < g.railY - 12) return null;
    let best = null, distance = Infinity;
    for (let i = 0; i < count; i++) {
      if (y > g.cardTops[i] + g.H + Math.max(0, sim.st[i] ?? 0) + 8) continue;
      const d = Math.abs(x - (sim.x[i] ?? 0));
      if (d < g.W / 2 + 6 && d < distance) { best = i; distance = d; }
    }
    return best;
  }
  function feasible(d) {
    let [lo, hi] = stops(sim, S.geo.W, S.size.width, count);
    for (let k = 0; k < d; k++) lo += minGap(sim, S.geo.W, k, k + 1);
    for (let k = count - 1; k > d; k--) hi -= minGap(sim, S.geo.W, k - 1, k);
    return [lo, Math.max(lo, hi)];
  }
  function retarget() { targets(false); if (S.reduced) snap(); }

  stage.addEventListener("pointermove", (e) => {
    const p = pointer, s = sim, now = performance.now();
    if (p.id === e.pointerId) {
      const dx = e.clientX - p.x, dy = e.clientY - p.y;
      if (!p.mode && Math.hypot(dx, dy) > 8) {
        if (Math.abs(dy) > Math.abs(dx)) p.mode = dy > 0 && p.index >= 0 ? "pull" : "none";
        else p.mode = S.size.carousel ? "swipe" : p.index >= 0 && !S.reduced ? "drag" : "none";
        if (p.mode !== "none") { stop(); if (stage.isConnected) stage.setPointerCapture(e.pointerId); }
        if (p.mode === "pull") s.pull = p.index;
        if (p.mode === "drag") { s.drag = p.index; s.grab = e.clientX - stage.getBoundingClientRect().left - s.x[p.index]; }
      }
      const elapsed = Math.max(1, now - p.lastT);
      p.v = p.v * 0.6 + ((e.clientX - p.lastX) / elapsed) * 0.4;
      p.lastX = e.clientX; p.lastY = e.clientY; p.lastT = now;
      if (p.mode === "pull") {
        const i = p.index;
        s.st[i] = soft(Math.max(0, dy), S.geo.maxStretch); s.vst[i] = 0;
        const angle = clamp((-Math.atan2(dx, (S.geo.pendulum[i] ?? 200) + s.st[i]) * 180) / Math.PI, -16, 16);
        s.vsw[i] = ((angle - (s.sw[i] ?? 0)) / elapsed) * 1000 * 0.5; s.sw[i] = angle;
        if (S.reduced) paint(i); else kick();
      } else if (p.mode === "drag" && s.drag >= 0) {
        const [lo, hi] = feasible(s.drag);
        s.x[s.drag] = clamp(e.clientX - stage.getBoundingClientRect().left - s.grab, lo, hi);
        s.vx[s.drag] = p.v * 1000; s.free = now + 900; kick();
      } else if (p.mode === "swipe") { p.swipe = dx; retarget(); }
      return;
    }
    if (e.pointerType !== "mouse" || p.id >= 0) return;
    const hit = nearest(e.clientX, e.clientY), hoverV = (e.clientX - p.hoverX) / Math.max(1, now - p.hoverT);
    p.hoverX = e.clientX; p.hoverT = now;
    if (S.size.carousel) { const center = S.active ?? S.carouselIndex; if (hit !== null && hit === center && S.active !== hit) { stop(); setActive(hit); } return; }
    if (hit !== null && hit !== p.hoverHit) impulse(hit, clamp(-hoverV * 22, -24, 24));
    p.hoverHit = hit ?? -1;
    if (hit !== null && hit !== S.active) { stop(); setActive(hit); }
  });
  stage.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const hit = nearest(e.clientX, e.clientY), now = performance.now();
    pendingOpen = -1;
    Object.assign(pointer, { id: e.pointerId, index: hit ?? -1, x: e.clientX, y: e.clientY, mode: "", kind: e.pointerType, lastX: e.clientX, lastY: e.clientY, lastT: now, v: 0, swipe: 0 });
  });
  function finishPointer(e, cancelled) {
    const p = pointer, s = sim;
    if (p.id !== e.pointerId) return;
    if (stage.hasPointerCapture(e.pointerId)) stage.releasePointerCapture(e.pointerId);
    p.id = -1;
    if (p.mode === "pull") { const i = s.pull; s.pull = -1; if (S.reduced) { s.st[i] = 0; s.vst[i] = 0; s.sw[i] = 0; s.vsw[i] = 0; s.beta[i] = 0; paint(i); } else kick(); return; }
    if (p.mode === "drag") { s.drag = -1; s.free = performance.now() + 700; kick(); return; }
    if (p.mode === "swipe") {
      const dx = e.clientX - p.x, current = S.active ?? S.carouselIndex;
      const by = Math.abs(dx) > 40 || Math.abs(p.v) > 0.45 ? (dx < 0 ? 1 : -1) : 0;
      p.swipe = 0;
      const next = S.cyclic ? (((current + by) % count) + count) % count : clamp(current + by, 0, count - 1);
      if (next === S.active) retarget(); else setActive(next);
      return;
    }
    if (cancelled || p.mode || p.index < 0) return;
    stop();
    if ((p.kind !== "mouse" || S.size.carousel) && S.active !== p.index) setActive(p.index);
    else pendingOpen = p.index;
  }
  stage.addEventListener("pointerup", (e) => finishPointer(e, false));
  stage.addEventListener("pointercancel", (e) => finishPointer(e, true));
  stage.addEventListener("pointerleave", (e) => {
    pointer.hoverHit = -1;
    if (e.pointerType === "mouse" && pointer.id < 0 && !S.size.carousel && !document.activeElement?.matches("[data-badge]:focus-visible") && S.flipped === null) setActive(null);
  });
  stage.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { if (S.flipped !== null) { e.preventDefault(); setFlipped(null); } return; }
    const badge = e.target instanceof HTMLElement ? e.target.dataset.badge : undefined;
    if (e.key === "ArrowDown") { if (badge === undefined) return; e.preventDefault(); stop(); tug(Number(badge), 300); return; }
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
    e.preventDefault(); stop();
    const from = S.active ?? S.focusIndex;
    const next = e.key === "Home" ? 0 : e.key === "End" ? count - 1 : clamp(from + (e.key === "ArrowRight" ? 1 : -1), 0, count - 1);
    S.focusIndex = next; setActive(next); R.buttons[next]?.focus({ preventScroll: true });
  });
  const onDocKey = (e) => {
    if (e.key !== "Escape" || e.defaultPrevented || S.flipped === null) return;
    if (e.target instanceof Node && stage.contains(e.target)) return;
    setFlipped(null);
  };
  document.addEventListener("keydown", onDocKey);
  const media = matchMedia("(prefers-reduced-motion: reduce)");
  const onMotion = () => { S.reduced = media.matches; if (S.reduced) { stop(); kick(); } };
  media.addEventListener("change", onMotion);
  const observer = new ResizeObserver(([box]) => { if (box) measure(box.contentRect.width); });
  observer.observe(stage);

  return {
    el: root,
    select(i) { stop(); setActive(i); },
    flip(i) { toggle(i); },
    destroy() { observer.disconnect(); cancelAnimationFrame(sim.raf); clearTimeout(autoTimer); document.removeEventListener("keydown", onDocKey); media.removeEventListener("change", onMotion); },
  };
}
