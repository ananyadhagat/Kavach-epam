"""KAVACH platform: tenant isolation, photo-free public reporting with
authority suggestion, event and organization workspaces, invitations,
and the public tracking / statistics pages."""

import pytest
from fastapi.testclient import TestClient

from geosatya.kavach.seed import CITY, EVENT
from geosatya.main import create_app
from tests.conftest import CITIZEN, SUPERVISOR, fix, make_settings, offset, report

ORG_ADMIN = {"X-GeoSatya-Demo-User": "ORG-DEMO-01"}
ORG_SUP = {"X-GeoSatya-Demo-User": "OSUP-DEMO-01"}
ROAD_CREW = {"X-GeoSatya-Demo-User": "OW-DEMO-21"}
ORGANIZER = {"X-GeoSatya-Demo-User": "EO-DEMO-01"}
MEDIC = {"X-GeoSatya-Demo-User": "EW-DEMO-31"}
GUARD = {"X-GeoSatya-Demo-User": "EW-DEMO-32"}
ADMIN = {"X-GeoSatya-Demo-User": "PA-DEMO-01"}
NEAR_CITY = offset(CITY, north_m=400, east_m=300)
K = "/api/v1/kavach"


@pytest.fixture
def c(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, tracking_min_interval_s=0))) as client:
        yield client


def check_in(c, headers, point):
    r = c.post("/api/v1/workers/me/check-in", json={"available": True, "location": fix(point)}, headers=headers)
    assert r.status_code == 200, r.text


def public_report(c, point=NEAR_CITY, category="road_damage", road_type=None, headers=CITIZEN, expect=201, **extra):
    body = {"category": category, "title": "Deep pothole on the main road", "description": "A large pothole is damaging vehicles.",
            "device_location": fix(point), **({"road_type": road_type} if road_type else {}), **extra}
    r = c.post(f"{K}/public/reports", json=body, headers=headers)
    assert r.status_code == expect, r.text
    return r.json()


def event_report(c, headers, point, category="medical_assistance", expect=201, **extra):
    body = {"category": category, "title": "Runner collapsed near the start", "description": "A runner is dizzy and needs help now.",
            "device_location": fix(point), **extra}
    r = c.post(f"{K}/workspaces/WS-DEMO-EVT/incidents", json=body, headers=headers)
    assert r.status_code == expect, r.text
    return r.json()


# ------------------------------------------------------------ public civic
def test_public_report_needs_no_photo_and_is_routed_to_the_municipal_workspace(c):
    check_in(c, ROAD_CREW, offset(NEAR_CITY, east_m=200))
    inc = public_report(c)
    assert inc["photos"] == []
    assert inc["authority"]["authority"]["authority_id"] == "AUTH-DEMO-MUN"
    assert inc["task"]["worker_id"] == "OW-DEMO-21"           # the organization's own worker, not a civic one
    # GeoSatya's location evidence is recorded exactly as for any report.
    assert inc["location"]["source"] == "DEVICE_GEOLOCATION"
    # The organization sees it; the open civic supervisor does not.
    assert c.get(f"/api/v1/incidents/{inc['incident_id']}", headers=ORG_ADMIN).status_code == 200
    assert c.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).status_code == 404
    # The citizen still sees their own report.
    assert c.get(f"/api/v1/incidents/{inc['incident_id']}", headers=CITIZEN).status_code == 200


def test_national_highway_report_suggests_the_highway_authority_and_is_not_claimed_as_sent(c):
    inc = public_report(c, road_type="NATIONAL_HIGHWAY")
    a = inc["authority"]["authority"]
    assert a["authority_id"] == "AUTH-DEMO-NH" and a["on_kavach"] is False
    track = c.get(f"{K}/public/track/{inc['incident_id']}").json()
    assert track["forwarding_status"] == "NOT_FORWARDED"           # never "submitted to NHAI"
    assert c.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).status_code == 200  # stays with the civic team
    r = c.post(f"{K}/incidents/{inc['incident_id']}/forwarded", headers=SUPERVISOR)
    assert r.json()["forwarding_status"] == "FORWARDED_MANUALLY"


def test_report_outside_every_jurisdiction_stays_with_the_open_civic_team(c):
    far = (12.97, 77.59)
    inc = public_report(c, point=far)
    assert inc["authority"]["authority"] is None and "manual review" in inc["authority"]["reason"]


def test_public_portal_refuses_event_categories_and_non_citizens(c):
    public_report(c, category="medical_assistance", expect=422)
    public_report(c, headers=ROAD_CREW, expect=403)


def test_the_original_geosatya_report_still_requires_a_photo(c):
    r = report(c, device=fix(NEAR_CITY), photos=0, expect=422)
    assert r["code"] == "PHOTO_REQUIRED"


def test_public_tracking_shows_status_only_and_hides_private_details(c):
    inc = public_report(c)
    t = c.get(f"{K}/public/track/{inc['incident_id'].lower()}").json()
    assert t["reference"] == inc["incident_id"] and t["stages"][0]["done"] is True
    assert not {"description", "latitude", "longitude", "reporter_id", "title", "location"} & set(t)


def test_event_incidents_are_not_public(c):
    check_in(c, MEDIC, offset(EVENT, east_m=50))
    inc = event_report(c, GUARD, offset(EVENT, east_m=20))
    assert c.get(f"{K}/public/track/{inc['incident_id']}").status_code == 404
    stats = c.get(f"{K}/public/stats").json()
    assert all(x["category"] != "medical_assistance" for x in stats["by_category"])


def test_public_stats_give_rounded_areas_not_points(c):
    public_report(c)
    s = c.get(f"{K}/public/stats").json()
    assert s["total"] >= 1
    assert all(len(str(a["latitude"]).split(".")[-1]) <= 2 for a in s["areas"])


# --------------------------------------------------------- tenant isolation
def test_tenants_cannot_see_each_others_incidents_workers_or_queues(c):
    check_in(c, ROAD_CREW, NEAR_CITY)
    check_in(c, MEDIC, offset(EVENT, east_m=40))
    org_inc = public_report(c)
    evt_inc = event_report(c, GUARD, offset(EVENT, east_m=10))
    civic = report(c, device=fix(offset(CITY, north_m=-300)))

    def ids(headers):
        return {i["incident_id"] for i in c.get("/api/v1/incidents", headers=headers).json()}

    assert org_inc["incident_id"] in ids(ORG_ADMIN) and not {evt_inc["incident_id"], civic["incident_id"]} & ids(ORG_ADMIN)
    assert evt_inc["incident_id"] in ids(ORGANIZER) and not {org_inc["incident_id"], civic["incident_id"]} & ids(ORGANIZER)
    assert civic["incident_id"] in ids(SUPERVISOR) and not {org_inc["incident_id"], evt_inc["incident_id"]} & ids(SUPERVISOR)

    live = c.get("/api/v1/dashboard/live", headers=ORGANIZER).json()
    assert {w["worker_id"] for w in live["workers"]} == {"EW-DEMO-31", "EW-DEMO-32"}
    assert {i["incident_id"] for i in live["incidents"]} == {evt_inc["incident_id"]}
    assert {w["worker_id"] for w in c.get("/api/v1/workers", headers=ORG_ADMIN).json()} == {"OW-DEMO-21", "OW-DEMO-22"}
    assert c.get(f"/api/v1/tasks/{org_inc['task']['task_id']}", headers=ORGANIZER).status_code == 404
    assert c.get(f"/api/v1/incidents/{evt_inc['incident_id']}/tracking", headers=ORG_ADMIN).status_code == 404
    # Workspace pages are private to their own admins.
    assert c.get(f"{K}/workspaces/WS-DEMO-ORG", headers=ORGANIZER).status_code == 404
    assert c.get(f"{K}/workspaces/WS-DEMO-EVT/members", headers=ORG_ADMIN).status_code == 404


def test_a_worker_from_another_workspace_cannot_be_assigned_even_with_override(c):
    civic = report(c, device=fix(offset(CITY, north_m=-300)))
    r = c.post(f"/api/v1/tasks/{civic['task']['task_id']}/reassign",
               json={"worker_id": "OW-DEMO-21", "reason": "Closer crew", "override": True}, headers=SUPERVISOR)
    assert r.status_code == 422 and r.json()["code"] == "NOT_A_WORKER"


def test_tenant_admins_cannot_change_platform_verification_limits_or_reset(c):
    r = c.put("/api/v1/settings", json={"geofence_radius_m": 50, "max_accuracy_m": 50}, headers=ORG_ADMIN)
    assert r.status_code == 403
    assert c.post("/api/v1/demo/reset", headers=ORGANIZER).status_code == 403


def test_a_new_organizer_without_an_event_sees_nothing_not_the_civic_workspace(c):
    report(c, device=fix(offset(CITY, north_m=-300)))
    org = c.post(f"{K}/register/event-organizer", json={"name": "Riya", "company": "Riya Events"}).json()
    h = {"X-GeoSatya-Demo-User": org["user_id"]}
    assert c.get("/api/v1/incidents", headers=h).json() == []
    live = c.get("/api/v1/dashboard/live", headers=h).json()
    assert live["incidents"] == [] and live["workers"] == [] and live["kpis"]["total_reported"] == 0


def test_platform_admin_sees_tenant_counts_but_no_incident_data(c):
    public_report(c)
    o = c.get(f"{K}/admin/overview", headers=ADMIN).json()
    org = next(w for w in o["workspaces"] if w["workspace_id"] == "WS-DEMO-ORG")
    assert org["incidents"]["total"] == 1 and "title" not in org
    assert c.get(f"{K}/admin/overview", headers=ORG_ADMIN).status_code == 403
    r = c.post(f"{K}/admin/workspaces/WS-DEMO-ORG/verification", json={"status": "VERIFIED", "note": "Documents checked"},
               headers=ADMIN)
    assert r.json()["verification_status"] == "VERIFIED"


# -------------------------------------------------------- event workflow
def test_event_lifecycle_register_create_invite_join_report_dispatch(c):
    org = c.post(f"{K}/register/event-organizer", json={"name": "Riya", "company": "Riya Events"}).json()
    h = {"X-GeoSatya-Demo-User": org["user_id"]}
    venue = (23.2700, 77.4300)
    ev = c.post(f"{K}/events", headers=h, json={
        "name": "Food Festival", "category": "FESTIVAL", "venue": "Riverside grounds",
        "center_latitude": venue[0], "center_longitude": venue[1], "radius_m": 800,
        "starts_at": "2026-12-01T10:00:00+05:30", "ends_at": "2026-12-01T22:00:00+05:30"})
    assert ev.status_code == 201, ev.text
    ev = ev.json()
    assert c.get(f"{K}/me", headers=h).json()["workspace"]["workspace_id"] == ev["workspace_id"]  # the new event is open

    zone = c.post(f"{K}/workspaces/{ev['workspace_id']}/zones", headers=h,
                  json={"name": "Food court", "latitude": venue[0], "longitude": venue[1], "radius_m": 120}).json()
    inv = c.post(f"{K}/workspaces/{ev['workspace_id']}/invites", headers=h,
                 json={"role": "WORKER", "skills": ["first_aid", "crowd_control"]}).json()
    joined = c.post(f"{K}/join", json={"code": inv["code"].lower(), "name": "Dev"}).json()
    assert joined["workspace"]["workspace_id"] == ev["workspace_id"]
    assert c.post(f"{K}/join", json={"code": inv["code"], "name": "Again"}).status_code == 404   # one-time
    w = {"X-GeoSatya-Demo-User": joined["user_id"]}
    check_in(c, w, offset(venue, east_m=30))
    check_in(c, MEDIC, offset(venue, east_m=10))    # a closer worker from another event must not be picked

    body = {"category": "medical_assistance", "title": "Visitor fainted", "description": "A visitor fainted near the stalls.",
            "device_location": fix(offset(venue, east_m=5)), "zone_id": zone["zone_id"]}
    inc = c.post(f"{K}/workspaces/{ev['workspace_id']}/incidents", json=body, headers=h)
    assert inc.status_code == 201, inc.text
    assert inc.json()["task"]["worker_id"] == joined["user_id"]
    body["category"] = "road_damage"
    assert c.post(f"{K}/workspaces/{ev['workspace_id']}/incidents", json=body, headers=h).json()["code"] == "CATEGORY_DISABLED"


def test_outsiders_cannot_report_into_an_event(c):
    event_report(c, ROAD_CREW, offset(EVENT, east_m=5), expect=404)
    event_report(c, CITIZEN, offset(EVENT, east_m=5), expect=404)


def test_report_outside_the_event_area_is_flagged_not_blocked(c):
    inc = event_report(c, GUARD, offset(EVENT, north_m=6000))
    assert "OUTSIDE_WORKSPACE_AREA" in inc["location"]["flags"]


def test_organizer_customizes_categories_and_cannot_claim_notification_delivery(c):
    r = c.put(f"{K}/workspaces/WS-DEMO-EVT", headers=ORGANIZER, json={"settings": {
        "categories": ["medical_assistance", "missing_person"], "notifications": {"channels_connected": True}}})
    s = r.json()["settings"]
    assert s["categories"] == ["medical_assistance", "missing_person"] and s["notifications"]["channels_connected"] is False
    r = c.put(f"{K}/workspaces/WS-DEMO-EVT", headers=ORGANIZER, json={"settings": {"categories": ["made_up"]}})
    assert r.status_code == 422


def test_deactivated_member_is_locked_out_and_never_dispatched(c):
    check_in(c, MEDIC, offset(EVENT, east_m=5))
    r = c.patch(f"{K}/workspaces/WS-DEMO-EVT/members/EW-DEMO-31", json={"active": False}, headers=ORGANIZER)
    assert r.json()["active"] is False
    assert c.get("/api/v1/me", headers=MEDIC).status_code == 403
    inc = event_report(c, GUARD, offset(EVENT, east_m=5))
    assert (inc["task"] or {}).get("worker_id") != "EW-DEMO-31"


# --------------------------------------------------- organization workflow
def test_organization_registers_and_builds_its_structure(c):
    r = c.post(f"{K}/register/organization", json={
        "name": "Green Campus FM", "category": "FACILITY_MANAGEMENT", "admin_name": "Sunita",
        "verification_details": "GST certificate uploaded offline", "center_latitude": 23.3, "center_longitude": 77.5,
        "radius_m": 3000})
    assert r.status_code == 201, r.text
    ws = r.json()["workspace"]
    assert ws["verification_status"] == "PENDING"
    h = {"X-GeoSatya-Demo-User": r.json()["user_id"]}
    dep = c.post(f"{K}/workspaces/{ws['workspace_id']}/departments", headers=h,
                 json={"name": "Electrical", "categories": ["streetlight"]}).json()
    m = c.post(f"{K}/workspaces/{ws['workspace_id']}/members", headers=h,
               json={"name": "Raju", "skills": ["electrical"], "department_id": dep["department_id"]}).json()
    assert m["department"] == "Electrical" and m["role"] == "WORKER"
    detail = c.get(f"{K}/workspaces/{ws['workspace_id']}", headers=h).json()
    assert detail["departments"][0]["members"] == 1 and detail["can_manage"] is True
    # Another tenant's department id is rejected.
    bad = c.post(f"{K}/workspaces/{ws['workspace_id']}/members", headers=h,
                 json={"name": "X", "department_id": "DEP-DEMO-ROADS"})
    assert bad.status_code == 422


def test_plan_worker_limit_is_enforced(c):
    org = c.post(f"{K}/register/event-organizer", json={"name": "Riya", "company": "Riya Events"}).json()
    h = {"X-GeoSatya-Demo-User": org["user_id"]}
    ev = c.post(f"{K}/events", headers=h, json={"name": "Tiny meetup", "category": "PRIVATE",
                                                "center_latitude": 23.2, "center_longitude": 77.4}).json()
    with c.app.state.session_factory() as s:
        from geosatya.platform_models import PlanRow
        s.get(PlanRow, "EVENT_PASS").max_workers = 1
        s.commit()
    assert c.post(f"{K}/workspaces/{ev['workspace_id']}/members", headers=h, json={"name": "Asha"}).status_code == 201
    r = c.post(f"{K}/workspaces/{ev['workspace_id']}/members", headers=h, json={"name": "Bina"})
    assert r.status_code == 409 and r.json()["code"] == "PLAN_LIMIT"


def test_registration_is_development_only(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, auth_mode="token", auth_tokens="tok-1234567890abcdef:SUP-DEMO-03"))) as c2:
        r = c2.post(f"{K}/register/event-organizer", json={"name": "Riya", "company": "Riya Events"})
        assert r.status_code == 404
