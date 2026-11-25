"""Sign-in (/api/v1/auth), following KAVACH_Authentication_Authorization_Flows:

Citizen:    sign up / log in -> FastAPI checks the credentials -> JWT (role CITIZEN).
Worker:     predefined Worker Access Code + registration -> JWT (role WORKER);
            afterwards the worker logs in with their own credentials.
Supervisor: no sign-up. Accounts are created beforehand (scripts/kavach_accounts.py).
            Credentials + predefined Supervisor Access Code -> JWT (role SUPERVISOR).
            Platform admins use the separate Admin Access Code.

Access codes live only in the server's environment. They are never returned
by any endpoint; /auth/options only says whether each door is open.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from geosatya.api.deps import get_actor, get_session
from geosatya.models import UserRow, WorkerProfileRow
from geosatya.security import code_matches, hash_password, make_token, normalise_login, password_problem, verify_password
from geosatya.services.common import Actor, ServiceError, audit, new_id
from geosatya.timeutil import iso, utcnow

router = APIRouter(prefix="/auth", tags=["Sign-in"])
Strict = ConfigDict(extra="forbid", str_strip_whitespace=True)
WRONG = "The sign-in details are not correct."


class CitizenSignUp(BaseModel):
    model_config = Strict
    name: str = Field(min_length=2, max_length=80)
    login: str = Field(min_length=5, max_length=160, description="Email address or mobile number")
    password: str = Field(min_length=1, max_length=200)


class WorkerSignUp(CitizenSignUp):
    access_code: str = Field(min_length=1, max_length=80)
    skills: list[str] = Field(default_factory=list, max_length=20)


class Login(BaseModel):
    model_config = Strict
    login: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=1, max_length=200)


class StaffLogin(Login):
    access_code: str = Field(min_length=1, max_length=80)


def _state(request: Request):
    return request.app.state


def _client(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")


def _limit(request: Request, *keys: str) -> None:
    state = _state(request)
    limiter = state.auth_limiter  # one per app (made in create_app)
    for key in keys:
        if not limiter.allow(key):
            raise ServiceError("Too many attempts. Please wait a minute and try again.", 429, "RATE_LIMITED")


def _login_id(raw: str) -> str:
    login = normalise_login(raw)
    if login is None:
        raise ServiceError("Enter a valid email address or a 10 to 15 digit mobile number.", 422, "INVALID_LOGIN")
    return login


def _check_password(password: str) -> None:
    problem = password_problem(password)
    if problem:
        raise ServiceError(problem, 422, "WEAK_PASSWORD")


def _session_out(request: Request, user: UserRow) -> dict:
    settings = _state(request).settings
    ttl = int(settings.jwt_ttl_hours * 3600)
    token = make_token(_state(request).jwt_secret, user_id=user.user_id, role=user.role, platform_role=user.platform_role,
                       epoch=user.auth_epoch or 0, ttl_s=ttl)
    return {"access_token": token, "token_type": "bearer", "expires_in": ttl, "user": _user_view(user)}


def _user_view(user: UserRow) -> dict:
    return {"user_id": user.user_id, "display_name": user.display_name, "role": user.role,
            "platform_role": user.platform_role, "workspace_id": user.workspace_id, "login": _masked(user.login_id)}


def _masked(login: str | None) -> str | None:
    if not login:
        return None
    if "@" in login:
        name, _, domain = login.partition("@")
        return f"{name[:2]}***@{domain}"
    return f"***{login[-4:]}"


def _create(session: Session, *, name: str, login: str, password: str, role: str, prefix: str) -> UserRow:
    if session.scalar(select(UserRow.user_id).where(UserRow.login_id == login)) is not None:
        raise ServiceError("An account with this email or mobile number already exists. Please sign in.", 409, "ACCOUNT_EXISTS")
    user = UserRow(user_id=new_id(prefix, 4), display_name=name.strip()[:80], role=role, is_demo=False, login_id=login,
                   password_hash=hash_password(password), auth_epoch=0, registered_at=utcnow(), last_login_at=utcnow(),
                   phone=login if login[0] in "+0123456789" else None)
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise ServiceError("An account with this email or mobile number already exists. Please sign in.", 409, "ACCOUNT_EXISTS") from None
    return user


# --------------------------------------------------------------- routes
@router.get("/options")
def options(request: Request):
    """Which sign-in doors are open. Never returns a code."""
    s = _state(request).settings
    return {"auth_mode": s.auth_mode, "citizen_signup": True,
            "worker_registration": bool(s.worker_access_code.get_secret_value()),
            "supervisor_login": bool(s.supervisor_access_code.get_secret_value()),
            "admin_login": bool(s.admin_access_code.get_secret_value()),
            "demo_identities": s.auth_mode == "demo" and s.app_env != "production"}


@router.post("/citizen/register", status_code=201)
def citizen_register(body: CitizenSignUp, request: Request, session: Session = Depends(get_session)):
    _limit(request, f"register:{_client(request)}")
    login = _login_id(body.login)
    _check_password(body.password)
    user = _create(session, name=body.name, login=login, password=body.password, role="CITIZEN", prefix="CIT")
    audit(session, Actor(user.user_id, user.role, user.display_name), "ACCOUNT_REGISTERED", None, role="CITIZEN")
    session.commit()
    return _session_out(request, user)


@router.post("/worker/register", status_code=201)
def worker_register(body: WorkerSignUp, request: Request, session: Session = Depends(get_session)):
    """Worker registration needs the predefined Worker Access Code (not an
    event invitation). The code is checked here, on the server."""
    _limit(request, f"register:{_client(request)}")
    expected = _state(request).settings.worker_access_code.get_secret_value()
    if not expected:
        raise ServiceError("Worker registration is not open on this server.", 403, "WORKER_REGISTRATION_CLOSED")
    if not code_matches(body.access_code, expected):
        raise ServiceError("That worker access code is not correct.", 403, "WRONG_ACCESS_CODE")
    login = _login_id(body.login)
    _check_password(body.password)
    known = {s for c in _state(request).categories.items for s in (c.get("dispatch") or {}).get("required_skills", [])}
    skills = [s for s in dict.fromkeys(body.skills) if s in known]
    user = _create(session, name=body.name, login=login, password=body.password, role="WORKER", prefix="W")
    session.add(WorkerProfileRow(user_id=user.user_id, skills=skills, equipment=[], available=True, max_active_tasks=3))
    audit(session, Actor(user.user_id, user.role, user.display_name), "ACCOUNT_REGISTERED", None, role="WORKER", skills=skills)
    session.commit()
    return _session_out(request, user)


@router.post("/login")
def login(body: Login, request: Request, session: Session = Depends(get_session)):
    """Citizens and field workers. Supervisors use /auth/supervisor/login."""
    login_id = normalise_login(body.login) or body.login.strip().lower()
    _limit(request, f"login:{_client(request)}", f"login-account:{login_id}")
    user = session.scalar(select(UserRow).where(UserRow.login_id == login_id))
    if not verify_password(body.password, user.password_hash if user else None) or user is None:
        raise ServiceError(WRONG, 401, "WRONG_CREDENTIALS")
    if user.is_active is False:
        raise ServiceError("This account has been deactivated.", 403, "ACCOUNT_INACTIVE")
    if user.role == "SUPERVISOR":
        raise ServiceError("Supervisors sign in on the supervisor page, with the supervisor access code.", 403, "USE_STAFF_SIGN_IN")
    user.last_login_at = utcnow()
    session.commit()
    return _session_out(request, user)


@router.post("/supervisor/login")
def supervisor_login(body: StaffLogin, request: Request, session: Session = Depends(get_session)):
    """No sign-up: the account must exist already. Needs the right access code
    too: the Supervisor Access Code, or the Admin Access Code for a platform admin."""
    login_id = normalise_login(body.login) or body.login.strip().lower()
    _limit(request, f"staff:{_client(request)}", f"staff-account:{login_id}")
    s = _state(request).settings
    user = session.scalar(select(UserRow).where(UserRow.login_id == login_id))
    password_ok = verify_password(body.password, user.password_hash if user else None)
    if user is None or not password_ok or user.role != "SUPERVISOR":
        raise ServiceError(WRONG, 401, "WRONG_CREDENTIALS")
    expected = (s.admin_access_code if user.platform_role == "PLATFORM_ADMIN" else s.supervisor_access_code).get_secret_value()
    if not code_matches(body.access_code, expected):
        audit(session, Actor(user.user_id, user.role, user.display_name), "STAFF_SIGN_IN_REFUSED", None, reason="access code")
        session.commit()
        raise ServiceError("The access code is not correct.", 403, "WRONG_ACCESS_CODE")
    if user.is_active is False:
        raise ServiceError("This account has been deactivated.", 403, "ACCOUNT_INACTIVE")
    user.last_login_at = utcnow()
    audit(session, Actor(user.user_id, user.role, user.display_name), "STAFF_SIGNED_IN", None, platform_role=user.platform_role)
    session.commit()
    return _session_out(request, user)


@router.get("/me")
def auth_me(actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    from geosatya.authz import ROLE_PERMISSIONS
    user = session.get(UserRow, actor.user_id)
    return {**_user_view(user), "permissions": ROLE_PERMISSIONS.get(actor.role, []),
            "last_login_at": iso(user.last_login_at) if user.last_login_at else None}


@router.post("/logout")
def logout(actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    """Signs this account out everywhere: every token issued before now stops working."""
    user = session.get(UserRow, actor.user_id)
    if user.password_hash:
        user.auth_epoch = (user.auth_epoch or 0) + 1
        session.commit()
    return {"signed_out": True}
