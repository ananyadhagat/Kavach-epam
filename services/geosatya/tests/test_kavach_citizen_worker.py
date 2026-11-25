"""Citizen and worker features added to KAVACH: the twelve complaint categories, the five public
progress stages, citizen feedback after resolution, and the worker's available jobs and claiming."""

import pytest
from fastapi.testclient import TestClient

from geosatya.kavach.seed import CITY
from geosatya.main import create_app
from tests.conftest import complaint_post, CITIZEN, CITIZEN2, SUPERVISOR, WORKER12, complete, fix, make_settings, offset, report, review

K = "/api/v1/kavach"
SPOT = (12.9700, 77.5900)                 # far outside the municipal sample area: stays with the open civic team
ORG_WORKER = {"X-GeoSatya-Demo-User": "OW-DEMO-21"}
TWELVE = ["garbage", "road_damage", "drainage", "water_leakage", "streetlight", "public_toilet", "sanitation", "waste_disposal",
          "infrastructure", "highway", "safety_hazard", "other"]


@pytest.fixture
def c(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, tracking_min_interval_s=0, dispatch_fallback="escalate", report_rate_limit_per_min=200))) as client:
        yield client


def check_in(c, headers, point, available=True):
    r = c.post("/api/v1/workers/me/check-in", json={"available": available, "location": fix(point)}, headers=headers)
    assert r.status_code == 200, r.text


def public(c, category, point=SPOT, **extra):
    body = {"category": category, "title": f"{category} problem near the market", "description": "Something needs fixing here soon.",
            "device_location": fix(point), **extra}
    r = complaint_post(c, body, headers=CITIZEN)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------- categories
def test_all_twelve_complaint_categories_exist_and_can_be_reported(c):
    cats = {x["id"]: x for x in c.get("/api/v1/categories").json()["categories"]}
    assert set(TWELVE) <= set(cats)
    for cid in TWELVE:
        assert cats[cid]["label"] and cats[cid]["instructions"] and cats[cid]["dispatch"]["required_skills"]
    catalog = c.get(f"{K}/catalog").json()["categories"]
    assert [x["id"] for x in catalog if x.get("scope") != "event"][:3] == ["road_damage", "garbage", "water_leakage"]
    for cid in TWELVE:
        inc = public(c, cid)
        assert inc["category"] == cid and len(inc["photos"]) == 1


def test_highway_reports_reach_the_highway_authority(c):
    s = c.get(f"{K}/authorities/suggest", params={"latitude": CITY[0], "longitude": CITY[1] + 0.02, "category": "highway", "road_type": "NATIONAL_HIGHWAY"}).json()
    assert s["authority"]["authority_id"] == "AUTH-DEMO-NH"


# ------------------------------------------------------------ public stages
def test_public_tracking_shows_the_five_requested_stages(c):
    inc = public(c, "garbage")
    t = c.get(f"{K}/public/track/{inc['incident_id']}").json()
    assert [s["label"] for s in t["stages"]] == ["Reported", "Verified", "Assigned", "In progress", "Resolved"]
    assert [s["done"] for s in t["stages"]] == [True, False, False, False, False]
    check_in(c, WORKER12, offset(SPOT, east_m=100))
    # a worker with the right skill takes it: Assigned
    r = report(c, device=fix(SPOT), title="Pothole beside the school", description="Deep pothole beside the school gate.")
    assert r["task"], "worker should be dispatched"
    t = c.get(f"{K}/public/track/{r['incident_id']}").json()
    assert [s["done"] for s in t["stages"]] == [True, True, True, False, False]       # verified is implied once assigned
    assert [s["current"] for s in t["stages"]].index(True) == 2
    w = {"X-GeoSatya-Demo-User": r["task"]["worker_id"]}
    c.post(f"/api/v1/tasks/{r['task']['task_id']}/start", headers=w)
    res = complete(c, r["task"]["task_id"], w, device=fix(offset(SPOT, east_m=2)))
    assert [s["done"] for s in c.get(f"{K}/public/track/{r['incident_id']}").json()["stages"]] == [True, True, True, True, False]
    review(c, res["completion"]["completion_id"], "APPROVE")
    assert all(s["done"] for s in c.get(f"{K}/public/track/{r['incident_id']}").json()["stages"])


# ---------------------------------------------------------------- feedback
def resolved_incident(c):
    check_in(c, WORKER12, offset(SPOT, east_m=100))
    r = report(c, device=fix(SPOT), title="Pothole beside the school", description="Deep pothole beside the school gate.")
    w = {"X-GeoSatya-Demo-User": r["task"]["worker_id"]}
    c.post(f"/api/v1/tasks/{r['task']['task_id']}/start", headers=w)
    res = complete(c, r["task"]["task_id"], w, device=fix(offset(SPOT, east_m=2)))
    return r, res


def test_citizen_can_rate_a_resolved_complaint_once_it_is_resolved(c):
    r, res = resolved_incident(c)
    iid = r["incident_id"]
    assert c.get(f"{K}/incidents/{iid}/feedback", headers=CITIZEN).json() == {"feedback": None, "can_give": False}
    assert c.post(f"{K}/incidents/{iid}/feedback", json={"rating": 5}, headers=CITIZEN).json()["code"] == "NOT_RESOLVED"
    review(c, res["completion"]["completion_id"], "APPROVE")
    assert c.get(f"{K}/incidents/{iid}/feedback", headers=CITIZEN).json()["can_give"] is True
    ok = c.post(f"{K}/incidents/{iid}/feedback", json={"rating": 4, "comment": "  Fixed quickly, thank you  "}, headers=CITIZEN)
    assert ok.status_code == 201 and ok.json()["feedback"]["rating"] == 4 and ok.json()["feedback"]["comment"] == "Fixed quickly, thank you"
    c.post(f"{K}/incidents/{iid}/feedback", json={"rating": 5}, headers=CITIZEN)          # changing it replaces, never duplicates
    assert c.get(f"{K}/incidents/{iid}/feedback", headers=SUPERVISOR).json()["feedback"]["rating"] == 5


def test_feedback_rules(c):
    r, res = resolved_incident(c)
    iid = r["incident_id"]
    review(c, res["completion"]["completion_id"], "APPROVE")
    assert c.post(f"{K}/incidents/{iid}/feedback", json={"rating": 0}, headers=CITIZEN).status_code == 422
    assert c.post(f"{K}/incidents/{iid}/feedback", json={"rating": 6}, headers=CITIZEN).status_code == 422
    assert c.post(f"{K}/incidents/{iid}/feedback", json={"rating": 5}, headers=CITIZEN2).status_code == 404       # not their complaint
    assert c.post(f"{K}/incidents/{iid}/feedback", json={"rating": 5}, headers=SUPERVISOR).status_code == 403     # only the reporter
    assert c.post(f"{K}/incidents/{iid}/feedback", json={"rating": 5}, headers=WORKER12).status_code == 403


# ---------------------------------------------------------- available jobs
def open_job(c, category="road_damage"):
    """A complaint nobody has been dispatched to (no worker has shared a location yet)."""
    r = complaint_post(c, {"category": category, "title": "Pothole at the junction", "description": "A big pothole at the junction.",
                                            "device_location": fix(SPOT)}, headers=CITIZEN)
    assert r.status_code == 201 and r.json()["task"] is None
    return r.json()["incident_id"]


def test_worker_sees_and_claims_a_nearby_open_job_they_have_skills_for(c):
    iid = open_job(c)
    none = c.get(f"{K}/jobs/available", headers=WORKER12).json()
    assert none["jobs"] == [] and "Share your location" in none["note"]            # no location shared yet: nothing guessed
    check_in(c, WORKER12, offset(SPOT, east_m=400))
    jobs = c.get(f"{K}/jobs/available", headers=WORKER12).json()
    assert [j["incident_id"] for j in jobs["jobs"]] == [iid] and 300 <= jobs["jobs"][0]["distance_m"] <= 500
    claim = c.post(f"{K}/jobs/{iid}/claim", headers=WORKER12)
    assert claim.status_code == 200 and claim.json()["claimed"]
    task = c.get(f"/api/v1/tasks/{claim.json()['task_id']}", headers=WORKER12).json()
    assert task["worker_id"] == "W-DEMO-12" and task["incident"]["progress"]["accepted_at"]       # claiming also accepts
    assert c.get(f"{K}/jobs/available", headers=WORKER12).json()["jobs"] == []
    assert c.post(f"{K}/jobs/{iid}/claim", headers=WORKER12).json()["code"] == "JOB_TAKEN"


def test_available_jobs_respect_skills_distance_availability_and_workspace(c):
    garbage_id = open_job(c, "garbage")                # needs waste_collection: W-DEMO-12 does not have it
    road_id = open_job(c, "road_damage")               # both exist before any worker shares a location, so nobody was dispatched
    check_in(c, WORKER12, offset(SPOT, east_m=300))
    assert [j["incident_id"] for j in c.get(f"{K}/jobs/available", headers=WORKER12).json()["jobs"]] == [road_id]   # not the garbage job
    assert c.post(f"{K}/jobs/{garbage_id}/claim", headers=WORKER12).json()["code"] == "NOT_ELIGIBLE"
    check_in(c, WORKER12, offset(SPOT, north_m=5000))  # too far from both
    assert c.get(f"{K}/jobs/available", headers=WORKER12).json()["jobs"] == []
    assert c.post(f"{K}/jobs/{road_id}/claim", headers=WORKER12).json()["code"] == "NOT_ELIGIBLE"
    check_in(c, WORKER12, offset(SPOT, east_m=200), available=False)
    assert "unavailable" in c.get(f"{K}/jobs/available", headers=WORKER12).json()["note"]
    assert c.post(f"{K}/jobs/{road_id}/claim", headers=WORKER12).json()["code"] == "NOT_READY"
    # an organization's worker never sees the open civic team's jobs
    check_in(c, ORG_WORKER, offset(SPOT, east_m=100))
    assert c.get(f"{K}/jobs/available", headers=ORG_WORKER).json()["jobs"] == []
    assert c.post(f"{K}/jobs/{road_id}/claim", headers=ORG_WORKER).status_code == 409


def test_only_workers_use_available_jobs(c):
    assert c.get(f"{K}/jobs/available", headers=CITIZEN).status_code == 403
    assert c.get(f"{K}/jobs/available", headers=SUPERVISOR).status_code == 403
    assert c.post(f"{K}/jobs/GS-NOPE/claim", headers=CITIZEN).status_code == 403


def test_an_organization_worker_claims_the_organizations_own_open_job(c):
    near_city = offset(CITY, north_m=400)
    r = complaint_post(c, {"category": "road_damage", "title": "Pothole by the town hall", "description": "Deep pothole by the town hall.",
                                            "device_location": fix(near_city)}, headers=CITIZEN).json()
    assert r["task"] is None and r["authority"]["authority"]["workspace_id"] == "WS-DEMO-ORG"
    check_in(c, WORKER12, offset(near_city, east_m=100))                 # a civic-team worker: must not see the organization's job
    civic_jobs = [j["incident_id"] for j in c.get(f"{K}/jobs/available", headers=WORKER12).json()["jobs"]]
    assert r["incident_id"] not in civic_jobs                           # (the civic demo streetlight job is theirs to see)
    assert c.post(f"{K}/jobs/{r['incident_id']}/claim", headers=WORKER12).json()["code"] == "JOB_TAKEN"
    check_in(c, ORG_WORKER, offset(near_city, east_m=100))
    jobs = c.get(f"{K}/jobs/available", headers=ORG_WORKER).json()["jobs"]
    assert r["incident_id"] in [j["incident_id"] for j in jobs]           # (the seeded demo streetlight job may be listed too)
    assert c.post(f"{K}/jobs/{r['incident_id']}/claim", headers=ORG_WORKER).status_code == 200
