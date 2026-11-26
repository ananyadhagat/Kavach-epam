# KAVACH: live demo on everyone's phone

The laptop runs KAVACH. Cloudflare gives it a temporary **https** link, so every teammate can open it on their own
phone (iPhone or Android, any network, with real GPS and camera).

---

## Before the demo

- Laptop charged, online, and set not to sleep.
- Everyone's phone has **Location** on.
- `cloudflared` is installed (`winget install --id Cloudflare.cloudflared`).

## Start (one command)

Open **PowerShell** on the laptop:

```powershell
powershell -ExecutionPolicy Bypass -File D:\Desktop\Kavach-epam-team\run-kavach.ps1 -TeamDemo
```

The script starts the four team agents and the server, checks each one, starts the tunnel, tests the link from outside,
and only then prints a **READY** block with the **link** and an **access code**. Send both to the team.

`-TeamDemo` uses its own database (`services\geosatya\data\kavach_team_demo.db`) with exactly the ten team accounts.
Your normal database is not touched. Without `-TeamDemo` the app opens in development access mode with role chips.

> The link and the access code change on every start. Anyone with both can open the site, so don't post them publicly.

## On each phone

1. Open the link (Chrome on Android, Safari on iPhone) and enter the **access code**.
2. Tap **Sign in**, tap **your name**, type the password **`kavach123`** (any password is accepted in the team demo).
3. Tap **Allow** for Location, Camera and Microphone.

**Location blocked?**
- **Android:** tap the icon left of the address → Permissions → Location → **Allow**.
- **iPhone:** Settings → Privacy & Security → Location Services → Safari Websites → **While Using** + **Precise Location**.
- Indoors GPS is weak: go outside or near a window.

---

## Who plays what

| Role | People | Does |
|---|---|---|
| Supervisor | Namrata | Live map, worker radar, approvals |
| Citizens | Divyansh, Shreya, Shweta | Report problems, track them, SOS |
| Field workers | Kavyansh, Yash, Shubhrit, Ananya, Karanveer, Om | Take and complete jobs |

Workers who are not present should tap **Go unavailable** (or a supervisor asks them to), so no job is sent to them.

---

## The demo, in order

1. **Workers go online.** At their spots (within about 2 km of the citizens): **Share my location** → **Go available** →
   **Share my location once**. Repeat if more than 15 minutes pass.
2. **Supervisor watches.** Namrata opens **Live operations map**.
3. **Citizen reports.** Outdoors at a real problem: **Report an issue** → category → camera photo → one line → **Submit**.
   KAVACH assigns the nearest eligible worker automatically.
4. **Worker does the job.** **My tasks** → open the job → **Accept** → **Start journey** → walk to the spot →
   **Start work** → at the spot (**within 15 m**) take the completion photo → optional **voice note** → **Submit evidence**.
5. **Supervisor approves.** **Pending approvals** → check the photos, distance and voice note → **Approve**.
   The citizen's complaint shows **Resolved**.
6. **Worker radar.** Namrata opens any complaint → **Dispatch & AI** → **Find another worker** (or **Find a worker nearby** if nobody is assigned yet): workers appear at their real
   distance and bearing, with rank, workload and skills; she can reassign from there.
7. **SOS.** A citizen opens **Women's safety** → adds a trusted ally → holds **SOS** for one second → records a
   **voice note** → sends the ally link by WhatsApp. The ally opens it, sees the live location and plays the note.
   **I'm safe** ends it.

---

## If something goes wrong

| Problem | Fix |
|---|---|
| "That code is not right" | Check the access code; after 5 wrong tries wait one minute. |
| "Cannot reach the server" on one phone | Switch between Wi-Fi and mobile data, reload, submit again. |
| Link doesn't open for anyone | The laptop or the tunnel window stopped; run the start command again (new link and code). |
| No worker assigned | Workers must share their location in the last 15 min and be within 2 km; or Namrata uses **Find a worker nearby** / **Automatic dispatch**. |
| Completion photo refused | The worker is more than 15 m from the complaint; walk closer and retake it. |
| Team agents "unavailable" | An agent window was closed; restart. Reports still work without them. |

## Stop

```powershell
powershell -ExecutionPolicy Bypass -File D:\Desktop\Kavach-epam-team\stop-kavach.ps1
```

The link stops working immediately. Demo data stays on the laptop in `services\geosatya\data\` and is never committed.
