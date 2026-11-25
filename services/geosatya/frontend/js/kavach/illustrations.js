/* Simple, calm illustrations in KAVACH's navy and green. Built as inline SVG so they stay crisp at every size
   and never need an image download. All are decorative (aria-hidden); the surrounding text carries the meaning. */

const NS = "http://www.w3.org/2000/svg";

function svg(markup, viewBox, extra = "") {
  const wrap = document.createElement("div");
  wrap.innerHTML = `<svg xmlns="${NS}" viewBox="${viewBox}" ${extra} aria-hidden="true" focusable="false">${markup}</svg>`;
  return wrap.firstElementChild;
}

/* A phone showing a map, a worker pin and a verified check, in front of a city skyline. */
export function heroIllustration() {
  return svg(`
    <defs>
      <linearGradient id="hi-sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#EAF1FB"/><stop offset="1" stop-color="#F7FAFD"/></linearGradient>
      <linearGradient id="hi-navy" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1B4DA1"/><stop offset="1" stop-color="#0F2A57"/></linearGradient>
      <linearGradient id="hi-green" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7DBE31"/><stop offset="1" stop-color="#2E9E4F"/></linearGradient>
      <filter id="hi-shadow" x="-20%" y="-10%" width="140%" height="130%"><feDropShadow dx="0" dy="14" stdDeviation="14" flood-color="#0F2A57" flood-opacity=".18"/></filter>
    </defs>
    <rect x="12" y="20" width="576" height="460" rx="36" fill="url(#hi-sky)"/>
    <circle cx="470" cy="110" r="46" fill="#fff" opacity=".9"/>
    <g fill="#D8E3F3"><rect x="40" y="300" width="56" height="150"/><rect x="104" y="260" width="44" height="190"/><rect x="156" y="330" width="62" height="120"/>
      <rect x="440" y="270" width="52" height="180"/><rect x="500" y="320" width="64" height="130"/></g>
    <g fill="#B9CCE6"><rect x="52" y="316" width="10" height="10"/><rect x="72" y="316" width="10" height="10"/><rect x="52" y="340" width="10" height="10"/><rect x="72" y="340" width="10" height="10"/>
      <rect x="114" y="278" width="9" height="9"/><rect x="130" y="278" width="9" height="9"/><rect x="114" y="302" width="9" height="9"/><rect x="130" y="302" width="9" height="9"/>
      <rect x="452" y="288" width="10" height="10"/><rect x="472" y="288" width="10" height="10"/><rect x="452" y="312" width="10" height="10"/><rect x="472" y="312" width="10" height="10"/></g>
    <path d="M12 450h576v6a24 24 0 0 1-24 24H36a24 24 0 0 1-24-24z" fill="#DCE7F5"/>
    <g transform="translate(556 372)"><rect x="-3" y="0" width="6" height="78" fill="#7DBE31"/><circle cx="0" cy="-8" r="22" fill="#7DBE31"/><circle cx="-14" cy="6" r="14" fill="#2E9E4F"/><circle cx="15" cy="8" r="13" fill="#2E9E4F"/></g>
    <g filter="url(#hi-shadow)">
      <rect x="190" y="48" width="220" height="410" rx="34" fill="#0F2A57"/>
      <rect x="202" y="62" width="196" height="382" rx="24" fill="#fff"/>
      <rect x="262" y="70" width="76" height="8" rx="4" fill="#0F2A57" opacity=".12"/>
      <rect x="202" y="86" width="196" height="196" fill="#EEF3F9"/>
      <path d="M202 200 C 250 170, 270 230, 330 190 S 380 150, 398 160" fill="none" stroke="#fff" stroke-width="14"/>
      <path d="M232 86 L 262 282 M330 86 L 300 282" stroke="#fff" stroke-width="10" fill="none"/>
      <path d="M214 232 C 250 214, 266 186, 300 176 S 346 150, 356 134" fill="none" stroke="#1B4DA1" stroke-width="4" stroke-dasharray="2 8" stroke-linecap="round"/>
      <circle cx="356" cy="132" r="30" fill="#2E9E4F" opacity=".14"/>
      <path d="M356 150s-14-12-14-24a14 14 0 0 1 28 0c0 12-14 24-14 24z" fill="url(#hi-navy)"/><circle cx="356" cy="126" r="5" fill="#fff"/>
      <circle cx="244" cy="224" r="11" fill="#fff"/><circle cx="244" cy="224" r="7" fill="url(#hi-green)"/>
      <rect x="214" y="298" width="172" height="12" rx="6" fill="#0F2A57"/>
      <rect x="214" y="320" width="120" height="9" rx="4.5" fill="#CBD5E1"/>
      <g transform="translate(214 342)"><rect width="172" height="44" rx="14" fill="#E8F5EC"/><circle cx="24" cy="22" r="13" fill="url(#hi-green)"/>
        <path d="M18 22l4.5 4.5L31 17.500" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        <rect x="46" y="14" width="86" height="8" rx="4" fill="#1F7A3B" opacity=".85"/><rect x="46" y="28" width="58" height="7" rx="3.500" fill="#1F7A3B" opacity=".35"/></g>
      <rect x="214" y="396" width="172" height="34" rx="12" fill="url(#hi-navy)"/><rect x="258" y="409" width="84" height="8" rx="4" fill="#fff" opacity=".9"/>
    </g>
    <g filter="url(#hi-shadow)"><rect x="62" y="150" width="150" height="62" rx="18" fill="#fff"/><circle cx="94" cy="181" r="17" fill="#EAF0FA"/>
      <path d="M94 192s-10-8-10-16a10 10 0 0 1 20 0c0 8-10 16-10 16z" fill="#0F2A57"/><circle cx="94" cy="176" r="3.500" fill="#fff"/>
      <rect x="120" y="168" width="72" height="8" rx="4" fill="#0F2A57"/><rect x="120" y="184" width="50" height="7" rx="3.500" fill="#94A3B8"/></g>
    <g filter="url(#hi-shadow)"><rect x="388" y="270" width="176" height="64" rx="18" fill="#fff"/><circle cx="420" cy="302" r="18" fill="#E8F5EC"/>
      <path d="M420 291l10 4v7c0 6-4.500 10-10 12-5.500-2-10-6-10-12v-7z" fill="#2E9E4F"/><path d="M415 302l3.500 3.500L425 298" fill="none" stroke="#fff" stroke-width="2.500" stroke-linecap="round" stroke-linejoin="round"/>
      <rect x="448" y="290" width="96" height="8" rx="4" fill="#0F2A57"/><rect x="448" y="306" width="64" height="7" rx="3.500" fill="#94A3B8"/></g>
  `, "0 0 600 500", 'role="presentation"');
}

/* Three people connected, for the "for organizations / events" sections. */
export function teamIllustration() {
  return svg(`
    <rect x="6" y="6" width="388" height="268" rx="28" fill="#F2F6FB"/>
    <g stroke="#CBD5E1" stroke-width="3" stroke-dasharray="3 9" stroke-linecap="round" fill="none"><path d="M120 150 L200 90 L280 150"/><path d="M120 150 H280"/></g>
    <g><circle cx="200" cy="84" r="34" fill="#0F2A57"/><circle cx="200" cy="76" r="11" fill="#fff"/><path d="M180 104c3-12 11-17 20-17s17 5 20 17" fill="#fff"/></g>
    <g><circle cx="118" cy="152" r="30" fill="#2E9E4F"/><circle cx="118" cy="145" r="10" fill="#fff"/><path d="M100 170c3-11 10-15 18-15s15 4 18 15" fill="#fff"/></g>
    <g><circle cx="282" cy="152" r="30" fill="#1B4DA1"/><circle cx="282" cy="145" r="10" fill="#fff"/><path d="M264 170c3-11 10-15 18-15s15 4 18 15" fill="#fff"/></g>
    <rect x="60" y="214" width="280" height="14" rx="7" fill="#DCE7F5"/><rect x="60" y="214" width="190" height="14" rx="7" fill="#2E9E4F"/>
  `, "0 0 400 280", 'role="presentation"');
}

/* A shield with a heart-shaped location pin, for women's safety. */
export function safetyIllustration() {
  return svg(`
    <defs><linearGradient id="sa-n" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1B4DA1"/><stop offset="1" stop-color="#0F2A57"/></linearGradient></defs>
    <rect x="6" y="6" width="388" height="288" rx="28" fill="#F6F2FA"/>
    <circle cx="200" cy="150" r="118" fill="#fff"/><circle cx="200" cy="150" r="84" fill="#F2F6FB"/><circle cx="200" cy="150" r="52" fill="#E4ECF8"/>
    <path d="M200 58 L286 90 V150 c0 52-36 86-86 104 -50-18-86-52-86-104 V90z" fill="url(#sa-n)"/>
    <path d="M200 190s-36-24-36-52a20 20 0 0 1 36-12 20 20 0 0 1 36 12c0 28-36 52-36 52z" fill="#fff"/>
    <circle cx="200" cy="144" r="9" fill="#C62828"/>
    <g fill="#2E9E4F"><circle cx="78" cy="96" r="10"/><circle cx="326" cy="214" r="10"/><circle cx="332" cy="86" r="7" opacity=".6"/><circle cx="70" cy="214" r="7" opacity=".6"/></g>
    <g stroke="#2E9E4F" stroke-width="3" stroke-dasharray="2 8" stroke-linecap="round" fill="none"><path d="M86 100 L150 130"/><path d="M318 210 L250 176"/></g>
  `, "0 0 400 300", 'role="presentation"');
}
