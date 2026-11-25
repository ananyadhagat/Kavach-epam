"""Citizen complaints: camera photo + automatic GPS are required, and the server
(GeoSatya) decides the verification status. Frontend coordinates are evidence, never proof."""

import json

import pytest
from fastapi.testclient import TestClient

from geosatya.main import create_app
from geosatya.models import EvidenceRow, MediaRow
from geosatya.synthetic_images import pothole_scene
from tests.conftest import CITIZEN, CITIZEN2, SUPERVISOR, WORKER12, SPOT, complaint_post, fix, iso, make_settings, offset

K = "/api/v1/kavach"
BODY = {"category": "road_damage", "title": "Pothole at the crossing", "description": "A deep pothole in the left lane."}


@pytest.fixture
def c(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        yield client


def send(c, expect=201, device="good", **kw):
    body = dict(BODY)
    if device == "good":
        body["device_location"] = fix(SPOT)
    elif device is not None:
        body["device_location"] = device
    body.update(kw.pop("body", {}))
    r = complaint_post(c, body, **kw)
    assert r.status_code == expect, r.text
    return r.json()


# ------------------------------------------------------------- required inputs
def test_photo_is_required(c):
    out = send(c, photo=False, expect=422)
    assert out["code"] == "PHOTO_REQUIRED" and "Photograph required" in out["detail"]


def test_gps_is_required_and_a_map_pin_is_not_enough(c):
    assert send(c, device=None, expect=422)["code"] == "LOCATION_REQUIRED"
    pin_only = send(c, device=None, body={"user_location": {"latitude": SPOT[0], "longitude": SPOT[1]}}, expect=422)
    assert pin_only["code"] == "LOCATION_REQUIRED"
    both = send(c, body={"user_location": {"latitude": SPOT[0], "longitude": SPOT[1]}}, expect=422)
    assert both["code"] == "GPS_REQUIRED"


def test_gallery_photos_are_not_accepted(c):
    assert send(c, source="GALLERY", expect=422)["code"] == "CAMERA_PHOTO_REQUIRED"


def test_only_citizens_submit_complaints(c):
    assert send(c, headers=WORKER12, expect=403)
    assert send(c, headers=SUPERVISOR, expect=403)
    r = c.post(f"{K}/public/reports", data={"payload": json.dumps({**BODY, "device_location": fix(SPOT)})},
               files=[("photos", ("p.jpg", pothole_scene(1), "image/jpeg"))])
    assert r.status_code == 401


def test_a_bad_or_oversized_file_is_refused(c):
    r = c.post(f"{K}/public/reports", data={"payload": json.dumps({**BODY, "device_location": fix(SPOT),
               "photos_meta": [{"capture_source": "CAMERA_LIVE", "captured_at": iso(2)}]})},
               files=[("photos", ("p.jpg", b"not an image", "image/jpeg"))], headers=CITIZEN)
    assert r.status_code in (415, 422)


# ------------------------------------------------------------ what is stored
def test_photo_gps_and_timestamps_are_stored_together_and_privately(c):
    out = send(c)
    check = out["geosatya_check"]
    assert out["incident_id"] and out["status"] in ("SUBMITTED", "ASSIGNED")
    assert check["status"] == "LOCATION_VERIFIED" and check["reasons"] == []
    assert check["gps"]["latitude"] == pytest.approx(SPOT[0]) and check["gps"]["accuracy_m"] == 8.0
    assert check["gps"]["observed_at"] and check["photo"]["captured_at"] and check["submitted_at"]
    with c.app.state.session_factory() as s:
        media = s.query(MediaRow).filter_by(incident_id=out["incident_id"]).one()
        assert media.capture_source == "CAMERA_LIVE" and media.captured_at is not None and media.storage_key != "complaint.jpg"
        gps = s.query(EvidenceRow).filter_by(incident_id=out["incident_id"], source_type="DEVICE_GEOLOCATION").one()
        assert gps.media_id == media.media_id and gps.available and gps.mode == "LIVE"      # the fix is tied to the photo
    url = out["photos"][0]["url"]
    assert c.get(url, headers=CITIZEN).status_code == 200
    assert c.get(url, headers=CITIZEN2).status_code == 404       # another citizen cannot open it
    assert c.get(url).status_code == 401
    assert c.get(f"{K}/incidents/{out['incident_id']}/check", headers=CITIZEN).json()["status"] == "LOCATION_VERIFIED"
    assert c.get(f"{K}/incidents/{out['incident_id']}/check", headers=CITIZEN2).status_code == 404


def test_missing_exif_is_normal_and_does_not_block(c):
    check = send(c)["geosatya_check"]
    assert check["exif"]["status"] == "NO_EXIF_GPS" and check["status"] == "LOCATION_VERIFIED"


def test_exif_gps_matching_the_phone_is_reported(c):
    near = offset(SPOT, east_m=10)
    check = send(c, scene=pothole_scene(3, gps=near))["geosatya_check"]
    assert check["exif"]["status"] == "EXIF_MATCHES" and check["exif"]["distance_m"] < 20
    assert check["status"] == "LOCATION_VERIFIED"


def test_exif_gps_far_from_the_phone_needs_review(c):
    far = offset(SPOT, north_m=2000)
    out = send(c, scene=pothole_scene(3, gps=far))
    check = out["geosatya_check"]
    assert check["exif"]["status"] == "EXIF_CONFLICT" and check["status"] == "NEEDS_REVIEW"
    assert "PHOTO_GPS_CONFLICT" in [r["code"] for r in check["reasons"]] and "PHOTO_GPS_CONFLICT" in out["location"]["flags"]


# ---------------------------------------------------------- weak evidence
def test_poor_accuracy_is_never_verified(c):
    out = send(c, device=fix(SPOT, accuracy=80))
    assert out["geosatya_check"]["status"] == "NEEDS_REVIEW"
    assert "LOW_GPS_ACCURACY" in [r["code"] for r in out["geosatya_check"]["reasons"]]
    assert "LOW_GPS_ACCURACY" in out["location"]["flags"]


def test_gps_taken_long_before_the_photo_needs_review(c):
    old_fix = fix(SPOT, observed=300)          # 5 minutes before upload; photo taken 2 s ago
    check = send(c, device=old_fix)["geosatya_check"]
    assert "LOCATION_NOT_AT_PHOTO_TIME" in [r["code"] for r in check["reasons"]] and check["status"] == "NEEDS_REVIEW"


def test_stale_and_future_fixes_need_review(c):
    stale = send(c, device=fix(SPOT, observed=3600), captured_ago=3600)["geosatya_check"]
    assert "STALE_LOCATION" in [r["code"] for r in stale["reasons"]]
    future = send(c, device=fix(SPOT, observed=-600), captured_ago=-600)["geosatya_check"]
    assert "FUTURE_TIMESTAMP" in [r["code"] for r in future["reasons"]]


def test_simulated_gps_is_labelled_and_never_verified(c):
    check = send(c, device=fix(SPOT, mode="SIMULATED"))["geosatya_check"]
    assert check["status"] == "NEEDS_REVIEW" and "SIMULATED_LOCATION" in [r["code"] for r in check["reasons"]]


def test_simulated_gps_is_refused_in_production(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, app_env="production", auth_mode="token",
                                             auth_tokens="citizen-token-123456:CIT-DEMO-01", seed_demo_data=False))) as p:
        from geosatya.models import UserRow
        with p.app.state.session_factory() as s:
            if s.get(UserRow, "CIT-DEMO-01") is None:
                s.add(UserRow(user_id="CIT-DEMO-01", display_name="Asha", role="CITIZEN", is_demo=False)); s.commit()
        r = complaint_post(p, {**BODY, "device_location": fix(SPOT, mode="SIMULATED")}, headers={"Authorization": "Bearer citizen-token-123456"})
        assert r.status_code == 422 and r.json()["code"] == "SIMULATION_REFUSED"


# --------------------------------------------------------- after submission
def test_submission_runs_dispatch_and_keeps_the_geofence_rule(c):
    """GeoSatya's 15 m completion geofence is unchanged for complaints from the new flow."""
    c.post("/api/v1/workers/me/check-in", json={"available": True, "location": fix(offset(SPOT, east_m=100))}, headers=WORKER12)
    out = send(c)
    task = out["task"]
    assert task is not None
    w = {"X-GeoSatya-Demo-User": task["worker_id"]}
    assert c.post(f"/api/v1/tasks/{task['task_id']}/start", headers=w).status_code == 200
    far = {"description": "Filled the pothole and compacted it.", "device_location": fix(offset(SPOT, north_m=60)),
           "photo_meta": {"capture_source": "CAMERA_LIVE", "captured_at": iso(2), "uploaded_at": iso(0)}}
    r = c.post(f"/api/v1/tasks/{task['task_id']}/completion", data={"payload": json.dumps(far)},
               files={"photo": ("done.jpg", pothole_scene(99, repaired=True), "image/jpeg")}, headers=w)
    assert r.status_code == 200 and r.json()["completion"]["accepted"] is False      # 60 m away: outside the 15 m geofence


def test_retry_with_the_same_key_returns_the_first_complaint(c):
    first = send(c, key="retry-key-1")
    again = send(c, key="retry-key-1")
    assert again["incident_id"] == first["incident_id"]
