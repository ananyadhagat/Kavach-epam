# KAVACH — live demo on everyone's phone

Your laptop runs Kavach. Cloudflare gives it a temporary **https** link, so every teammate can open it on their own phone (iPhone or Android, any network, location works).

---

## Before the demo (once)

- Laptop charged and on the internet. Turn off sleep while presenting.
- Everyone has their phone's **Location** switched on.

## Start everything (one command)

Open **PowerShell** on the laptop and run:

```
powershell -ExecutionPolicy Bypass -File D:\Desktop\Kavach-epam-team\start-kavach-demo.ps1
```

1. It asks for an **access code**. Type any code of 6+ characters (example idea: a word + numbers). Nothing is shown while you type; that's normal.
2. Six windows open: 4 team agents, the **KAVACH server**, and the **KAVACH tunnel**.
3. In the **KAVACH tunnel** window, wait ~10 seconds for a line like:
   `https://some-random-words.trycloudflare.com`
4. Send your team **that link + the access code** on WhatsApp.

Laptop link: http://localhost:8000

> The tunnel link is new every time you start. It's a temporary test link, not a real deployment. Anyone with the link **and** the code can open it, so don't post it publicly.

## On each phone

1. Open the https link (Safari on iPhone, Chrome on Android).
2. Enter the access code → **Sign in / Register** → pick a person (see the roles below).
3. When asked for location, tap **Allow**.

**Location is blocked?**
- **iPhone:** Settings → Privacy & Security → Location Services → **On** → Safari Websites → **While Using**, and turn **Precise Location** on. Then in Safari tap **aA** → Website Settings → Location → **Allow**, and reload.
- **Android:** tap the icon left of the address → Permissions → Location → **Allow**.
- Indoors the GPS can be weak. Stand near a window.

**Want the app icon?** iPhone: Share → *Add to Home Screen*. Android: ⋮ → *Install app*.

---

## Who plays what (5 people)

| Phone | Sign in as | Shows |
|---|---|---|
| 1 | **Arjun (event organizer)** — on the laptop/projector | Event dashboard, live map, invites |
| 2 | Teammate who **joins with an invite code** | Event field worker with real GPS |
| 3 | **Aarav (citizen)** | Public complaint without photo, tracking |
| 4 | **Ravi (field worker)** | Civic worker who gets the citizen's complaint |
| 5 | **Priya (supervisor)** | Live map, reviews, AI team agents |

Everyone's phone remembers its own person. Use **Sign out** (top bar) to switch.

---

## Demo 1 — Event operations (works wherever you are)

1. **Arjun (laptop):** *My events* → **Create event** → name it (e.g. "Team demo day"), click the map at **where you are now**, choose 1 km, keep the incident types → **Create**.
2. **Arjun:** *Zones* → click the map → add "Stage" or "Gate 1".
3. **Arjun:** *Workers* → **Create invite code** (tick *First aid* and *Crowd control*) → send the link/code to Phone 2.
4. **Phone 2:** open the invite link (or *Join with an invite code*) → type your name → **Join**. On Home tap **Share my location once**.
5. **Arjun:** *Event dashboard* shows 1 worker "sharing location". Open **Live operations**: the worker is on the map.
6. **Phone 2 (or Arjun):** **Report incident** → *Medical Assistance* → short text → **Submit**. It's dispatched to the right skilled worker automatically.
7. **Phone 2:** opens the task → **Accept** → shares location while travelling → **I've arrived** → *Take before photo* → **Start work** → tick steps → **Completion photo** → **Submit**.
8. **Arjun:** watch it move on the live map; **Completion review** → open it → see the GeoSatya location check, the before/after photos, the ticked steps and the **Verification agent**'s second opinion → **Approve**.

## Demo 2 — Citizen complaint (no photo) to a civic worker

1. **Ravi (Phone 4):** Home → **Share my location once** (be near the citizen).
2. **Aarav (Phone 3):** **Report an issue** → *Garbage* → write a line → allow location → see the **suggested authority** → **Submit** → copy the reference (GS-…).
3. **Ravi:** the job appears in *My assignments* → Accept → Arrive → Before photo → Start → steps → Completion photo.
4. **Aarav:** **Track live** shows the worker coming (like a delivery app); *Track complaint* shows the public status by reference.
5. **Priya (Phone 5):** **Reviews** → open → Approve. Open the incident → **Dispatch & AI** → **Team agents**: Duplicate Detection, Supervisor, Sanitation plan, Verification — each with its developer's name.
6. **Bonus:** Aarav reports the *same* garbage again → Priya sees **Duplicate** (≈95%+ similar) linked to the first.

## Demo 3 — Quick tour (laptop)

- **Kavya (org admin):** Overview, Departments, Workers, Reports, Settings.
- **Neha (platform admin):** organizations, events, verification, plans, authorities.
- **Public site:** Home, Public dashboard, About (who built which agent, live status).

---

## If something goes wrong

| Problem | Fix |
|---|---|
| Phone says "That code is not right" | Check the code; 5 wrong tries = wait 1 minute. |
| Link doesn't open | The tunnel window must stay open; restart the script for a new link. |
| No worker assigned | The worker must have tapped **Share my location once** in the last 15 min, be within 2 km of the incident, have the skill, and not be on break. A supervisor can also assign by hand. |
| "Location not available" | See *Location is blocked* above; or as a last resort tick **Simulate GPS (demo)**. It is always labelled *Simulated* and never counts as real GPS. |
| Team agents show "unavailable" | One agent window was closed; restart the script. Reports still work without them. |
| Ports already in use | Close the old KAVACH windows, then run the script again. |

## Stop

Close all the KAVACH windows. The tunnel link stops working immediately.

All demo data is saved on the laptop in `services\geosatya\data\`. Nothing is pushed to GitHub.
