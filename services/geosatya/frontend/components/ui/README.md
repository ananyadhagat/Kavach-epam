# components/ui

The two supplied React components live here as ports into this app's plain JavaScript
(the KAVACH frontend has no React, TypeScript, Tailwind or build step; FastAPI serves
the files as they are).

| Supplied component | Port in this app | Used on |
|---|---|---|
| `team-lanyard-rail.tsx` (TeamLanyardRail) | `js/kavach/lanyard.js` (same geometry, springs, swing, pull-down reel, drag, flip, carousel, autoplay, keyboard, reduced motion) | `#/team` and the home page team section (`js/kavach/team.js`, data in `js/kavach/team-data.js`) |
| `digital-serenity-animated-landing-page.tsx` (DigitalSerenity) | `js/kavach/serenity.js` (grid drawing, detail dots, corners, floating particles, word-by-word type, mouse glow, click ripples) | the home page hero (`js/kavach/home.js`) |

Styles for both are in `aurora.css` (sections "Digital Serenity hero" and "team lanyard rail").

Why ports and not the `.tsx` files: putting React components into this folder would need
Vite + React + TypeScript + Tailwind + shadcn and a rewrite of every page. If the team later
moves the frontend to that stack, run `npx shadcn@latest init` in a new Vite React TS app,
keep `components/ui` as the shadcn component folder (shadcn's CLI adds components there and
the `@/components/ui/...` imports expect it), and copy the original `.tsx` files in unchanged.
