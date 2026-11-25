"""Server side of the installable worker app: offline re-sends are filed once,
positions sent late keep their real age, and the app files are served."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from geosatya.main import create_app
from geosatya.models import CompletionRow, ProgressUpdateRow, WorkerProfileRow
from geosatya.synthetic_images import pothole_scene
from tests.conftest import CITIZEN, SPOT, SUPERVISOR, fix, iso, make_settings, offset, report
from tests.test_integration import tracking


@pytest.fixture
def c(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, tracking_min_interval_s=0))) as client:
        yield client


def started(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
    assert c.post(f"/api/v1/tasks/{tid}/start", headers=w).status_code == 200
    return inc, tid, w


def send_completion(c, tid, w, key, point, observed=2):
    payload = {"description": "Filled and compacted the pothole.", "device_location": fix(point, observed=observed),
               "photo_meta": {"capture_source": "CAMERA_LIVE", "captured_at": iso(observed + 1), "uploaded_at": iso(0)}}
    return c.post(f"/api/v1/tasks/{tid}/completion", data={"payload": json.dumps(payload)},
                  files={"photo": ("done.jpg", pothole_scene(77, repaired=True), "image/jpeg")},
                  headers={**w, **({"Idempotency-Key": key} if key else {})})


def test_a_resent_completion_is_filed_once_and_returns_the_first_result(c):
    inc, tid, w = started(c)
    first = send_completion(c, tid, w, "phone-key-1", offset(SPOT, east_m=3))
    again = send_completion(c, tid, w, "phone-key-1", offset(SPOT, east_m=3))
    assert first.status_code == again.status_code == 200
    assert again.json()["replayed"] is True
    assert again.json()["completion"]["completion_id"] == first.json()["completion"]["completion_id"]
    with c.app.state.session_factory() as s:
        assert s.scalar(select(func.count()).select_from(CompletionRow).where(CompletionRow.task_id == tid)) == 1


def test_a_resent_failed_completion_is_not_filed_twice_either(c):
    inc, tid, w = started(c)
    far = offset(SPOT, north_m=60)
    first = send_completion(c, tid, w, "phone-key-2", far).json()["completion"]
    again = send_completion(c, tid, w, "phone-key-2", far).json()["completion"]
    assert first["outcome"] == again["outcome"] == "FAIL" and first["completion_id"] == again["completion_id"]
    # A new attempt (new key) is a real new submission.
    third = send_completion(c, tid, w, "phone-key-3", offset(SPOT, east_m=3)).json()["completion"]
    assert third["completion_id"] != first["completion_id"] and third["outcome"] == "PASS"


def test_a_completion_saved_offline_is_still_checked_against_the_incident(c):
    inc, tid, w = started(c)
    # Saved offline 20 minutes ago at the spot: the location is still checked against the incident.
    r = send_completion(c, tid, w, "k", offset(SPOT, east_m=3), observed=1200).json()["completion"]
    assert r["outcome"] in ("PASS", "REVIEW_REQUIRED")


def test_a_resent_progress_note_is_saved_once(c):
    inc, tid, w = started(c)
    for _ in range(2):
        r = c.post(f"/api/v1/tasks/{tid}/progress", headers={**w, "Idempotency-Key": "note-1"},
                   json={"note": "Filling the pothole now", "estimate_minutes": 20})
        assert r.status_code == 200
    with c.app.state.session_factory() as s:
        assert s.scalar(select(func.count()).select_from(ProgressUpdateRow).where(ProgressUpdateRow.task_id == tid)) == 1


def test_a_position_sent_late_shows_its_real_age(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
    # Taken 10 minutes ago without signal, sent now.
    late = fix(offset(SPOT, north_m=600), observed=600)
    assert c.post(f"/api/v1/tasks/{tid}/location", headers=w, json=late).json()["stored"] is True
    t = tracking(c, inc["incident_id"], CITIZEN)
    assert t["state"] == "STALE" and t["latest"]["kind"] == "LAST_KNOWN" and t["latest"]["age_s"] >= 590
    assert t["eta"]["state"] == "STALE"
    with c.app.state.session_factory() as s:     # dispatch sees the real age too
        prof = s.get(WorkerProfileRow, inc["task"]["worker_id"])
        assert prof.last_received_at is not None
    live = next(x for x in c.get("/api/v1/dashboard/live", headers=SUPERVISOR).json()["workers"]
                if x["worker_id"] == inc["task"]["worker_id"])
    assert live["location_state"] == "STALE" and live["location_age_s"] >= 590


def test_a_device_clock_in_the_future_cannot_make_a_position_fresher(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
    future = fix(offset(SPOT, north_m=600), observed=-3600)     # device says "an hour from now"
    c.post(f"/api/v1/tasks/{tid}/location", headers=w, json=future)
    t = tracking(c, inc["incident_id"], SUPERVISOR)
    assert t["state"] == "LIVE" and 0 <= t["latest"]["age_s"] < 60


def test_app_files_are_served_for_install(c):
    m = c.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.headers["content-type"].startswith("application/manifest+json")
    manifest = m.json()
    assert manifest["display"] == "standalone" and manifest["start_url"] == "/#/tasks"
    assert any(i.get("purpose") == "maskable" for i in manifest["icons"])
    for icon in manifest["icons"]:
        r = c.get("/" + icon["src"])
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    sw = c.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"] and sw.headers["cache-control"] == "no-cache"
    assert '"/api/"' in sw.text                                  # the service worker never caches API data
    page = c.get("/").text
    assert 'rel="manifest"' in page and "apple-touch-icon" in page
