"""Identity and access.

AUTH_MODE=demo (local prototype): no sign-in. The UI picks a seeded demo
identity and sends it in X-GeoSatya-Demo-User. Only users flagged is_demo
work this way, and the mode is refused when APP_ENV=production.
AUTH_MODE=token: bearer tokens mapped to users (AUTH_TOKENS), a stand-in until
a real identity provider is connected in get_actor().

Authorization is the same in both modes.
"""

import hmac
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from geosatya.models import IncidentRow, TaskRow, UserRow
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
    settings = request.app.state.settings
    if settings.auth_mode == "demo":
        user_id = request.headers.get(DEMO_HEADER)
        if not user_id:
            raise HTTPException(401, "Choose a demo role to continue.")
        user = session.get(UserRow, user_id)
        if user is None or not user.is_demo:
            raise HTTPException(401, "Unknown demo identity.")
        return Actor(user.user_id, user.role, user.display_name)
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    for token, user_id in settings.token_map().items():
        if hmac.compare_digest(token.encode(), credentials.credentials.encode()):
            user = session.get(UserRow, user_id)
            if user is not None:
                return Actor(user.user_id, user.role, user.display_name)
    raise HTTPException(401, "Invalid token", headers={"WWW-Authenticate": "Bearer"})


def require_role(*roles: str):
    def check(actor: Actor = Depends(get_actor)) -> Actor:
        if actor.role not in roles:
            raise HTTPException(403, f"This needs the {' or '.join(r.lower() for r in roles)} role.")
        return actor
    return check


def task_of(session: Session, incident_id: str) -> TaskRow | None:
    return session.scalar(select(TaskRow).where(TaskRow.incident_id == incident_id))


def load_incident(session: Session, incident_id: str, actor: Actor) -> IncidentRow:
    """Citizens see their own reports, workers the incidents assigned to them,
    supervisors everything. Anything else is reported as not found."""
    incident = session.get(IncidentRow, incident_id)
    if incident is not None:
        if actor.role == "SUPERVISOR" or (actor.role == "CITIZEN" and incident.reporter_id == actor.user_id):
            return incident
        task = task_of(session, incident_id)
        if actor.role == "WORKER" and task is not None and task.worker_id == actor.user_id:
            return incident
    raise HTTPException(404, "Incident not found")


def load_task(session: Session, task_id: str, actor: Actor) -> TaskRow:
    task = session.get(TaskRow, task_id)
    if task is None or actor.role == "CITIZEN" or (actor.role == "WORKER" and task.worker_id != actor.user_id):
        raise HTTPException(404, "Task not found")
    return task
