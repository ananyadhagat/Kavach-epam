# Kavach: AI-driven multi-agent incident management (Team Codyssey)

```
kavach/
├── render.yaml                  Render blueprint (backend deploy)
├── backend/                     FastAPI + LangGraph agents + PostgreSQL
│   ├── requirements.txt
│   ├── .env.example             copy to .env
│   ├── tests/test_flow.py       end-to-end test of all 7 agents (pytest)
│   └── app/
│       ├── main.py              app, CORS, startup (creates tables + demo data)
│       ├── config.py  database.py  models.py  schemas.py
│       ├── auth.py              JWT + RBAC (citizen / worker / admin)
│       ├── tools.py             worker search, distance, nearby incidents
│       ├── mcp_server.py        same tools exposed over MCP
│       ├── rag.py + knowledge/  LangChain RAG over the sanitation SOP
│       ├── seed.py              demo users, workers, vehicles
│       ├── routers/             auth.py incidents.py worker.py admin.py
│       └── agents/              intelligence, duplicate, supervisor, sanitation,
│                                dispatch, verification, graph.py (LangGraph)
└── frontend/                    React + Tailwind (Vite)
    ├── package.json  vercel.json  .env.example
    └── src/  main.jsx App.jsx api.js auth.jsx index.css
              components/ (Layout, Badges, PhotoInput, Timeline, MapView, usePolling)
              pages/ (Login, Citizen, NewComplaint, IncidentDetail, Worker, Admin)
```

## Run locally
```bash
# terminal 1: backend
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                   # add GEMINI_API_KEY (optional)
pytest -q                                              # should pass
uvicorn app.main:app --reload                          # http://localhost:8000/docs

# terminal 2: frontend
cd frontend
cp .env.example .env
npm install && npm run dev                             # http://localhost:5173
```
Without a Gemini key the agents use built-in fallback rules so the full flow still works.
With a key, Gemini classifies, plans and compares before/after photos.

Demo logins: citizen@kavach.app / citizen123, worker1@kavach.app / worker123, admin@kavach.app / admin123

## Deploy (all free tiers; check each provider's current limits)
1. **GitHub**: push the whole `kavach/` folder to a new repo.
2. **Database (Neon)**: create a project at neon.tech, copy the connection string (starts with `postgresql://`).
3. **Backend (Render)**: New > Blueprint > select the repo (reads `render.yaml`). Fill `DATABASE_URL`,
   `GEMINI_API_KEY`, and `CORS_ORIGINS` (set a placeholder now). Deploy, then open `https://<name>.onrender.com/api/health`.
4. **Frontend (Vercel)**: Add New > Project > import the repo, set **Root Directory = frontend**, framework Vite,
   env var `VITE_API_URL=https://<name>.onrender.com`. Deploy.
5. **Connect them**: in Render set `CORS_ORIGINS=https://<your-app>.vercel.app` (no trailing slash) and redeploy.
6. Open the Vercel URL. Share it. Done.

Notes: Render's free service sleeps when idle (first request takes ~30-60 s; open the health URL before a demo).
Before a public launch set `SEED_DEMO=false` after creating real accounts, or change the demo passwords.
