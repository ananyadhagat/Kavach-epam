/* Voice notes: the recorder card (visual direction: the "Voice note" frame in the team's Figma file)
   and a small player. Recording is always optional. The microphone is used only between Record and
   Stop, and its tracks are released as soon as recording stops or the page changes.

   voiceRecorder({ title, hint, maxSeconds, submitText, onSubmit(blob, seconds) -> Promise, onSent? })
     returns { el, destroy, hasRecording() }. onSubmit does the upload; errors it throws are shown.
   audioNote(note, { fetchAuth }) shows one saved note with a play button. */

import { protectedImage } from "../api.js";
import { button, clear, h, icon, toast } from "../ui.js";

const BARS = 48;
const fmt = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const pickType = () => ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((t) => window.MediaRecorder?.isTypeSupported?.(t)) || "";

export function voiceRecorder({ title = "Voice note", hint = "", maxSeconds = 180, submitText = "Send voice note", onSubmit, onSent, autoSubmit = true } = {}) {
  let stream = null, rec = null, chunks = [], blob = null, url = null, started = 0, seconds = 0, tick = 0, raf = 0, ctx = null, analyser = null, sent = false;
  const ring = h("div", { class: "vn-ring", "aria-hidden": "true" }, Array.from({ length: BARS }, (_, i) => h("i", { style: { "--a": `${(360 / BARS) * i}deg` } })));
  const time = h("strong", { class: "vn-time", "aria-live": "off" }, "00:00");
  const state = h("span", { class: "vn-state" }, "Ready");
  const audio = h("audio", { class: "vn-audio", controls: true, preload: "metadata", hidden: true });
  const controls = h("div", { class: "vn-controls" });
  const msg = h("p", { class: "vn-msg", role: "status", "aria-live": "polite" });
  const el = h("section", { class: "vn glass", "aria-label": title },
    h("p", { class: "vn-title" }, title),
    h("div", { class: "vn-dial" }, ring, h("div", { class: "vn-center" }, time, state)),
    hint ? h("p", { class: "vn-hint" }, hint) : null,
    audio, controls, msg);

  const setState = (name, text) => { el.dataset.state = name; state.textContent = text; };
  const release = () => {
    cancelAnimationFrame(raf); raf = 0; clearInterval(tick);
    stream?.getTracks().forEach((t) => t.stop()); stream = null;
    ctx?.close?.().catch(() => {}); ctx = null; analyser = null;
    ring.querySelectorAll("i").forEach((b) => b.style.setProperty("--v", "0"));
  };
  const levels = () => {
    if (!analyser) return;
    const data = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(data);
    const bars = ring.children, lit = Math.round((seconds / maxSeconds) * BARS);
    for (let i = 0; i < BARS; i++) {
      const v = data[Math.floor((i / BARS) * data.length * 0.7)] / 255;
      bars[i].style.setProperty("--v", v.toFixed(2));
      bars[i].classList.toggle("lit", i < Math.max(lit, 1));
    }
    raf = requestAnimationFrame(levels);
  };

  function draw() {
    const s = el.dataset.state;
    clear(controls,
      s === "idle" || s === "error" ? button("Record", { class: "btn primary vn-rec", onclick: start }, "mic") : null,
      s === "recording" ? button("Stop", { class: "btn vn-stop", onclick: stop }, "x") : null,
      s === "recorded" ? [button("Delete", { class: "btn", onclick: discard }, "trash"), button("Record again", { class: "btn", onclick: () => { discard(); start(); } }, "refresh"),
        autoSubmit ? button(submitText, { class: "btn primary", onclick: submit }, "upload") : null] : null,
      s === "sending" ? h("span", { class: "spinner" }) : null,
      s === "sent" ? button("Record another", { class: "btn", onclick: () => { discard(); } }, "plus") : null);
  }
  async function start() {
    msg.textContent = "";
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { setState("error", "Not supported"); msg.textContent = "This browser can't record audio. You can still continue without a voice note."; draw(); return; }
    if (!window.isSecureContext) { setState("error", "Needs HTTPS"); msg.textContent = "Recording needs a secure (https) page."; draw(); return; }
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
    catch (e) { setState("error", "No microphone"); msg.textContent = e?.name === "NotAllowedError" ? "Microphone access was blocked. Allow it in the browser's site settings to record, or continue without a voice note." : "No microphone could be opened."; draw(); return; }
    const type = pickType();
    rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    chunks = [];
    rec.ondataavailable = (e) => { if (e.data?.size) chunks.push(e.data); };
    rec.onstop = () => {
      release();
      blob = new Blob(chunks, { type: (rec.mimeType || type || "audio/webm").split(";")[0] });
      if (blob.size < 200) { blob = null; setState("idle", "Too short"); msg.textContent = "Nothing was recorded. Try again."; draw(); return; }
      url = URL.createObjectURL(blob);
      audio.src = url; audio.hidden = false;
      setState("recorded", "Recorded"); draw();
    };
    try {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      analyser = ctx.createAnalyser(); analyser.fftSize = 256;
      ctx.createMediaStreamSource(stream).connect(analyser);
    } catch { analyser = null; }
    rec.start(250);
    started = performance.now(); seconds = 0; time.textContent = "00:00";
    tick = setInterval(() => {
      seconds = (performance.now() - started) / 1000;
      time.textContent = fmt(seconds);
      if (seconds >= maxSeconds) { stop(); toast(`Voice notes stop at ${maxSeconds / 60} minutes.`, "info"); }
    }, 200);
    setState("recording", "Recording"); draw(); levels();
  }
  function stop() { if (rec && rec.state !== "inactive") rec.stop(); seconds = (performance.now() - started) / 1000; }
  function discard() {
    if (url) URL.revokeObjectURL(url);
    url = null; blob = null; seconds = 0; sent = false;
    audio.removeAttribute("src"); audio.hidden = true; time.textContent = "00:00"; msg.textContent = "";
    ring.querySelectorAll("i").forEach((b) => b.classList.remove("lit"));
    setState("idle", "Ready"); draw();
  }
  async function submit() {
    if (!blob || !onSubmit) return;
    setState("sending", "Sending"); draw();
    try { await onSubmit(blob, Math.max(1, Math.round(seconds * 10) / 10)); sent = true; setState("sent", "Sent"); msg.textContent = "Voice note saved."; onSent?.(); }
    catch (e) { setState("recorded", "Not sent"); msg.textContent = e.message || "The voice note could not be sent."; }
    draw();
  }
  setState("idle", "Ready"); draw();
  return {
    el,
    hasRecording: () => !!blob && !sent,
    take: () => (blob && !sent ? { blob, seconds: Math.max(1, Math.round(seconds * 10) / 10) } : null),
    markSent: () => { sent = true; setState("sent", "Sent"); msg.textContent = "Voice note saved."; draw(); },
    destroy() { if (rec && rec.state !== "inactive") { rec.onstop = null; rec.stop(); } release(); if (url) URL.revokeObjectURL(url); },
  };
}

/* One saved voice note. Signed-in routes need the auth header, so the file is fetched as a blob first. */
export function audioNote(note, { auth = true, label: text } = {}) {
  // The ally's private link needs no sign-in header, so the browser can stream it directly.
  const audio = h("audio", { controls: true, preload: "none", class: "vn-audio", src: auth ? null : note.url });
  const load = button("Play voice note", { class: "btn small", onclick: async () => {
    try { audio.src = auth ? await protectedImage(note.url) : note.url; load.replaceWith(audio); audio.play().catch(() => {}); }
    catch (e) { toast(e.message || "The voice note could not be loaded.", "fail"); }
  } }, "mic");
  return h("div", { class: "vn-note" }, icon("mic", 16), h("span", { class: "grow" }, text || "Voice note", note.duration_s ? ` · ${fmt(note.duration_s)}` : ""), auth ? load : audio);
}
