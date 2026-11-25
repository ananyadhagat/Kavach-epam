"""The full citizen → worker → supervisor flow through the HTTP API."""

import json

import pytest
from fastapi.testclient import TestClient

from geosatya.main import create_app
from geosatya.synthetic_images import pothole_scene
from tests.conftest import (
    CITIZEN, CITIZEN2, SPOT, SUPERVISOR, WORKER12, WORKER15, complete, fix, iso, make_settings, offset, report,
    reported_task, review, start, status_of,
)


# ============================================================ citizen
def test_citizen_report_gets_one_id_and_a_task(client):
    inc = report(client, device=fix(SPOT, accuracy=7))
    assert inc["incident_id"].startswith("GS-") and len(inc["incident_id"]) == 9
    assert inc["status"] == "ASSIGNED"                      # SUBMITTED -> ASSIGNED automatically
    task = inc["task"]
    assert task["status"] == "ASSIGNED" and task["worker_id"] in ("W-DEMO-12", "W-DEMO-15")
    assert (task["target_latitude"], task["target_longitude"]) == pytest.approx(SPOT)
    # the worker can see the task without anyone recreating the complaint
    mine = client.get("/api/v1/tasks", headers={"X-GeoSatya-Demo-User": task["worker_id"]}).json()
    assert inc["incident_id"] in [t["incident"]["incident_id"] for t in mine]


def test_photo_is_associated_with_device_location_evidence(client):
    inc = report(client, device=fix(SPOT, accuracy=7, observed=3))
    loc = inc["location"]
    assert loc["source"] == "DEVICE_GEOLOCATION" and loc["mode"] == "LIVE" and loc["accuracy_m"] == 7
    assert (loc["latitude"], loc["longitude"]) == pytest.approx(SPOT)
    assert loc["observed_at"] and "USER_SELECTED_LOCATION" not in loc["flags"]
    assert len(inc["photos"]) == 1
    evidence = client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).json()["photos"][0]
    # four different times, kept apart
    assert set(evidence["times"]) == {"image_captured_at", "exif_claimed_time", "uploaded_at", "server_received_at"}
    assert evidence["times"]["image_captured_at"] and evidence["times"]["server_received_at"]
    assert evidence["capture_source"] == "CAMERA_LIVE"


def test_gallery_photo_has_no_capture_time_and_is_flagged(client):
    inc = report(client, device=fix(SPOT), source="GALLERY")
    photo = client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).json()["photos"][0]
    assert photo["times"]["image_captured_at"] is None            # not invented from upload time
    assert "PHOTO_FROM_GALLERY" in inc["location"]["flags"]


def test_exif_gps_is_read_separately_and_conflicts_are_flagged(client):
    far = pothole_scene(5, gps=offset(SPOT, north_m=2000), taken="2026:10:20 08:00:00")
    inc = report(client, device=fix(SPOT), source="CAMERA_INPUT", scene=far)
    assert "PHOTO_GPS_CONFLICT" in inc["location"]["flags"]
    detail = client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).json()["photos"][0]
    assert detail["exif_status"] == "GPS_FOUND" and detail["exif_gps"]["latitude"] == pytest.approx(offset(SPOT, north_m=2000)[0], abs=1e-5)
    assert detail["times"]["exif_claimed_time"] == "2026:10:20 08:00:00"
    # the incident location is still the device's, not the photo's
    assert inc["location"]["latitude"] == pytest.approx(SPOT[0])


def test_missing_location_is_refused_unless_a_pin_is_chosen(client):
    report(client, device=None, error="PERMISSION_DENIED", expect=422)
    pinned = report(client, error="PERMISSION_DENIED", pin={"latitude": SPOT[0], "longitude": SPOT[1]})
    assert pinned["location"]["source"] == "USER_SELECTED_PIN" and pinned["location"]["mode"] == "USER_PIN"
    assert "USER_SELECTED_LOCATION" in pinned["location"]["flags"]
    kinds = {e["source_type"] for e in client.get(f"/api/v1/incidents/{pinned['incident_id']}", headers=SUPERVISOR).json().get("evidence", [])} or set()
    assert pinned["status"] == "ASSIGNED"


@pytest.mark.parametrize("bad", [{"latitude": 95, "longitude": 77}, {"latitude": 23, "longitude": 190},
                                 {"latitude": 0, "longitude": 0}, {"latitude": 23, "longitude": 77, "accuracy_m": -3}])
def test_invalid_coordinates_are_rejected(client, bad):
    report(client, device={**bad, "observed_at": iso(1)}, expect=422)


def test_nan_and_infinity_are_rejected(client):
    for bad in ("NaN", "Infinity"):
        payload = ('{"category":"road_damage","title":"Bad one","description":"Bad coordinates here.",'
                   f'"device_location":{{"latitude":{bad},"longitude":77}}}}')
        r = client.post("/api/v1/incidents", data={"payload": payload},
                        files=[("photos", ("a.jpg", pothole_scene(1), "image/jpeg"))], headers=CITIZEN)
        assert r.status_code == 422


def test_report_needs_a_photo_a_real_image_and_a_known_category(client):
    report(client, device=fix(SPOT), photos=0, expect=422)
    r = client.post("/api/v1/incidents", headers=CITIZEN, data={"payload": json.dumps({
        "category": "road_damage", "title": "Not an image", "description": "This is not an image file.",
        "device_location": fix(SPOT), "photos_meta": [{"capture_source": "GALLERY"}]})},
        files=[("photos", ("x.jpg", b"%PDF-1.4 nope", "image/jpeg"))])
    assert r.status_code == 422 and r.json()["code"] == "NOT_AN_IMAGE"
    report(client, device=fix(SPOT), category="spaceships", expect=422)


@pytest.mark.parametrize("category", ["road_damage", "garbage", "water_leakage", "drainage", "streetlight",
                                      "infrastructure", "safety_hazard", "other"])
def test_every_category_works_the_same_way(client, category):
    inc = report(client, device=fix(SPOT), category=category)
    assert inc["category"] == category and inc["task"]["status"] == "ASSIGNED" and inc["instructions"]


def test_incident_location_is_locked(client):
    inc, task, wh = reported_task(client)
    # a worker has no way to move it, and a citizen cannot either
    assert client.post(f"/api/v1/incidents/{inc['incident_id']}/correct-location", headers=wh,
                       json={"latitude": 23.3, "longitude": 77.4, "reason": "trying to cheat"}).status_code == 403
    assert client.post(f"/api/v1/incidents/{inc['incident_id']}/correct-location", headers=CITIZEN,
                       json={"latitude": 23.3, "longitude": 77.4, "reason": "trying to cheat"}).status_code == 403
    # a supervisor can, with a reason; the original stays and the change is audited
    r = client.post(f"/api/v1/incidents/{inc['incident_id']}/correct-location", headers=SUPERVISOR,
                    json={"latitude": SPOT[0] + 0.0001, "longitude": SPOT[1], "reason": "Pin was on the wrong lane"})
    assert r.status_code == 200 and r.json()["task"]["target_source"] == "ADMIN_CORRECTION"
    assert r.json()["location"]["latitude"] == pytest.approx(SPOT[0])           # original untouched
    events = client.get(f"/api/v1/evidence-history?incident_id={inc['incident_id']}", headers=SUPERVISOR).json()["events"]
    assert next(e for e in events if e["action"] == "LOCATION_CORRECTED")["details"]["reason"] == "Pin was on the wrong lane"
    client.post(f"/api/v1/incidents/{inc['incident_id']}/correct-location", headers=SUPERVISOR,
                json={"latitude": SPOT[0], "longitude": SPOT[1], "reason": "x"}).status_code == 422


# ============================================================ worker
def test_worker_inside_radius_passes_but_is_not_resolved_automatically(client):
    inc, task, wh = reported_task(client)
    start(client, task["task_id"], wh)
    res = complete(client, task["task_id"], wh, device=fix(offset(SPOT, east_m=6)))
    c = res["completion"]
    assert c["outcome"] == "PASS" and c["accepted"] and c["distance_m"] == pytest.approx(6, abs=0.3)
    assert "within the permitted radius" in c["message"]
    assert res["incident_status"] == "AWAITING_VERIFICATION" and res["task"]["status"] == "AWAITING_VERIFICATION"
    assert status_of(client, inc["incident_id"]) != "RESOLVED"        # uploading a photo never resolves anything


def test_worker_outside_radius_is_rejected_and_can_retry(client):
    inc, task, wh = reported_task(client)
    start(client, task["task_id"], wh)
    res = complete(client, task["task_id"], wh, device=fix(offset(SPOT, east_m=80)))
    c = res["completion"]
    assert c["outcome"] == "FAIL" and c["accepted"] is False and "Move closer" in c["message"]
    assert res["incident_status"] == "IN_PROGRESS" and res["task"]["status"] == "IN_PROGRESS"
    assert client.get("/api/v1/verification-queue", headers=SUPERVISOR).json() == []      # nothing reaches a supervisor
    # moving closer and retrying works; the failed attempt stays in the history
    retry = complete(client, task["task_id"], wh, device=fix(offset(SPOT, east_m=5)))
    assert retry["completion"]["outcome"] == "PASS"
    detail = client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).json()
    assert [c["outcome"] for c in detail["completions"]] == ["FAIL", "PASS"]


def test_poor_gps_accuracy_is_inconclusive_not_a_pass(client):
    inc, task, wh = reported_task(client)
    start(client, task["task_id"], wh)
    c = complete(client, task["task_id"], wh, device=fix(offset(SPOT, east_m=4), accuracy=90))["completion"]
    assert c["outcome"] == "REVIEW_REQUIRED" and "POOR_GPS_ACCURACY" in c["reason_codes"]
    assert c["accepted"] is True                                        # a supervisor decides
    assert [q["pending"] for q in client.get("/api/v1/verification-queue", headers=SUPERVISOR).json()] == [True]


@pytest.mark.parametrize("error", ["PERMISSION_DENIED", "TIMEOUT", "POSITION_UNAVAILABLE", "UNSUPPORTED"])
def test_no_location_means_not_checked_and_nothing_is_accepted(client, error):
    inc, task, wh = reported_task(client)
    start(client, task["task_id"], wh)
    res = complete(client, task["task_id"], wh, error=error)
    assert res["completion"]["outcome"] == "NOT_CHECKED" and res["completion"]["accepted"] is False
    assert error in res["completion"]["reason_codes"]
    assert res["task"]["status"] == "IN_PROGRESS"                       # retry allowed; no coordinates were invented


def test_missing_completion_evidence_is_refused(client):
    inc, task, wh = reported_task(client)
    start(client, task["task_id"], wh)
    r = complete(client, task["task_id"], wh, device=fix(SPOT), photo=False, expect=422)
    assert "MISSING_COMPLETION_PHOTO" in r["code"]
    r = complete(client, task["task_id"], wh, device=fix(SPOT), description="ok", expect=422)
    assert "COMPLETION_DESCRIPTION_TOO_SHORT" in r["code"]
    r = complete(client, task["task_id"], wh, expect=422)
    assert "DEVICE_LOCATION_NOT_RECORDED" in r["code"]
    assert status_of(client, inc["incident_id"]) == "IN_PROGRESS"


def test_worker_cannot_use_their_own_coordinates_as_the_target(client):
    inc, task, wh = reported_task(client)
    start(client, task["task_id"], wh)
    far = offset(SPOT, north_m=5000)
    res = client.post(f"/api/v1/tasks/{task['task_id']}/completion", headers=wh, files={"photo": ("a.jpg", pothole_scene(2), "image/jpeg")},
                      data={"payload": json.dumps({"description": "Filled the pothole properly.", "device_location": fix(far),
                                                   "target_latitude": far[0], "target_longitude": far[1]})})
    assert res.status_code == 422                                       # unknown fields are refused
    c = complete(client, task["task_id"], wh, device=fix(far))["completion"]
    assert c["outcome"] == "FAIL"                                       # still measured against the original location
    assert client.get(f"/api/v1/tasks/{task['task_id']}", headers=wh).json()["target_latitude"] == pytest.approx(SPOT[0])


def test_conflicting_photo_gps_goes_to_review(client):
    inc, task, wh = reported_task(client)
    start(client, task["task_id"], wh)
    scene = pothole_scene(7, repaired=True, gps=offset(SPOT, north_m=1500))
    c = complete(client, task["task_id"], wh, device=fix(offset(SPOT, east_m=3)), source="CAMERA_INPUT", scene=scene)["completion"]
    assert c["outcome"] == "REVIEW_REQUIRED" and "SOURCE_CONFLICT" in c["reason_codes"]


def test_gallery_completion_photo_needs_review(client):
    inc, task, wh = reported_task(client)
    start(client, task["task_id"], wh)
    c = complete(client, task["task_id"], wh, device=fix(offset(SPOT, east_m=3)), source="GALLERY")["completion"]
    assert c["outcome"] == "REVIEW_REQUIRED" and "PHOTO_LOCATION_UNVERIFIED" in c["reason_codes"]


def test_reusing_the_citizens_photo_is_flagged(client):
    inc, task, wh = reported_task(client)
    start(client, task["task_id"], wh)
    c = complete(client, task["task_id"], wh, device=fix(SPOT), scene=pothole_scene(10))["completion"]   # same bytes as the report photo
    assert "DUPLICATE_PHOTO" in c["reason_codes"] and c["outcome"] == "REVIEW_REQUIRED"


def test_client_distance_is_never_trusted(client):
    inc, task, wh = reported_task(client)
    start(client, task["task_id"], wh)
    r = client.post(f"/api/v1/tasks/{task['task_id']}/completion", headers=wh, files={"photo": ("a.jpg", pothole_scene(2), "image/jpeg")},
                    data={"payload": json.dumps({"description": "Filled the pothole properly.", "device_location": fix(offset(SPOT, east_m=90)),
                                                 "distance_m": 1})})
    assert r.status_code == 422


def test_simulated_location_is_never_real_evidence(client, tmp_path):
    inc, task, wh = reported_task(client)
    start(client, task["task_id"], wh)
    c = complete(client, task["task_id"], wh, device=fix(offset(SPOT, east_m=3), mode="SIMULATED"))["completion"]
    assert c["simulated"] is True and c["outcome"] == "REVIEW_REQUIRED"         # test env: simulation cannot pass
    # development mode allows a labelled demo PASS; production refuses simulation outright
    with TestClient(create_app(make_settings(tmp_path / "dev", app_env="development"))) as dev:
        i2, t2, w2 = reported_task(dev)
        start(dev, t2["task_id"], w2)
        c2 = complete(dev, t2["task_id"], w2, device=fix(offset(SPOT, east_m=3), mode="SIMULATED"))["completion"]
        assert c2["outcome"] == "PASS" and "SIMULATED" in c2["message"]
    with TestClient(create_app(make_settings(tmp_path / "prod", app_env="production", auth_mode="token",
                                             auth_tokens="a-long-test-token-1234:CIT-DEMO-01", seed_demo_data=False))) as prod:
        assert prod.get("/api/v1/config").json()["simulation_allowed"] is False


# ======================================================== supervisor
def awaiting(client, outcome_point):
    inc, task, wh = reported_task(client)
    start(client, task["task_id"], wh)
    c = complete(client, task["task_id"], wh, device=fix(outcome_point))["completion"]
    return inc, task, wh, c


def test_supervisor_approves_a_pass_and_the_incident_resolves(client):
    inc, task, wh, c = awaiting(client, offset(SPOT, east_m=4))
    assert c["outcome"] == "PASS"
    done = review(client, c["completion_id"], "APPROVE")           # no reason needed for a clean pass
    assert done["review_decision"] == "APPROVE"
    assert status_of(client, inc["incident_id"]) == "RESOLVED"
    assert client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=CITIZEN).json()["status"] == "RESOLVED"
    review(client, c["completion_id"], "APPROVE", expect=409)      # decided once


def test_approving_an_unverified_result_is_an_override_that_needs_a_reason(client):
    inc, task, wh, c = awaiting(client, offset(SPOT, east_m=4))
    start_review = client.post(f"/api/v1/tasks/{task['task_id']}/start", headers=wh)   # no-op
    inc2, task2, wh2 = reported_task(client)
    start(client, task2["task_id"], wh2)
    weak = complete(client, task2["task_id"], wh2, device=fix(offset(SPOT, east_m=4), accuracy=90))["completion"]
    assert weak["outcome"] == "REVIEW_REQUIRED"
    review(client, weak["completion_id"], "APPROVE", expect=422)
    review(client, weak["completion_id"], "APPROVE", "Called the worker; photo clearly shows the repair.")
    events = client.get(f"/api/v1/evidence-history?incident_id={inc2['incident_id']}", headers=SUPERVISOR).json()["events"]
    decision = next(e for e in events if e["action"] == "SUPERVISOR_DECISION")
    assert decision["details"]["override"] is True and decision["details"]["automated_outcome"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("decision", ["REJECT", "REQUEST_EVIDENCE"])
def test_rejecting_sends_the_job_back_for_rework(client, decision):
    inc, task, wh, c = awaiting(client, offset(SPOT, east_m=4))
    review(client, c["completion_id"], decision, expect=422)       # a reason is required
    review(client, c["completion_id"], decision, "The photo shows a different pothole.")
    assert status_of(client, inc["incident_id"]) == "ASSIGNED"
    t = client.get(f"/api/v1/tasks/{task['task_id']}", headers=wh).json()
    assert t["attempt"] == 2 and t["rework_reason"] == "The photo shows a different pothole."
    start(client, task["task_id"], wh)
    again = complete(client, task["task_id"], wh, device=fix(SPOT), scene=pothole_scene(55, repaired=True))["completion"]
    assert again["outcome"] == "PASS" and again["attempt"] == 2


def test_status_transitions_follow_the_lifecycle(client):
    inc, task, wh = reported_task(client)
    seen = [inc["status"]]
    start(client, task["task_id"], wh)
    seen.append(status_of(client, inc["incident_id"]))
    c = complete(client, task["task_id"], wh, device=fix(SPOT))["completion"]
    seen.append(status_of(client, inc["incident_id"]))
    review(client, c["completion_id"], "APPROVE")
    seen.append(status_of(client, inc["incident_id"]))
    assert seen == ["ASSIGNED", "IN_PROGRESS", "AWAITING_VERIFICATION", "RESOLVED"]
    complete(client, task["task_id"], wh, device=fix(SPOT), expect=409)       # nothing more can be submitted
    timeline = [e["details"]["to_status"] for e in client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).json()["timeline"]
                if e["action"] == "STATUS_CHANGED"]
    assert timeline == ["ASSIGNED", "IN_PROGRESS", "AWAITING_VERIFICATION", "RESOLVED"]


def test_cannot_submit_before_starting(client):
    inc, task, wh = reported_task(client)
    complete(client, task["task_id"], wh, device=fix(SPOT), expect=409)


# ======================================================= access & settings
def test_the_app_opens_without_a_token_and_roles_are_still_enforced(client):
    assert client.get("/api/v1/config").json()["auth_mode"] == "demo"
    assert {u["role"] for u in client.get("/api/v1/demo/users").json()} == {"CITIZEN", "WORKER", "SUPERVISOR"}
    assert client.get("/api/v1/me").status_code == 401
    assert client.get("/api/v1/verification-queue", headers=WORKER12).status_code == 403
    assert client.get("/api/v1/tasks", headers=CITIZEN).status_code == 403
    assert client.post("/api/v1/incidents", headers=SUPERVISOR, data={"payload": "{}"}).status_code == 403


def test_evidence_access_is_limited(client):
    inc = report(client, device=fix(SPOT))
    url = inc["photos"][0]["url"]
    worker = {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
    other = WORKER15 if inc["task"]["worker_id"] == "W-DEMO-12" else WORKER12
    assert client.get(url, headers=CITIZEN).status_code == 200
    assert client.get(url, headers=worker).status_code == 200
    assert client.get(url, headers=SUPERVISOR).status_code == 200
    assert client.get(url, headers=CITIZEN2).status_code == 404
    assert client.get(url, headers=other).status_code == 404
    assert client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=other).status_code == 404
    assert client.get("/api/v1/evidence-history", headers=CITIZEN).status_code == 403
    exact = client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=CITIZEN).json()
    assert "completions" not in exact and "reporter_name" in exact


def test_geofence_is_configurable_within_range_and_audited(client):
    inc, task, wh = reported_task(client)
    start(client, task["task_id"], wh)
    point = offset(SPOT, east_m=19)
    assert complete(client, task["task_id"], wh, device=fix(point, accuracy=3))["completion"]["outcome"] != "PASS"   # radius 15
    assert client.put("/api/v1/settings", headers=WORKER12, json={"geofence_radius_m": 20, "max_accuracy_m": 25}).status_code == 403
    for bad in (5, 25, 21):
        assert client.put("/api/v1/settings", headers=SUPERVISOR, json={"geofence_radius_m": bad, "max_accuracy_m": 25}).status_code == 422
    assert client.put("/api/v1/settings", headers=SUPERVISOR, json={"geofence_radius_m": 20, "max_accuracy_m": 25}).json()["geofence_radius_m"] == 20
    assert complete(client, task["task_id"], wh, device=fix(point, accuracy=3), scene=pothole_scene(77, repaired=True))["completion"]["outcome"] == "PASS"
    assert client.get("/api/v1/config", headers=CITIZEN).json()["limits"]["geofence_radius_m"] == 20


def test_citizen_status_and_my_reports(client):
    a = report(client, device=fix(SPOT))
    report(client, device=fix(SPOT), headers=CITIZEN2)
    mine = client.get("/api/v1/incidents", headers=CITIZEN).json()
    assert a["incident_id"] in [i["incident_id"] for i in mine] and all(i["status_text"] for i in mine)
    assert all(i["incident_id"] != "x" for i in mine)
    detail = client.get(f"/api/v1/incidents/{a['incident_id']}", headers=CITIZEN).json()
    assert detail["status"] == "ASSIGNED" and [e["details"]["to_status"] for e in detail["timeline"] if e["action"] == "STATUS_CHANGED"] == ["ASSIGNED"]


def test_demo_mode_is_refused_in_production(tmp_path):
    with pytest.raises(RuntimeError, match="not allowed"):
        create_app(make_settings(tmp_path, app_env="production"))


def test_token_mode(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, auth_mode="token", auth_tokens="a-long-test-token-1234:SUP-DEMO-03"))) as c:
        assert c.get("/api/v1/me", headers=SUPERVISOR).status_code == 401
        assert c.get("/api/v1/me", headers={"Authorization": "Bearer a-long-test-token-1234"}).json()["role"] == "SUPERVISOR"
        assert c.get("/api/v1/demo/users").status_code == 404


def test_frontend_is_served_with_no_login_page(client):
    page = client.get("/")
    assert page.status_code == 200 and "GeoSatya" in page.text and "access token" not in page.text.lower()
    assert client.get("/js/app.js").status_code == 200


def test_demo_data_is_labelled(client):
    seeded = [i for i in client.get("/api/v1/incidents", headers=SUPERVISOR).json() if i["is_demo"]]
    assert seeded and seeded[0]["status"] == "ASSIGNED"
    loc = client.get(f"/api/v1/incidents/{seeded[0]['incident_id']}", headers=SUPERVISOR).json()["location"]
    assert loc["mode"] == "SIMULATED" and "SIMULATED_LOCATION" in loc["flags"]
    assert client.post("/api/v1/demo/reset", headers=WORKER12).status_code == 403
    assert client.post("/api/v1/demo/reset", headers=SUPERVISOR).status_code == 200
