/* Team Codyssey: the ten people listed in the project README. Work descriptions come from
   what each person built in this repository (their branch / agent); nothing is invented.
   Photos: icons/team/ (cropped from the photos the team supplied). Shubhrit has no photo yet. */

export const TEAM = [
  {
    id: "namrata", name: "Namrata Digarse", role: "Team Lead", team: "Codyssey · Lead", tone: 1,
    image: "icons/team/namrata-digarse.webp",
    bio: "Leads Team Codyssey. Built the Sanitation agent: a LangGraph workflow that turns an approved complaint into a cleaning plan with resources, time and a safety check.",
    tags: ["Team lead", "Sanitation agent", "LangGraph"],
  },
  {
    id: "divyansh", name: "Divyansh Kackker", role: "GeoSatya & platform", team: "Codyssey · Platform", tone: 2,
    image: "icons/team/divyansh-kackker.webp",
    bio: "Built GeoSatya location verification and the unified KAVACH platform: live worker tracking, dispatch ranking, sign-in, women's safety SOS and the web app.",
    tags: ["Geolocation", "Live tracking", "Platform"],
  },
  {
    id: "shreya", name: "Shreya Kaushik", role: "Incident Intelligence", team: "Codyssey · Agents", tone: 3,
    image: "icons/team/shreya-kaushik.webp",
    bio: "Built the Incident Intelligence agent: it turns a raw complaint (text, voice transcript, photos, GPS) into a structured incident record with severity and location checks.",
    tags: ["Incident Intelligence", "FastAPI", "Gemini"],
  },
  {
    id: "yash", name: "Yash Dadlani", role: "Duplicate Detection", team: "Codyssey · Agents", tone: 4,
    image: "icons/team/yash-dadlani.webp",
    bio: "Built the Duplicate Detection agent: compares text, location, category and time to flag repeat complaints, without ever merging or deleting one itself.",
    tags: ["Duplicate Detection", "scikit-learn"],
  },
  {
    id: "karanveer", name: "Karanveer Singh Malhotra", role: "Supervisor agent", team: "Codyssey · Agents", tone: 5,
    image: "icons/team/karanveer-singh-malhotra.webp",
    bio: "Built the Supervisor agent: picks the department and priority and decides whether a complaint can proceed or needs a human approval.",
    tags: ["Supervisor agent", "Approvals"],
  },
  {
    id: "ananya", name: "Ananya Dhagat", role: "Dispatch", team: "Codyssey · Repository", tone: 1,
    image: "icons/team/ananya-dhagat.webp",
    bio: "Owns the team repository and built the Dispatch work: deterministic worker assignment by availability, skills, workload and distance.",
    tags: ["Dispatch", "Worker allocation", "Repository"],
  },
  {
    id: "shweta", name: "Shweta Mishra", role: "Field Worker agent", team: "Codyssey · Agents", tone: 2,
    image: "icons/team/shweta-mishra.webp",
    bio: "Built the Field Worker agent: the worker's task flow (accept, start, checklist, before and after photos, GPS) with an enforced task state machine.",
    tags: ["Field Worker agent", "PostgreSQL"],
  },
  {
    id: "shubhrit", name: "Shubhrit Tiwari", role: "Verification agent", team: "Codyssey · Agents", tone: 3,
    image: "",
    bio: "Built the Verification agent: checks completed work with photo quality checks, GPS distance and a deterministic pass or fail decision.",
    tags: ["Verification", "OpenCV"],
  },
  {
    id: "kavyansh", name: "Kavyansh Gupta", role: "Repository & docs", team: "Codyssey · Docs", tone: 4,
    image: "icons/team/kavyansh-gupta.webp",
    bio: "Set up the project repository and wrote the README that maps every agent, its status, test results and the next steps.",
    tags: ["Documentation", "Repository"],
  },
  {
    id: "om", name: "Om Gupta", role: "Team member", team: "Team Codyssey", tone: 5,
    image: "icons/team/om-gupta.webp",
    bio: "Member of Team Codyssey.",
    tags: ["Team Codyssey"],
  },
];
