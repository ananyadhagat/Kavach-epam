"""Sign-in (JWT) and central authorization, following KAVACH_Authentication_Authorization_Flows.

The server runs in AUTH_MODE=jwt here: no demo identities, only real accounts.
Access codes are test values set in Settings; none is in the frontend."""

import base64
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geosatya.authz import POLICY, PUBLIC
from geosatya.main import create_app
from geosatya.models import UserRow
from geosatya.security import hash_password, make_token, read_token, TokenError
from tests.conftest import SPOT, complaint_post, fix, make_settings, offset

WORKER_CODE, SUP_CODE, ADMIN_CODE = "worker-code-test-1", "super-code-test-2", "admin-code-test-3"
A = "/api/v1/auth"


def jwt_settings(tmp_path, **extra):
    return make_settings(tmp_path, auth_mode="jwt", jwt_secret="x" * 40, worker_access_code=WORKER_CODE,
                         supervisor_access_code=SUP_CODE, admin_access_code=ADMIN_CODE, login_rate_limit_per_min=50,
                         tracking_min_interval_s=0, **extra)


@pytest.fixture
def c(tmp_path):
    with TestClient(create_app(jwt_settings(tmp_path))) as client:
        yield client


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def citizen(c, login="asha@example.com", name="Asha"):
    r = c.post(f"{A}/citizen/register", json={"name": name, "login": login, "password": "safe-pass-123"})
    assert r.status_code == 201, r.text
    return r.json()


def worker(c, login="ravi@example.com", skills=("road_repair",)):
    r = c.post(f"{A}/worker/register", json={"access_code": WORKER_CODE, "name": "Ravi", "login": login,
                                             "password": "safe-pass-123", "skills": list(skills)})
    assert r.status_code == 201, r.text
    return r.json()


def staff_account(c, user_id, login, platform_role=None, workspace_id=None):
    """Supervisor / admin accounts are created beforehand (scripts/kavach_accounts.py does this on a server)."""
    with c.app.state.session_factory() as s:
        u = s.get(UserRow, user_id)
        if u is None:
            u = UserRow(user_id=user_id, display_name=user_id, role="SUPERVISOR", is_demo=False, platform_role=platform_role, workspace_id=workspace_id)
            s.add(u)
        u.login_id, u.password_hash, u.auth_epoch = login, hash_password("staff-pass-123"), 0
        s.commit()


def staff_login(c, login, code=SUP_CODE, password="staff-pass-123"):
    return c.post(f"{A}/supervisor/login", json={"login": login, "password": password, "access_code": code})


# ------------------------------------------------------------ citizen flow
def test_citizen_registers_and_gets_a_jwt_with_the_citizen_role(c):
    out = citizen(c)
    assert out["token_type"] == "bearer" and out["user"]["role"] == "CITIZEN"
    claims = read_token("x" * 40, out["access_token"])
    assert claims["sub"] == out["user"]["user_id"] and claims["role"] == "CITIZEN"
    me = c.get(f"{A}/me", headers=bearer(out["access_token"])).json()
    assert me["role"] == "CITIZEN" and me["login"].startswith("as***@")       # login is masked
    with c.app.state.session_factory() as s:
        u = s.get(UserRow, out["user"]["user_id"])
        assert u.password_hash.startswith("scrypt$") and "safe-pass-123" not in u.password_hash


def test_citizen_login_and_wrong_password(c):
    citizen(c)
    ok = c.post(f"{A}/login", json={"login": "ASHA@example.com ", "password": "safe-pass-123"})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "CITIZEN"
    bad = c.post(f"{A}/login", json={"login": "asha@example.com", "password": "wrong-pass-1"})
    assert bad.status_code == 401
    nobody = c.post(f"{A}/login", json={"login": "nobody@example.com", "password": "wrong-pass-1"})
    assert nobody.status_code == 401 and nobody.json()["detail"] == bad.json()["detail"]   # no hint which one was wrong


def test_registration_rules(c):
    citizen(c)
    again = c.post(f"{A}/citizen/register", json={"name": "Asha", "login": "asha@example.com", "password": "safe-pass-123"})
    assert again.status_code == 409
    weak = c.post(f"{A}/citizen/register", json={"name": "B", "login": "b@example.com", "password": "short"})
    assert weak.status_code == 422
    letters = c.post(f"{A}/citizen/register", json={"name": "Bo", "login": "b@example.com", "password": "onlyletters"})
    assert letters.status_code == 422
    phone = c.post(f"{A}/citizen/register", json={"name": "Bo", "login": "+91 98765-43210", "password": "safe-pass-123"})
    assert phone.status_code == 201 and phone.json()["user"]["login"] == "***3210"
    junk = c.post(f"{A}/citizen/register", json={"name": "Bo", "login": "not-a-login", "password": "safe-pass-123"})
    assert junk.status_code == 422


def test_citizen_cannot_use_worker_or_supervisor_functions(c):
    t = bearer(citizen(c)["access_token"])
    for method, path in [("GET", "/api/v1/tasks"), ("GET", "/api/v1/workers"), ("GET", "/api/v1/dashboard/live"),
                         ("GET", "/api/v1/verification-queue"), ("GET", "/api/v1/kavach/jobs/available"),
                         ("POST", "/api/v1/workers/me/check-in"), ("GET", "/api/v1/dispatch/board"),
                         ("POST", "/api/v1/completions/CMP-X/review"), ("GET", "/api/v1/kavach/admin/overview")]:
        r = c.request(method, path, headers=t, json={})
        assert r.status_code == 403, (method, path, r.status_code)


# ------------------------------------------------------------- worker flow
def test_worker_registers_with_the_access_code_then_logs_in(c):
    out = worker(c)
    assert out["user"]["role"] == "WORKER"
    me = c.get("/api/v1/workers/me", headers=bearer(out["access_token"])).json()
    assert me["skills"] == ["road_repair"]
    login = c.post(f"{A}/login", json={"login": "ravi@example.com", "password": "safe-pass-123"})
    assert login.status_code == 200 and login.json()["user"]["role"] == "WORKER"


def test_worker_registration_needs_the_right_code(c):
    body = {"name": "Xavier", "login": "x@example.com", "password": "safe-pass-123"}
    assert c.post(f"{A}/worker/register", json={**body, "access_code": "wrong-code"}).status_code == 403
    assert c.post(f"{A}/worker/register", json={**body, "access_code": ""}).status_code == 422
    # The code is not an event invite code: invite codes do not work here.
    assert c.post(f"{A}/worker/register", json={**body, "access_code": "ABCD1234"}).status_code == 403


def test_worker_registration_is_closed_without_a_configured_code(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, auth_mode="jwt", jwt_secret="x" * 40))) as c2:
        r = c2.post(f"{A}/worker/register", json={"access_code": "anything", "name": "Xavier", "login": "x@example.com", "password": "safe-pass-123"})
        assert r.status_code == 403
        assert c2.get(f"{A}/options").json()["worker_registration"] is False


def test_worker_cannot_use_supervisor_or_citizen_functions(c):
    t = bearer(worker(c)["access_token"])
    for method, path in [("GET", "/api/v1/workers"), ("GET", "/api/v1/verification-queue"), ("POST", "/api/v1/incidents/X/assign"),
                         ("POST", "/api/v1/kavach/public/reports"), ("GET", "/api/v1/women/overview"), ("PUT", "/api/v1/settings")]:
        assert c.request(method, path, headers=t, json={}).status_code == 403, path


# ---------------------------------------------------------- supervisor flow
def test_supervisor_logs_in_with_credentials_and_the_access_code(c):
    staff_account(c, "SUP-DEMO-03", "priya@city.example")
    ok = staff_login(c, "priya@city.example")
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "SUPERVISOR"
    t = bearer(ok.json()["access_token"])
    assert c.get("/api/v1/verification-queue", headers=t).status_code == 200
    assert staff_login(c, "priya@city.example", code="wrong").status_code == 403
    assert staff_login(c, "priya@city.example", password="wrong-pass-9").status_code == 401
    # Supervisors cannot use the citizen/worker sign-in, and there is no supervisor sign-up.
    assert c.post(f"{A}/login", json={"login": "priya@city.example", "password": "staff-pass-123"}).status_code == 403
    assert c.post(f"{A}/supervisor/register", json={}).status_code in (403, 404, 405)


def test_a_citizen_or_worker_cannot_sign_in_as_supervisor_even_with_the_code(c):
    citizen(c)
    worker(c)
    assert staff_login(c, "asha@example.com", password="safe-pass-123").status_code == 401
    assert staff_login(c, "ravi@example.com", password="safe-pass-123").status_code == 401


def test_platform_admin_needs_the_separate_admin_code(c):
    staff_account(c, "PA-DEMO-01", "admin@kavach.example", platform_role="PLATFORM_ADMIN")
    assert staff_login(c, "admin@kavach.example", code=SUP_CODE).status_code == 403     # supervisor code is not enough
    ok = staff_login(c, "admin@kavach.example", code=ADMIN_CODE)
    assert ok.status_code == 200
    assert c.get("/api/v1/kavach/admin/overview", headers=bearer(ok.json()["access_token"])).status_code == 200
    # An ordinary supervisor cannot use the admin code, nor the platform pages.
    staff_account(c, "SUP-DEMO-03", "priya@city.example")
    assert staff_login(c, "priya@city.example", code=ADMIN_CODE).status_code == 403
    sup = bearer(staff_login(c, "priya@city.example").json()["access_token"])
    assert c.get("/api/v1/kavach/admin/overview", headers=sup).status_code == 403


# ------------------------------------------------------------------ tokens
def test_requests_without_a_valid_token_are_refused(c):
    assert c.get("/api/v1/incidents").status_code == 401
    assert c.get("/api/v1/incidents", headers=bearer("not.a.token")).status_code == 401
    assert c.get("/api/v1/incidents", headers={"X-GeoSatya-Demo-User": "SUP-DEMO-03"}).status_code == 401   # no demo identities in jwt mode
    assert c.get("/api/v1/demo/users").status_code == 404


def test_forged_tampered_expired_and_none_alg_tokens_are_refused(c):
    out = citizen(c)
    uid = out["user"]["user_id"]
    forged = make_token("another-secret-" + "y" * 30, user_id=uid, role="CITIZEN", platform_role=None, epoch=0, ttl_s=600)
    assert c.get("/api/v1/incidents", headers=bearer(forged)).status_code == 401
    # Change the role inside a valid token: the signature no longer matches.
    h, body, sig = out["access_token"].split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=="))
    claims["role"] = "SUPERVISOR"
    evil = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    assert c.get("/api/v1/workers", headers=bearer(f"{h}.{evil}.{sig}")).status_code == 401
    none_header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    assert c.get("/api/v1/incidents", headers=bearer(f"{none_header}.{body}.")).status_code == 401
    expired = make_token("x" * 40, user_id=uid, role="CITIZEN", platform_role=None, epoch=0, ttl_s=-5)
    assert c.get("/api/v1/incidents", headers=bearer(expired)).status_code == 401
    with pytest.raises(TokenError):
        read_token("x" * 40, expired)


def test_a_signed_token_whose_role_differs_from_the_database_is_refused(c):
    out = citizen(c)
    uid = out["user"]["user_id"]
    # Even a correctly signed token cannot claim a role the account does not have.
    lying = make_token("x" * 40, user_id=uid, role="SUPERVISOR", platform_role=None, epoch=0, ttl_s=600)
    assert c.get("/api/v1/workers", headers=bearer(lying)).status_code == 401


def test_logout_and_deactivation_stop_the_token(c):
    out = citizen(c)
    t = bearer(out["access_token"])
    assert c.get("/api/v1/incidents", headers=t).status_code == 200
    assert c.post(f"{A}/logout", headers=t).status_code == 200
    assert c.get("/api/v1/incidents", headers=t).status_code == 401
    fresh = bearer(c.post(f"{A}/login", json={"login": "asha@example.com", "password": "safe-pass-123"}).json()["access_token"])
    with c.app.state.session_factory() as s:
        s.get(UserRow, out["user"]["user_id"]).is_active = False
        s.commit()
    assert c.get("/api/v1/incidents", headers=fresh).status_code == 403
    assert c.post(f"{A}/login", json={"login": "asha@example.com", "password": "safe-pass-123"}).status_code == 403


def test_sign_in_attempts_are_rate_limited(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, auth_mode="jwt", jwt_secret="x" * 40, login_rate_limit_per_min=3))) as c2:
        codes = [c2.post(f"{A}/login", json={"login": "a@example.com", "password": "wrong-pass-1"}).status_code for _ in range(5)]
        assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


# ------------------------------------------------------- central authorization
def test_every_api_route_has_an_explicit_policy(c):
    """Deny by default: a route missing from POLICY would be refused for everyone; this test makes it a decision."""
    missing, prefix = [], "/api/v1"
    for inc in [r for r in c.app.routes if type(r).__name__ == "_IncludedRouter"] or []:
        cands = inc.effective_candidates() if callable(inc.effective_candidates) else inc.effective_candidates
        for r in cands:
            route = getattr(r, "route", r)
            for m in getattr(route, "methods", []) or []:
                key = f"{m} {route.path[len(prefix):]}"
                if route.path.startswith(prefix) and key not in POLICY:
                    missing.append(key)
    assert not missing, missing


def test_unknown_policy_is_denied(c, monkeypatch):
    monkeypatch.delitem(POLICY, "GET /kavach/catalog")
    assert c.get("/api/v1/kavach/catalog").status_code == 403


def test_public_routes_need_no_sign_in_and_reveal_no_codes(c):
    for key, rule in POLICY.items():
        if rule == PUBLIC and key.startswith("GET ") and "{" not in key:
            assert c.get("/api/v1" + key[4:]).status_code not in (401, 403), key   # 422 = missing query values, still no sign-in
    opts = c.get(f"{A}/options").json()
    blob = json.dumps(opts) + json.dumps(c.get("/api/v1/config").json())
    for code in (WORKER_CODE, SUP_CODE, ADMIN_CODE, "x" * 40):
        assert code not in blob
    assert opts == {"auth_mode": "jwt", "citizen_signup": True, "worker_registration": True, "supervisor_login": True,
                    "admin_login": True, "demo_identities": False}


def test_no_access_code_or_secret_in_frontend_files():
    frontend = Path(__file__).resolve().parent.parent / "frontend"
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in frontend.rglob("*.js"))
    assert not re.search(r"(WORKER|SUPERVISOR|ADMIN)_ACCESS_CODE\s*[=:]\s*['\"]\w", text)
    assert "jwt_secret" not in text.lower()


def test_complaints_are_owned_and_workspaces_are_isolated(c):
    a = bearer(citizen(c, "asha@example.com")["access_token"])
    b = bearer(citizen(c, "bilal@example.com", "Bilal")["access_token"])
    r = complaint_post(c, {"category": "road_damage", "title": "Pothole at the gate", "description": "A deep pothole at the main gate.",
                           "device_location": fix(SPOT)}, headers=a)
    assert r.status_code == 201, r.text
    inc = r.json()
    assert c.get(f"/api/v1/incidents/{inc['incident_id']}", headers=a).status_code == 200
    assert c.get(f"/api/v1/incidents/{inc['incident_id']}", headers=b).status_code == 404          # someone else's complaint
    assert [i["incident_id"] for i in c.get("/api/v1/incidents", headers=b).json()] == []
    photo = inc["photos"][0]["url"]
    assert c.get(photo, headers=a).status_code == 200
    assert c.get(photo, headers=b).status_code == 404 and c.get(photo).status_code == 401           # photos are private
    # Only the supervisors of the workspace the complaint was routed to see it.
    staff_account(c, "ORG-DEMO-01", "org@city.example", platform_role="ORG_ADMIN", workspace_id="WS-DEMO-ORG")
    org = bearer(staff_login(c, "org@city.example").json()["access_token"])
    staff_account(c, "SUP-DEMO-03", "priya@city.example")
    civic = bearer(staff_login(c, "priya@city.example").json()["access_token"])
    a_ = inc["authority"]["authority"] or {}
    routed_to_org = a_.get("on_kavach") and a_.get("workspace_id") == "WS-DEMO-ORG"   # never for sample data with real sign-in
    assert c.get(f"/api/v1/incidents/{inc['incident_id']}", headers=org).status_code == (200 if routed_to_org else 404)
    assert c.get(f"/api/v1/incidents/{inc['incident_id']}", headers=civic).status_code == (404 if routed_to_org else 200)
    # A far-away complaint stays with the open civic team: the organization cannot see it.
    far = complaint_post(c, {"category": "garbage", "title": "Garbage pile", "description": "Garbage pile by the far road.",
                             "device_location": fix((12.9716, 77.5946))}, headers=a).json()
    assert c.get(f"/api/v1/incidents/{far['incident_id']}", headers=org).status_code == 404
    assert c.get(f"/api/v1/incidents/{far['incident_id']}", headers=civic).status_code == 200


def test_worker_sees_only_assigned_tasks_and_locations_stay_with_supervisors(c):
    w = worker(c, skills=("road_repair",))
    wt = bearer(w["access_token"])
    assert c.post("/api/v1/workers/me/check-in", headers=wt, json={"available": True, "location": fix(offset(SPOT, east_m=80))}).status_code == 200
    a = bearer(citizen(c)["access_token"])
    inc = complaint_post(c, {"category": "road_damage", "title": "Pothole by the bank", "description": "A deep pothole by the bank.",
                             "device_location": fix(SPOT)}, headers=a).json()
    tasks = c.get("/api/v1/tasks", headers=wt).json()
    other = worker(c, "meena@example.com")
    ot = bearer(other["access_token"])
    if inc["task"] and inc["task"]["worker_id"] == w["user"]["user_id"]:
        assert [t["task_id"] for t in tasks] == [inc["task"]["task_id"]]
        assert c.get(f"/api/v1/tasks/{inc['task']['task_id']}", headers=ot).status_code == 404
        assert c.get(f"/api/v1/tasks/{inc['task']['task_id']}/tracking", headers=a).status_code == 403   # citizen: not this endpoint
    # Worker locations are listed only for supervisors.
    assert c.get("/api/v1/workers", headers=wt).status_code == 403
    assert c.get("/api/v1/workers", headers=a).status_code == 403
    staff_account(c, "SUP-DEMO-03", "priya@city.example")
    sup = bearer(staff_login(c, "priya@city.example").json()["access_token"])
    assert any(x["worker_id"] == w["user"]["user_id"] for x in c.get("/api/v1/workers", headers=sup).json())


def test_demo_mode_still_works_and_also_accepts_jwt(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, jwt_secret="x" * 40))) as d:
        assert d.get("/api/v1/incidents", headers={"X-GeoSatya-Demo-User": "CIT-DEMO-01"}).status_code == 200
        t = d.post(f"{A}/citizen/register", json={"name": "Asha", "login": "asha@example.com", "password": "safe-pass-123"}).json()["access_token"]
        assert d.get("/api/v1/incidents", headers=bearer(t)).status_code == 200


def test_production_refuses_unsafe_auth_configuration(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(make_settings(tmp_path, app_env="production", auth_mode="jwt", jwt_secret=""))
    with pytest.raises(RuntimeError):
        create_app(make_settings(tmp_path, auth_mode="jwt", jwt_secret="short"))
    with pytest.raises(RuntimeError):
        create_app(make_settings(tmp_path, auth_mode="jwt", worker_access_code="abc"))


def test_complaints_go_only_to_registered_workers(c):
    """With real sign-in, seeded demo workers (no password) never get a job, and a real complaint
    near the sample city stays with the civic team and its registered workers."""
    from geosatya.kavach.seed import CITY
    w = worker(c, skills=("road_repair",))
    wt = bearer(w["access_token"])
    spot = offset(CITY, north_m=400)                       # inside the sample municipal authority's area
    assert c.post("/api/v1/workers/me/check-in", headers=wt, json={"available": True, "location": fix(offset(spot, east_m=150))}).status_code == 200
    a = bearer(citizen(c)["access_token"])
    inc = complaint_post(c, {"category": "road_damage", "title": "Pothole by the town hall", "description": "Deep pothole by the town hall.",
                             "device_location": fix(spot)}, headers=a).json()
    assert inc["task"]["worker_id"] == w["user"]["user_id"]
    with c.app.state.session_factory() as s:
        from geosatya.models import IncidentRow
        assert s.get(IncidentRow, inc["incident_id"]).workspace_id is None          # not the sample workspace
    # A supervisor cannot hand it to a demo worker who could never sign in, and only registered workers are listed.
    staff_account(c, "SUP-DEMO-03", "priya@city.example")
    sup = bearer(staff_login(c, "priya@city.example").json()["access_token"])
    assert [x["worker_id"] for x in c.get("/api/v1/workers", headers=sup).json()] == [w["user"]["user_id"]]
    r = c.post(f"/api/v1/tasks/{inc['task']['task_id']}/reassign", headers=sup, json={"worker_id": "W-DEMO-12", "reason": "Closer to the site"})
    assert r.status_code == 409 and r.json()["code"] == "WORKER_NOT_REGISTERED"


def test_with_no_registered_worker_the_complaint_waits_for_one(c):
    a = bearer(citizen(c)["access_token"])
    inc = complaint_post(c, {"category": "road_damage", "title": "Pothole at the gate", "description": "A deep pothole at the main gate.",
                             "device_location": fix(SPOT)}, headers=a).json()
    assert inc["task"] is None and inc["status"] == "SUBMITTED"     # demo workers exist, but none can sign in
