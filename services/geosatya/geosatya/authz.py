"""Central authorization for every API request.

Each request passes through authorize() before its handler runs:
  1. validate the access token (JWT)        -> deps.get_actor
  2. identify the user                       -> deps.get_actor (reloaded from the database)
  3. identify the role                       -> deps.get_actor (the database role must match the token)
  4. check the role's permission             -> POLICY below
  5. check ownership / workspace             -> deps.load_incident, deps.load_task, kavach.service.managed/viewable
  6. allow, or answer 401 (not signed in) / 403 (signed in, not allowed)

Deny by default: a route missing from POLICY is refused with 403 for everyone,
and a test fails, so a new route cannot be added without a decision here.
Hiding buttons in the frontend is only a convenience; this table is the rule.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from geosatya.api.deps import bearer, get_actor, get_session

PUBLIC = "PUBLIC"      # no sign-in (the handler may still refuse, e.g. demo-only routes)
SIGNED_IN = "SIGNED_IN"  # any signed-in role; the handler scopes the data to the caller
C, W, S = "CITIZEN", "WORKER", "SUPERVISOR"

# What each role may do (for people reading this file; enforced by POLICY).
ROLE_PERMISSIONS = {
    C: ["register and sign in", "submit complaints (photo + GPS)", "track own complaints", "view progress",
        "give feedback on own resolved complaints", "women's safety: trusted allies and SOS"],
    W: ["view assigned tasks", "accept / decline tasks", "claim eligible open tasks", "update task status",
        "share real GPS location", "submit before and completion evidence", "view task history"],
    S: ["complaints in own workspace", "manage workers", "assign / reassign tasks", "monitor live operations",
        "review evidence, approve or reject", "reports", "(platform admin only) platform administration"],
}

# "METHOD /path" (without the /api/v1 prefix) -> PUBLIC, SIGNED_IN or the roles allowed.
POLICY: dict[str, str | tuple[str, ...]] = {
    # --- sign-in
    "GET /auth/options": PUBLIC,
    "POST /auth/citizen/register": PUBLIC,
    "POST /auth/worker/register": PUBLIC,          # needs the worker access code
    "POST /auth/login": PUBLIC,                    # citizens and workers
    "POST /auth/supervisor/login": PUBLIC,         # needs credentials + supervisor/admin access code
    "GET /auth/me": SIGNED_IN,
    "POST /auth/logout": SIGNED_IN,
    # --- app
    "GET /config": PUBLIC,
    "GET /categories": PUBLIC,
    "GET /demo/users": PUBLIC,                     # 404 unless AUTH_MODE=demo
    "POST /demo/reset": (S,),
    "GET /me": SIGNED_IN,
    "GET /dashboard": SIGNED_IN,
    "GET /settings": SIGNED_IN,
    "PUT /settings": (S,),
    # --- incidents (handlers scope to own / assigned / workspace)
    "POST /incidents": (C,),
    "GET /incidents": SIGNED_IN,
    "GET /incidents/{incident_id}": SIGNED_IN,
    "GET /incidents/{incident_id}/tracking": SIGNED_IN,
    "POST /incidents/{incident_id}/intelligence/retry": (S,),
    "POST /incidents/{incident_id}/dispatch/retry": (S,),
    "GET /incidents/{incident_id}/dispatch/candidates": (S,),   # read-only worker search
    "POST /incidents/{incident_id}/assign": (S,),
    "POST /incidents/{incident_id}/correct-location": (S,),
    "GET /media/{media_id}": SIGNED_IN,
    # --- tasks
    "GET /tasks": (W, S),
    "GET /tasks/{task_id}": (W, S),
    "POST /tasks/{task_id}/start": (W,),
    "POST /tasks/{task_id}/accept": (W,),
    "POST /tasks/{task_id}/decline": (W,),
    "POST /tasks/{task_id}/location": (W,),
    "POST /tasks/{task_id}/arrive": (W,),
    "POST /tasks/{task_id}/progress": (W,),
    "POST /tasks/{task_id}/tracking/stop": (W,),
    "POST /tasks/{task_id}/completion": (W,),
    "GET /tasks/{task_id}/tracking": (W, S),
    "POST /tasks/{task_id}/release": (S,),
    "POST /tasks/{task_id}/reassign": (S,),
    # --- workers and supervision
    "GET /workers": (S,),
    "GET /workers/me": (W,),
    "POST /workers/me/check-in": (W,),
    "GET /dispatch/board": (S,),
    "GET /dashboard/live": (S,),
    "GET /verification-queue": (S,),
    "GET /completions/{completion_id}": (S,),
    "POST /completions/{completion_id}/review": (S,),
    "GET /evidence-history": (S,),
    # --- KAVACH public
    "GET /kavach/catalog": PUBLIC,
    "GET /kavach/public/stats": PUBLIC,
    "GET /kavach/public/track/{reference}": PUBLIC,  # reference number only; no personal data
    "GET /kavach/authorities/suggest": PUBLIC,
    "GET /kavach/agents/status": PUBLIC,
    "POST /kavach/public/reports": (C,),
    "POST /kavach/register/organization": PUBLIC,    # 404 unless AUTH_MODE=demo
    "POST /kavach/register/event-organizer": PUBLIC,  # 404 unless AUTH_MODE=demo
    "POST /kavach/join": PUBLIC,                     # 404 unless AUTH_MODE=demo
    # --- KAVACH workspaces
    "GET /kavach/me": SIGNED_IN,
    "GET /kavach/workspaces/{workspace_id}": SIGNED_IN,  # members and managers only (handler)
    "PUT /kavach/workspaces/{workspace_id}": (S,),
    "POST /kavach/workspaces/{workspace_id}/departments": (S,),
    "DELETE /kavach/workspaces/{workspace_id}/departments/{department_id}": (S,),
    "POST /kavach/workspaces/{workspace_id}/zones": (S,),
    "DELETE /kavach/workspaces/{workspace_id}/zones/{zone_id}": (S,),
    "GET /kavach/workspaces/{workspace_id}/members": (S,),
    "POST /kavach/workspaces/{workspace_id}/members": (S,),
    "PATCH /kavach/workspaces/{workspace_id}/members/{user_id}": (S,),
    "GET /kavach/workspaces/{workspace_id}/invites": (S,),
    "POST /kavach/workspaces/{workspace_id}/invites": (S,),
    "POST /kavach/workspaces/{workspace_id}/incidents": (W, S),
    "GET /kavach/workspaces/{workspace_id}/report": (S,),
    "POST /kavach/events": (S,),
    "POST /kavach/events/{workspace_id}/open": (S,),
    "POST /kavach/events/{workspace_id}/archive": (S,),
    "GET /kavach/admin/overview": (S,),               # + platform admin (handler)
    "POST /kavach/admin/workspaces/{workspace_id}/verification": (S,),
    "POST /kavach/admin/authorities": (S,),
    "DELETE /kavach/admin/authorities/{authority_id}": (S,),
    "POST /kavach/incidents/{incident_id}/forwarded": (S,),
    "GET /kavach/incidents/{incident_id}/agents": (S,),
    "GET /kavach/incidents/{incident_id}/check": SIGNED_IN,  # reporter, assigned worker, workspace supervisors (handler)
    "POST /kavach/incidents/{incident_id}/agents/retry": (S,),
    "GET /kavach/tasks/{task_id}/work-check": (W, S),
    "POST /kavach/tasks/{task_id}/checklist": (W,),
    "POST /kavach/tasks/{task_id}/before-photo": (W,),
    "GET /kavach/incidents/{incident_id}/feedback": (C, S),
    "POST /kavach/incidents/{incident_id}/feedback": (C,),
    "GET /kavach/jobs/available": (W,),
    "POST /kavach/jobs/{incident_id}/claim": (W,),
    # --- women's safety (the citizen's own allies and alerts only)
    "GET /women/overview": (C,),
    "POST /women/allies": (C,),
    "PATCH /women/allies/{ally_id}": (C,),
    "DELETE /women/allies/{ally_id}": (C,),
    "POST /women/sos": (C,),
    "GET /women/sos/{sos_id}": (C,),
    "POST /women/sos/{sos_id}/location": (C,),
    "POST /women/sos/{sos_id}/manual-location": (C,),
    "POST /women/sos/{sos_id}/cancel": (C,),
    "POST /women/sos/{sos_id}/resolve": (C,),
    "GET /women/share/{token}": PUBLIC,             # private per-ally link (unguessable token)
    # --- optional voice notes (SOS and task completion); ownership is checked again in the handler
    "POST /women/sos/{sos_id}/audio-notes": (C,),
    "GET /women/sos/{sos_id}/audio-notes/{note_id}": (C,),
    "GET /women/share/{token}/audio-notes/{note_id}": PUBLIC,   # same private per-ally link, only while the SOS is active
    "POST /tasks/{task_id}/audio-notes": (W,),
    "GET /tasks/{task_id}/audio-notes": (W, S),
    "GET /tasks/{task_id}/audio-notes/{note_id}": (W, S),
}


def policy_key(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    prefix = request.app.state.settings.api_prefix
    if path.startswith(prefix):
        path = path[len(prefix):]
    return f"{request.method.upper()} {path}"


def authorize(request: Request, session: Session = Depends(get_session),
              credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    rule = POLICY.get(policy_key(request))
    if rule is None:
        raise HTTPException(403, "This action is not allowed.")  # deny by default
    if rule == PUBLIC:
        return
    actor = get_actor(request, session, credentials)  # 401 when not signed in or the token is not valid
    if rule == SIGNED_IN:
        return
    if actor.role not in rule:
        raise HTTPException(403, f"Your role ({actor.role.lower()}) is not allowed to do this.")
