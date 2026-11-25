"""Identity and access.

AUTH_MODE=jwt (default): users sign in (geosatya/api/auth_routes.py) and send
the JWT access token as "Authorization: Bearer <token>".
AUTH_MODE=demo (development only): JWT sign-in works, and the UI may also pick
a seeded demo identity sent in X-GeoSatya-Demo-User. Only users flagged
is_demo work this way, and the mode is refused when APP_ENV=production.
AUTH_MODE=token: fixed bearer tokens mapped to users (AUTH_TOKENS), for scripts.

Authorization is the same in every mode: geosatya/authz.py checks each route,
and the loaders below check ownership and workspace.
"""

import hmac
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from geosatya.models import IncidentRow, TaskRow, UserRow
from geosatya.scope import is_active, same_workspace
from geosatya.security import TokenError, looks_like_jwt, read_token
from geosatya.services.common import Actor

DEMO_HEADER = "X-GeoSatya-Demo-User"
bearer = HTTPBearer(auto_error=False)


def get_session(request: Request) -> Iterator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_actor(request: Request, session: Session = Depends(get_session),
              credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Actor:
    cached = getattr(request.state, "actor", None)
    if cached is not None:
        return cached
    actor = _identify(request, session, credentials)
    request.state.actor = actor
    return actor


def _identify(request: Request, session: Session, credentials: HTTPAuthorizationCredentials | None) -> Actor:
    settings = request.app.state.settings
    token = credentials.credentials if credentials is not None and credentials.scheme.lower() == "bearer" else None
    if token and looks_like_jwt(token) and settings.auth_mode in ("jwt", "demo"):
        return _jwt_actor(request, session, token)
    if settings.auth_mode == "jwt":
        raise HTTPException(401, "Please sign in to continue.", headers={"WWW-Authenticate": "Bearer"})
    if settings.auth_mode == "demo":
        user_id = request.headers.get(DEMO_HEADER)
        if not user_id:
            raise HTTPException(401, "Choose a demo role to continue.")
        user = session.get(UserRow, user_id)
        if user is None or not user.is_demo:
            raise HTTPException(401, "Unknown demo identity.")
        return _actor(user)
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    for token, user_id in settings.token_map().items():
        if hmac.compare_digest(token.encode(), credentials.credentials.encode()):
            user = session.get(UserRow, user_id)
            if user is not None:
                return _actor(user)
    raise HTTPException(401, "Invalid token", headers={"WWW-Authenticate": "Bearer"})


def _jwt_actor(request: Request, session: Session, token: str) -> Actor:
    """Validate the JWT, then identify the user and role from the database: a
    deactivated account, a changed role or a signed-out token stops working at once."""
    expired = HTTPException(401, "Your sign-in has expired. Please sign in again.", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = read_token(request.app.state.jwt_secret, token)
    except TokenError:
        raise expired from None
    user = session.get(UserRow, claims["sub"])
    if user is None or not user.password_hash:
        raise expired
    if claims.get("role") != user.role or claims.get("prole") != user.platform_role or claims.get("ep") != (user.auth_epoch or 0):
        raise expired
    return _actor(user)


def _actor(user: UserRow) -> Actor:
    if not is_active(user):
        raise HTTPException(403, "This account has been deactivated by its workspace administrator.")
    workspace = user.workspace_id
    if workspace is None and user.platform_role in TENANT_ROLES:
        # A tenant admin with no workspace open must not fall into the open
        # civic scope (workspace None): give them a scope that matches nothing.
        workspace = f"NONE:{user.user_id}"
    return Actor(user.user_id, user.role, user.display_name, workspace_id=workspace, platform_role=user.platform_role)


TENANT_ROLES = ("ORG_ADMIN", "EVENT_ORGANIZER")


def optional_actor(request: Request, session: Session = Depends(get_session),
                   credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Actor | None:
    """For public pages: the caller's identity when they sent one, else None."""
    try:
        return get_actor(request, session, credentials)
    except HTTPException:
        return None


def require_role(*roles: str):
    def check(actor: Actor = Depends(get_actor)) -> Actor:
        if actor.role not in roles:
            raise HTTPException(403, f"This needs the {' or '.join(r.lower() for r in roles)} role.")
        return actor
    return check


def task_of(session: Session, incident_id: str) -> TaskRow | None:
    return session.scalar(select(TaskRow).where(TaskRow.incident_id == incident_id))


def load_incident(session: Session, incident_id: str, actor: Actor) -> IncidentRow:
    """Reporters see their own reports, workers the incidents assigned to them,
    supervisors every incident of their own workspace (KAVACH tenancy).
    Anything else is reported as not found."""
    incident = session.get(IncidentRow, incident_id)
    if incident is not None:
        if actor.role == "SUPERVISOR" and same_workspace(actor.workspace_id, incident.workspace_id):
            return incident
        if incident.reporter_id == actor.user_id:
            return incident
        task = task_of(session, incident_id)
        if actor.role == "WORKER" and task is not None and task.worker_id == actor.user_id:
            return incident
    raise HTTPException(404, "Incident not found")


def load_task(session: Session, task_id: str, actor: Actor) -> TaskRow:
    task = session.get(TaskRow, task_id)
    if task is None or actor.role == "CITIZEN" or (actor.role == "WORKER" and task.worker_id != actor.user_id):
        raise HTTPException(404, "Task not found")
    if actor.role == "SUPERVISOR":
        incident = session.get(IncidentRow, task.incident_id)
        if incident is None or not same_workspace(actor.workspace_id, incident.workspace_id):
            raise HTTPException(404, "Task not found")
    return task


def require_civic_supervisor(actor: Actor = Depends(require_role("SUPERVISOR"))) -> Actor:
    """Platform-wide GeoSatya settings (geofence radius, GPS accuracy limit,
    demo reset) belong to the civic platform, not to a tenant workspace."""
    if actor.workspace_id is not None:
        raise HTTPException(403, "Verification limits are set platform-wide, not per workspace.")
    return actor
