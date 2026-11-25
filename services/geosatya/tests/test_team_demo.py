"""Team live demo (TEAM_DEMO=1): only the ten team members exist for the app, and a complaint goes the
whole way: citizen reports -> a team worker is assigned -> works -> completes -> Namrata approves."""

import pytest
from fastapi.testclient import TestClient

from geosatya.main import create_app
from tests.conftest import SPOT, complaint_post, complete, fix, make_settings, offset, start

TEAM = {"TEAM-NAMRATA": "SUPERVISOR", "TEAM-DIVYANSH": "CITIZEN", "TEAM-SHREYA": "CITIZEN", "TEAM-SHWETA": "CITIZEN",
        "TEAM-KAVYANSH": "WORKER", "TEAM-YASH": "WORKER", "TEAM-SHUBHRIT": "WORKER", "TEAM-ANANYA": "WORKER",
        "TEAM-KARANVEER": "WORKER", "TEAM-OM": "WORKER"}
as_ = lambda uid: {"X-GeoSatya-Demo-User": uid}


@pytest.fixture
def c(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, team_demo=True, seed_demo_data=False))) as client:
        yield client


def test_only_the_ten_team_members_are_offered(c):
    users = c.get("/api/v1/demo/users").json()
    assert {u["user_id"]: u["role"] for u in users} == TEAM
    assert c.get("/api/v1/config").json()["team_demo"] is True
    workers = c.get("/api/v1/workers", headers=as_("TEAM-NAMRATA")).json()
    assert {w["worker_id"] for w in workers} == {k for k, v in TEAM.items() if v == "WORKER"}


def test_a_complaint_goes_from_citizen_to_team_worker_to_approval(c):
    # Two workers share their location near the spot; the nearest one should get it.
    for uid, north in (("TEAM-YASH", 120), ("TEAM-OM", 600)):
        p = offset(SPOT, north_m=north)
        r = c.post("/api/v1/workers/me/check-in", json={"available": True, "location": fix(p)}, headers=as_(uid))
        assert r.status_code == 200, r.text
    r = complaint_post(c, {"category": "road_damage", "title": "Pothole at the gate", "description": "Deep pothole near the main gate.",
                           "device_location": fix(SPOT)}, headers=as_("TEAM-DIVYANSH"))
    assert r.status_code == 201, r.text
    out = r.json()
    ref = out.get("reference") or out.get("incident_id") or out["incident"]["incident_id"]
    inc = c.get(f"/api/v1/incidents/{ref}", headers=as_("TEAM-NAMRATA")).json()
    task = inc["task"]
    assert task and task["worker_id"] == "TEAM-YASH"
    wh = as_("TEAM-YASH")
    start(c, task["task_id"], wh)
    done = complete(c, task["task_id"], wh, device=fix(SPOT))
    comp = done["completion"]
    assert comp["accepted"], comp
    r = c.post(f"/api/v1/completions/{comp['completion_id']}/review", json={"decision": "APPROVE", "reason": ""}, headers=as_("TEAM-NAMRATA"))
    assert r.status_code == 200, r.text
    assert c.get(f"/api/v1/incidents/{ref}", headers=as_("TEAM-NAMRATA")).json()["status"] == "RESOLVED"


def test_team_demo_is_refused_outside_demo_mode(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(make_settings(tmp_path, team_demo=True, auth_mode="jwt", jwt_secret="x" * 40))
