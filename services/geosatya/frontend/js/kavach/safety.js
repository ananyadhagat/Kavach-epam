/* KAVACH Women's Safety: Trusted Allies and SOS.

Honesty rules in this file:
- The location sent is the phone's real GPS (locate / watchPosition). Simulated GPS is never used here.
- If GPS is blocked or unavailable the screen says so, and offers retry or a hand-placed point that is labelled "not GPS".
- Delivery to allies is shown as "not sent by KAVACH" because no SMS / WhatsApp provider is connected. The user sends
  each ally's private link with their own phone (WhatsApp, SMS or the share sheet) using the buttons below.
- Location updates only run while this screen is open and the SOS is active; they stop at once when it ends. */

import { api, session, upload } from "../api.js";
import { audioNote, voiceRecorder } from "./voice.js";
import { LOCATION_BLOCKED_HELP, locate } from "../capture.js";
import { createMap } from "../maps.js";
import { banner, button, card, chip, clear, emptyState, fmtAgo, fmtTime, h, icon, pageHead, toast } from "../ui.js";
import { initials } from "./brand.js";
import { safetyIllustration } from "./illustrations.js";

const CALLS = [{ number: "100", label: "Police" }, { number: "108", label: "Ambulance" }, { number: "112", label: "Emergency helpline" }];
const DISCLAIMER = "KAVACH does not replace the police, ambulance or emergency services. In danger, call 112 first.";
const elapsed = (iso) => { const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000)); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };
const linkFor = (path) => `${location.origin}${location.pathname}${path}`;
const digitsOf = (phone) => phone.replace(/[^\d]/g, "");

export function callButtons(compact = false) {
  return h("div", { class: `callrow${compact ? " compact" : ""}` }, CALLS.map((c) =>
    h("a", { class: "callbtn", href: `tel:${c.number}`, "aria-label": `Call ${c.label} on ${c.number}` }, icon("phone", compact ? 18 : 22),
      h("span", {}, h("strong", {}, c.number), h("small", {}, c.label)))));
}

/* A press-and-hold button. A short tap only explains how it works, so a pocket touch cannot trigger it. */
function sosButton(onTrigger) {
  let timer = null, fired = false;
  const btn = h("button", { class: "sos-btn", type: "button", "aria-label": "SOS emergency button. Press and hold for one second, or press Enter, to start an alert with a 5 second cancel countdown." },
    h("span", { class: "sos-fill", "aria-hidden": "true" }), h("span", { class: "sos-label" }, "SOS"), h("span", { class: "sos-hint" }, "Press and hold"));
  const stop = () => { clearTimeout(timer); btn.classList.remove("holding"); };
  btn.addEventListener("pointerdown", (e) => { e.preventDefault(); fired = false; btn.classList.add("holding");
    timer = setTimeout(() => { fired = true; stop(); navigator.vibrate?.(80); onTrigger("LONG_PRESS"); }, 1000); });
  for (const ev of ["pointerup", "pointerleave", "pointercancel"]) btn.addEventListener(ev, stop);
  btn.addEventListener("contextmenu", (e) => e.preventDefault());
  btn.addEventListener("click", () => { if (!fired) toast("Press and hold the SOS button for one second.", "info"); fired = false; });
  btn.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onTrigger("BUTTON"); } });
  return btn;
}

/* A short countdown that lets the user cancel an accidental trigger. */
function countdown(seconds = 5) {
  return new Promise((resolve) => {
    let left = seconds;
    const num = h("div", { class: "cd-num", "aria-live": "assertive" }, String(left));
    const dlg = h("dialog", { class: "dialog cd-dialog", "aria-label": "SOS starting" },
      h("div", { class: "stack", style: { alignItems: "center", textAlign: "center", gap: "14px" } },
        h("h2", {}, "Starting SOS"), num, h("p", { class: "muted", style: { margin: 0 } }, "Your trusted allies will get your name, the time and your live location."),
        h("div", { class: "cd-actions" },
          h("button", { class: "btn big block", type: "button", onclick: () => done(false) }, "Cancel, I'm fine"),
          h("button", { class: "btn sos big block", type: "button", onclick: () => done(true) }, "Send now"))));
    let tick = setInterval(() => { left -= 1; num.textContent = String(Math.max(left, 0)); if (left <= 0) done(true); }, 1000);
    const done = (go) => { clearInterval(tick); dlg.close(); dlg.remove(); resolve(go); };
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); done(false); });
    document.body.append(dlg);
    dlg.showModal();
    dlg.querySelector("button").focus();
  });
}

/* ----------------------------------------------------------- the user's page */
export async function renderSafety(ctx) {
  const { main, onCleanup, rerender } = ctx;
  let data = await api("/women/overview");
  const stoppers = [];
  onCleanup(() => stoppers.forEach((fn) => { try { fn(); } catch { /* ignore */ } }));
  const reload = async () => { stoppers.splice(0).forEach((fn) => { try { fn(); } catch { /* ignore */ } }); data = await api("/women/overview"); draw(); };

  const begin = async (method) => {
    if (!(await countdown(5))) { toast("SOS cancelled before it started.", "info"); return; }
    try {
      // The SOS is created at once (the trigger time is recorded now); the phone's GPS follows as soon as it has a fix.
      let sos = await api("/women/sos", { method: "POST", json: { method, device_location: null, device_location_error: "NOT_REQUESTED" } });
      data.active = sos;
      draw();
      const fix = await locate({ timeout: 12000 });
      if (fix.status === "ok") sos = await sendFix(sos.sos_id, fix);
      else { sos = { ...sos, client_error: fix.message, client_error_code: fix.code }; toast(fix.message, "fail"); }
      data.active = sos; draw();
    } catch (e) { toast(e.message, "fail"); }
  };

  const sendFix = (id, fix) => api(`/women/sos/${id}/location`, { method: "POST", json: { device_location: {
    latitude: fix.latitude, longitude: fix.longitude, accuracy_m: fix.accuracy_m, observed_at: fix.observed_at, mode: "LIVE" } } });

  /* --- active SOS panel --- */
  function activePanel(sos) {
    let current = sos, watchId = null, lastSent = 0, pending = null, wake = null, manualMode = false, manualPoint = null, mapObj = null;
    const clock = h("strong", { class: "sos-clock" }, elapsed(sos.triggered_at));
    const statusLine = h("div", { class: "sos-loc" });
    const sharing = h("div", { class: "stack" });
    const mapEl = h("div", { class: "map", style: { height: "300px", borderRadius: "16px" }, role: "img", "aria-label": "Map showing your shared location" });
    const manualBar = h("div", { class: "row wrap" });
    const status = () => {
      const l = current.location, live = current.location_status === "SHARING";
      clear(statusLine, h("span", { class: `dot ${live ? (l?.stale ? "stale" : "live") : "offline"}` }, live ? (l?.stale ? "Location is getting old" : "Location shared live") : current.location_status === "MANUAL" ? "Hand-placed point" : "No location shared yet"),
        h("p", { class: "muted", style: { margin: "6px 0 0" } }, current.location_status === "SHARING" || current.location_status === "MANUAL" || !current.client_error
          ? current.location_text : `No location is being shared yet. ${current.client_error}`),
        l ? h("p", { class: "hint", style: { margin: "4px 0 0" } }, `Updated ${fmtAgo(l.received_at)}${l.accuracy_m != null ? ` · GPS ±${Math.round(l.accuracy_m)} m` : ""}${l.mode === "MANUAL" ? " · not GPS" : ""}`) : null);
      const blocked = current.location_error === "PERMISSION_DENIED" || current.client_error_code === "PERMISSION_DENIED";
      clear(manualBar, current.location_status !== "SHARING" ? [button("Retry GPS", { class: "btn", onclick: retryGps }, "refresh"),
        button(manualMode ? "Cancel placing a point" : "Share a point on the map", { class: "btn", onclick: () => { manualMode = !manualMode; manualPoint = null; status(); } }, "pin")] : null,
        manualMode ? h("span", { class: "hint" }, "Tap the map where you are, then confirm.") : null,
        manualMode && manualPoint ? button("Share this point", { class: "btn primary", onclick: shareManual }, "check") : null,
        blocked ? h("div", { class: "banner review", style: { width: "100%" } }, icon("warn", 18), h("div", {}, LOCATION_BLOCKED_HELP)) : null);
    };
    const drawMap = () => {
      const l = current.location;
      if (!mapObj) return;
      mapObj.remove("me"); mapObj.remove("acc");
      if (manualPoint) mapObj.marker("pt", "pin", manualPoint, "Point to share"); else mapObj.remove("pt");
      if (l) {
        mapObj.marker("me", l.mode === "MANUAL" ? "pin" : "me", [l.latitude, l.longitude], "Shared location");
        if (l.accuracy_m) mapObj.circle("acc", [l.latitude, l.longitude], l.accuracy_m, "me");
        if (!drawMap.fitted) { mapObj.setView([l.latitude, l.longitude], 17); drawMap.fitted = true; }
      }
    };
    const apply = (next) => { current = { ...current, ...next }; status(); drawAllies(); drawMap(); if (next.audio_notes) drawNotes(); };
    const retryGps = async () => {
      const fix = await locate({ timeout: 12000 });
      if (fix.status !== "ok") { apply({ client_error: fix.message, client_error_code: fix.code }); return; }
      try { apply({ ...(await sendFix(current.sos_id, fix)), client_error: null, client_error_code: null }); toast("Location is now shared", "pass"); } catch (e) { toast(e.message, "fail"); }
    };
    const shareManual = async () => {
      try { apply({ ...(await api(`/women/sos/${current.sos_id}/manual-location`, { method: "POST", json: { latitude: manualPoint[0], longitude: manualPoint[1] } })), client_error: null }); manualMode = false; manualPoint = null; status(); toast("Sharing the point you placed (not GPS)", "info"); }
      catch (e) { toast(e.message, "fail"); }
    };

    const message = (a) => `SOS from ${session.me.display_name.replace(/\s*\(.*\)/, "")}: I need help. Follow my live location here: ${linkFor(a.share_path)}`;
    const drawAllies = () => clear(sharing,
      current.no_allies ? banner("review", "You have no trusted allies, so nobody has a link to follow you. Call 112 now, and add allies below for next time.") : [
        banner("info", h("span", {}, h("strong", {}, "KAVACH has not sent these. "), "SMS and WhatsApp are not connected yet. Tap a button to send each link from your own phone.")),
        ...current.allies.map((a) => h("div", { class: "ally-send" }, h("div", { class: "stack tight", style: { minWidth: 0 } },
          h("strong", {}, a.name), h("span", { class: "muted" }, a.relationship_label),
          h("span", { class: "chip review" }, "Not sent by KAVACH"),
          a.opened_at ? h("span", { class: "hint" }, `They opened the link ${fmtAgo(a.opened_at)}`) : null),
          a.share_path ? h("div", { class: "row wrap", style: { gap: "8px" } },
            h("a", { class: "btn small primary", href: `https://wa.me/${a.phone.startsWith("+") ? digitsOf(a.phone) : ""}?text=${encodeURIComponent(message(a))}`, target: "_blank", rel: "noopener" }, icon("share", 16), "WhatsApp"),
            h("a", { class: "btn small", href: `sms:${a.phone}?&body=${encodeURIComponent(message(a))}` }, icon("phone", 16), "SMS"),
            navigator.share ? button("Share…", { class: "btn small", onclick: () => navigator.share({ title: "SOS", text: message(a) }).catch(() => {}) }, "share") : null,
            button("Copy link", { class: "btn small", onclick: async () => { try { await navigator.clipboard.writeText(linkFor(a.share_path)); toast("Link copied", "pass"); } catch { toast(linkFor(a.share_path), "info"); } } }, "copy")) : null))]);

    // Optional voice note: what is happening, where, who is with you. Allies can play it from their link.
    const notesBox = h("div", { class: "stack tight" });
    const drawNotes = () => clear(notesBox, (current.audio_notes || []).map((n, i) => audioNote(n, { label: `Voice note ${i + 1} · sent ${fmtTime(n.received_at)}` })));
    const voiceCard = () => {
      const rec = voiceRecorder({ title: "Voice note · optional", submitText: "Send to my allies", maxSeconds: 120,
        hint: "Say what is happening and where you are. Your allies can play it from their link while the SOS is on.",
        onSubmit: async (blob, seconds) => {
          const fd = new FormData();
          fd.append("audio", blob, blob.type.includes("mp4") ? "sos.m4a" : "sos.webm");
          fd.append("duration_s", String(seconds));
          const r = await upload(`/women/sos/${current.sos_id}/audio-notes`, fd);
          current = { ...current, audio_notes: r.notes }; drawNotes();
        } });
      stoppers.push(rec.destroy);
      drawNotes();
      return card({ class: "card sos-voice" }, rec.el, notesBox);
    };

    const end = async (kind) => {
      const ok = kind === "resolve" ? confirm("End the SOS? Your allies will be told you are safe and location sharing stops.")
        : confirm("Cancel this SOS as a false alarm? Your allies will be told it was cancelled and location sharing stops.");
      if (!ok) return;
      try { await api(`/women/sos/${current.sos_id}/${kind === "resolve" ? "resolve" : "cancel"}`, { method: "POST" }); toast(kind === "resolve" ? "SOS ended. Stay safe." : "SOS cancelled.", "pass"); await reload(); }
      catch (e) { toast(e.message, "fail"); }
    };

    // While the SOS is active (and only then) follow the phone's GPS and keep the server's copy fresh.
    const follow = () => {
      if (!navigator.geolocation || !window.isSecureContext) return;
      watchId = navigator.geolocation.watchPosition((p) => { pending = { latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy_m: p.coords.accuracy, observed_at: new Date(p.timestamp).toISOString() }; },
        () => {}, { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 });
      navigator.wakeLock?.request("screen").then((w) => { wake = w; }).catch(() => {});
    };
    const timer = setInterval(async () => {
      clock.textContent = elapsed(current.triggered_at);
      if (pending && Date.now() - lastSent > 10000) {
        const fix = pending; pending = null; lastSent = Date.now();
        try { const r = await api(`/women/sos/${current.sos_id}/location`, { method: "POST", json: { device_location: { ...fix, mode: "LIVE" } } }); apply({ ...r, client_error: null, client_error_code: null }); } catch (e) { if (e.code === "SOS_ENDED") reload(); }
      }
    }, 1000);
    const poll = setInterval(async () => { try { const r = await api(`/women/sos/${current.sos_id}`); if (r.status !== "ACTIVE") reload(); else apply(r); } catch { /* keep trying */ } }, 15000);
    stoppers.push(() => { clearInterval(timer); clearInterval(poll); if (watchId != null) navigator.geolocation.clearWatch(watchId); wake?.release?.().catch(() => {}); mapObj?.destroy(); });
    follow();

    const panel = h("section", { class: "sos-active" },
      h("div", { class: "sos-banner", role: "alert" }, h("span", { class: "sos-pulse", "aria-hidden": "true" }), h("div", { class: "stack tight" },
        h("strong", {}, "SOS is active"), h("span", {}, `Started ${fmtTime(sos.triggered_at)} · running `, clock))),
      card({}, h("h2", {}, "Call for help"), callButtons(), h("p", { class: "hint", style: { margin: 0 } }, DISCLAIMER + " Calling opens your phone's dialer; nothing is dialled until you press call.")),
      card({}, h("h2", {}, "Your location"), statusLine, manualBar, mapEl,
        h("p", { class: "hint", style: { margin: 0 } }, "Keep this screen open: location updates pause if the phone locks or you leave this page.")),
      voiceCard(),
      card({}, h("h2", {}, "Send the link to your trusted allies"), sharing),
      card({}, h("h2", {}, "Finished?"), h("div", { class: "row wrap" },
        button("I'm safe: end SOS", { class: "btn green big", onclick: () => end("resolve") }, "check"),
        button("Cancel (false alarm)", { class: "btn big", onclick: () => end("cancel") }, "x"))));
    status(); drawAllies();
    setTimeout(async () => {
      mapObj = await createMap(mapEl, { center: current.location ? [current.location.latitude, current.location.longitude] : [23.2599, 77.4126], zoom: current.location ? 17 : 5,
        onClick: (ll) => { if (manualMode) { manualPoint = ll; drawMap(); status(); } } });
      drawMap();
    });
    return panel;
  }

  /* --- trusted allies --- */
  function alliesCard() {
    const name = h("input", { type: "text", id: "al-name", required: true, minlength: 2, maxlength: 80, autocomplete: "off" });
    const phone = h("input", { type: "tel", id: "al-phone", required: true, minlength: 7, maxlength: 24, inputmode: "tel", placeholder: "+91 98765 43210" });
    const rel = h("select", { id: "al-rel" }, data.relationships.map((r) => h("option", { value: r.id }, r.label)));
    const consent = h("input", { type: "checkbox", id: "al-consent" });
    const err = h("p", { class: "field-error", "aria-live": "polite" });
    const full = data.allies.length >= data.max_allies;
    const add = h("form", { class: "stack", onsubmit: async (e) => {
      e.preventDefault(); err.textContent = "";
      if (!consent.checked) { err.textContent = "Please tick the box to confirm you agree."; return; }
      try { await api("/women/allies", { method: "POST", json: { name: name.value, phone: phone.value, relationship: rel.value, consent: true } }); toast("Trusted ally added", "pass"); await reload(); }
      catch (ex) { err.textContent = ex.message; }
    } }, h("div", { class: "form-grid" }, h("label", { class: "field", for: "al-name" }, "Name", name), h("label", { class: "field", for: "al-phone" }, "Phone number", phone),
      h("label", { class: "field full", for: "al-rel" }, "Relationship", rel)),
    h("label", { class: "consent" }, consent, h("span", {}, "I agree that KAVACH may share my name and my live location with this person when I press SOS. I can remove them at any time.")),
    err, h("div", {}, h("button", { class: "btn primary", type: "submit" }, icon("plus", 16), "Add trusted ally")));

    const edit = (a) => {
      const n = h("input", { type: "text", value: a.name, minlength: 2, maxlength: 80, id: "ed-name" }), p = h("input", { type: "tel", value: a.phone, id: "ed-phone" });
      const r = h("select", { id: "ed-rel" }, data.relationships.map((x) => h("option", { value: x.id, selected: x.id === a.relationship }, x.label)));
      const e2 = h("p", { class: "field-error" });
      const dlg = h("dialog", { class: "dialog" }, h("form", { class: "stack", onsubmit: async (ev) => {
        ev.preventDefault();
        try { await api(`/women/allies/${a.ally_id}`, { method: "PATCH", json: { name: n.value, phone: p.value, relationship: r.value } }); dlg.close(); dlg.remove(); toast("Updated", "pass"); await reload(); }
        catch (ex) { e2.textContent = ex.message; }
      } }, h("h2", {}, "Edit trusted ally"), h("label", { class: "field", for: "ed-name" }, "Name", n), h("label", { class: "field", for: "ed-phone" }, "Phone number", p),
      h("label", { class: "field", for: "ed-rel" }, "Relationship", r), e2,
      h("div", { class: "row end" }, button("Cancel", { onclick: () => { dlg.close(); dlg.remove(); } }), h("button", { class: "btn primary", type: "submit" }, "Save"))));
      document.body.append(dlg); dlg.showModal();
    };
    const remove = async (a) => {
      if (!confirm(`Remove ${a.name}? They will no longer receive your SOS links, and their number is deleted from KAVACH.`)) return;
      try { await api(`/women/allies/${a.ally_id}`, { method: "DELETE" }); toast("Removed", "pass"); await reload(); } catch (e) { toast(e.message, "fail"); }
    };
    return card({}, h("div", { class: "row between wrap" }, h("h2", {}, "Your trusted allies"), h("span", { class: "muted" }, `${data.allies.length} of ${data.max_allies}`)),
      h("p", { class: "muted", style: { margin: 0 } }, data.who_gets_it), h("p", { class: "hint", style: { margin: 0 } }, icon("lock", 14), " Only you can see this list. It is never shown on public pages."),
      data.allies.length ? h("div", { class: "allylist" }, data.allies.map((a) => h("div", { class: "ally-row" }, h("span", { class: "mini-av" }, initials(a.name)),
        h("div", { class: "stack tight", style: { minWidth: 0 } }, h("strong", {}, a.name), h("span", { class: "muted" }, `${a.relationship_label} · ${a.phone}`),
          h("span", { class: "hint" }, `Agreed ${fmtAgo(a.consent_at)}`)),
        h("div", { class: "row", style: { gap: "6px" } }, button("Edit", { class: "btn small", onclick: () => edit(a) }), button("Remove", { class: "btn small danger", onclick: () => remove(a) })))))
        : banner("review", "You have no trusted allies yet. Add at least one so they can follow you if you press SOS."),
      full ? banner("info", `You have reached the limit of ${data.max_allies} allies. Remove one to add another.`) : h("details", { open: data.allies.length === 0 }, h("summary", {}, "Add a trusted ally"), h("div", { style: { marginTop: "12px" } }, add)));
  }

  function draw() {
    stoppers.splice(0).forEach((fn) => { try { fn(); } catch { /* ignore */ } });   // never leave a second GPS watch or timer running
    const sos = data.active;
    clear(main,
      pageHead({ title: "Women's Safety", subtitle: "Trusted allies and SOS. Private to you." }),
      sos ? activePanel(sos) : card({ class: "card sos-card" },
        h("div", { class: "stack", style: { alignItems: "center", textAlign: "center", gap: "14px" } },
          sosButton(begin), h("h2", {}, "In danger? Hold the button."),
          h("p", { class: "muted", style: { margin: 0, maxWidth: "440px" } }, data.allies.length
            ? `You get 5 seconds to cancel. Then ${data.allies.length} trusted ${data.allies.length === 1 ? "ally gets" : "allies get"} your name, the time and your live location link.`
            : "You have no trusted allies yet. Add one below so someone can follow you. An SOS still records the time and your location."),
          h("p", { class: "hint", style: { margin: 0 } }, "It will ask for your phone's location. Allow it so your allies can see where you are."))),
      card({}, h("h2", {}, "Emergency calls"), callButtons(), h("p", { class: "hint", style: { margin: 0 } }, DISCLAIMER + " These open your phone's dialer; nothing is dialled until you press call.")),
      alliesCard(),
      card({}, h("h2", {}, "SOS history"), data.history.length ? h("div", { class: "items" }, data.history.map((x) => h("div", { class: "hist-row" },
        h("div", { class: "stack tight" }, h("strong", {}, fmtTime(x.triggered_at)), h("span", { class: "muted" }, x.ended_at ? `Ended ${fmtTime(x.ended_at)} · ${x.updates} location update${x.updates === 1 ? "" : "s"}` : "Still active")),
        chip(x.status === "RESOLVED" ? "PASS" : x.status === "ACTIVE" ? "FAIL" : "", x.status_text))))
        : emptyState("No SOS history yet", "If you ever press SOS, it is recorded here, privately.")));
  }
  draw();
  void rerender;
}

/* ------------------------------------------------------------- public info */
export async function renderWomenInfo({ main }) {
  const citizen = session.me?.role === "CITIZEN";
  clear(main,
    h("section", { class: "hhero" }, h("div", { class: "hwrap hhero-grid" },
      h("div", { class: "hhero-copy" }, h("span", { class: "hpill" }, h("i", {}), "KAVACH Women's Safety"),
        h("h1", {}, "Your trusted allies,", h("br"), h("span", {}, "one press away.")),
        h("p", { class: "hlead" }, "Add the people you trust. If you ever need help, press SOS and they get a private link that follows your live location."),
        h("div", { class: "hhero-actions" }, h("a", { class: "hbtn primary big", href: citizen ? "#/safety" : "#/enter" }, citizen ? "Open Women's Safety" : "Sign in to set it up", icon("arrowRight", 18)),
          h("a", { class: "hbtn big", href: "tel:112" }, icon("phone", 18), "Call 112"))),
      h("div", { class: "hhero-art" }, safetyIllustration()))),
    h("section", { class: "hsec" }, h("div", { class: "hwrap" },
      h("div", { class: "hhead" }, h("span", { class: "heyebrow" }, "How it works"), h("h2", {}, "Simple, private and under your control")),
      h("ol", { class: "hsteps" },
        h("li", { class: "hstep" }, h("span", { class: "hicon" }, icon("heart", 24)), h("h3", {}, "Add allies"), h("p", {}, "Parents, siblings, a partner or friends, each added with your consent.")),
        h("li", { class: "hstep" }, h("span", { class: "hicon" }, icon("siren", 24)), h("h3", {}, "Hold SOS"), h("p", {}, "Press and hold. You get 5 seconds to cancel an accidental press.")),
        h("li", { class: "hstep" }, h("span", { class: "hicon" }, icon("pin", 24)), h("h3", {}, "Share location"), h("p", {}, "Your phone's real GPS is shared with your allies while the SOS is active.")),
        h("li", { class: "hstep" }, h("span", { class: "hicon" }, icon("check", 24)), h("h3", {}, "Stay safe"), h("p", {}, "End it when you are safe. Sharing stops immediately, and your allies are told."))),
      h("div", { class: "hgrid three", style: { marginTop: "24px" } },
        h("div", { class: "hcard" }, h("span", { class: "hicon" }, icon("lock", 24)), h("h3", {}, "Private"), h("p", {}, "Your allies and SOS history are visible only to you. They never appear on public pages or to staff.")),
        h("div", { class: "hcard" }, h("span", { class: "hicon" }, icon("eye", 24)), h("h3", {}, "No background tracking"), h("p", {}, "Location is only shared after you press SOS, and only while the SOS screen is open.")),
        h("div", { class: "hcard" }, h("span", { class: "hicon" }, icon("warn", 24)), h("h3", {}, "Honest about delivery"), h("p", {}, "SMS and WhatsApp are not connected yet, so you send each ally's link from your own phone."))),
      h("div", { style: { marginTop: "28px" } }, callButtons(), h("p", { class: "hnote" }, DISCLAIMER)))));
}

/* --------------------------------------------- the page a trusted ally opens */
export async function renderAllyView({ main, params, onCleanup }) {
  const token = params[0];
  const mapEl = h("div", { class: "map", style: { height: "min(52vh, 420px)", borderRadius: "18px" }, role: "img", "aria-label": "Map showing the person's shared location" });
  const head = h("div", { class: "ally-head" });
  const info = h("div", { class: "stack", style: { gap: "10px" } });
  let map = null, timer = null, fitted = false, notesKey = "";
  // Voice notes get their own box, redrawn only when the list changes (a playing note is never cut off by the 8 s refresh).
  const allyNotes = h("div", { class: "stack tight" });
  const drawAllyNotes = (d) => {
    const notes = d.status === "ACTIVE" ? d.audio_notes || [] : [];
    const key = notes.map((n) => n.note_id).join(",");
    if (key === notesKey) return;
    notesKey = key;
    clear(allyNotes, notes.length ? [h("strong", {}, "Voice notes from them"),
      notes.map((n, i) => audioNote(n, { auth: false, label: `Voice note ${i + 1} · ${fmtTime(n.received_at)}` }))] : null);
  };

  const draw = (d) => {
    const active = d.status === "ACTIVE", l = d.location;
    head.className = `ally-head ${active ? "alert" : "ended"}`;
    clear(head, h("span", { class: active ? "sos-pulse" : "ally-ok", "aria-hidden": "true" }), h("div", { class: "stack tight" },
      h("strong", { style: { fontSize: "20px" } }, active ? `${d.person} needs help` : `${d.person}'s alert has ended`),
      h("span", {}, active ? `Alert started ${fmtTime(d.triggered_at)}` : d.status_text)));
    clear(info,
      active ? h("div", { class: "stack tight" }, h("span", { class: `dot ${l ? (l.stale ? "stale" : "live") : "offline"}` }, l ? (l.mode === "MANUAL" ? "Point placed by hand (not GPS)" : l.stale ? "Location is getting old" : "Live location") : "No location yet"),
        h("p", { class: "muted", style: { margin: 0 } }, l ? `Last updated ${fmtAgo(l.received_at)}${l.accuracy_m != null ? ` · GPS ±${Math.round(l.accuracy_m)} m` : ""}${l.mode === "MANUAL" ? " · a point they placed by hand, not GPS" : ""}` : d.location_note))
        : banner("info", d.location_note),
      l ? h("div", { class: "row wrap" },
        h("a", { class: "btn primary", href: `https://www.google.com/maps?q=${l.latitude},${l.longitude}`, target: "_blank", rel: "noopener" }, icon("navigate", 17), "Open in Google Maps"),
        h("a", { class: "btn", href: `https://www.openstreetmap.org/?mlat=${l.latitude}&mlon=${l.longitude}#map=18/${l.latitude}/${l.longitude}`, target: "_blank", rel: "noopener" }, "OpenStreetMap")) : null,
      allyNotes,
      active ? h("div", { class: "stack" }, h("strong", {}, "What you can do"), callButtons(), h("p", { class: "hint", style: { margin: 0 } }, d.disclaimer)) : null);
    drawAllyNotes(d);
    mapEl.hidden = !active;
    if (map) {
      map.remove("p");
      if (active && l) { map.marker("p", l.mode === "MANUAL" ? "pin" : "me", [l.latitude, l.longitude], d.person); if (l.accuracy_m) map.circle("a", [l.latitude, l.longitude], l.accuracy_m, "me");
        if (!fitted) { map.setView([l.latitude, l.longitude], 17); fitted = true; } else map.setView([l.latitude, l.longitude]); }
    }
    if (!active) clearInterval(timer);
  };
  const load = async () => {
    try { draw(await api(`/women/share/${encodeURIComponent(token)}`)); }
    catch (e) { clearInterval(timer); clear(head); clear(info, banner("fail", e.status === 404 ? "This link is not valid or has expired." : e.message)); mapEl.hidden = true; }
  };
  clear(main, h("div", { class: "hwrap ally-page" }, h("div", { class: "stack", style: { gap: "16px", padding: "20px 0 48px" } },
    h("span", { class: "heyebrow" }, "KAVACH · Trusted ally alert"), head, mapEl, info,
    h("p", { class: "hint" }, "You are seeing this because someone chose you as a trusted ally. This page shows nothing else about them."))));
  await load();
  map = await createMap(mapEl, { center: [23.2599, 77.4126], zoom: 5 });
  onCleanup(() => { clearInterval(timer); map?.destroy(); });
  await load();
  timer = setInterval(load, 8000);
}
