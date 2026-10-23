"""Shared fixtures: each test gets its own SQLite file, photo folder and demo
data. No test needs live GPS, a browser, an API key or a database server."""

import json
import math
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from geosatya.config import Settings
from geosatya.main import create_app
from geosatya.seed import DEMO_POINT
from geosatya.synthetic_images import pothole_scene

CITIZEN = {"X-GeoSatya-Demo-User": "CIT-DEMO-01"}
CITIZEN2 = {"X-GeoSatya-Demo-User": "CIT-DEMO-02"}
WORKER12 = {"X-GeoSatya-Demo-User": "W-DEMO-12"}
WORKER15 = {"X-GeoSatya-Demo-User": "W-DEMO-15"}
SUPERVISOR = {"X-GeoSatya-Demo-User": "SUP-DEMO-03"}

SPOT = (23.250000, 77.380000)  # a synthetic incident location


def offset(point, north_m=0.0, east_m=0.0):
    lat, lon = point
    return (lat + north_m / 111_320.0, lon + east_m / (111_320.0 * math.cos(math.radians(lat))))


def iso(seconds_ago=0):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def make_settings(tmp_path, **overrides):
    values = dict(app_env="test", database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
                  storage_dir=tmp_path / "uploads", _env_file=None)
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as c:
        yield c


def fix(point, accuracy=8.0, mode="LIVE", observed=1):
    return {"latitude": point[0], "longitude": point[1], "accuracy_m": accuracy, "observed_at": iso(observed), "mode": mode}


def report(client, *, device=None, error=None, pin=None, photos=1, source="CAMERA_LIVE", scene=None, headers=CITIZEN,
           expect=201, category="road_damage", **extra):
    payload = {"category": category, "title": extra.pop("title", "Pothole near the crossing"),
               "description": extra.pop("description", "A deep pothole in the left lane."),
               "device_location": device, "device_location_error": error, "user_location": pin,
               "photos_meta": [{"capture_source": source, "captured_at": iso(2) if source == "CAMERA_LIVE" else None,
                                "uploaded_at": iso(0)} for _ in range(photos)], **extra}
    files = [("photos", (f"p{i}.jpg", scene or pothole_scene(10 + i), "image/jpeg")) for i in range(photos)]
    r = client.post("/api/v1/incidents", data={"payload": json.dumps(payload)}, files=files or None, headers=headers)
    assert r.status_code == expect, r.text
    return r.json()


def reported_task(client, point=SPOT, worker_headers=None):
    """A reported pothole at `point`, its auto-created task id, and the worker it went to."""
    inc = report(client, device=fix(point))
    task = inc["task"]
    headers = worker_headers or {"X-GeoSatya-Demo-User": task["worker_id"]}
    return inc, task, headers


def start(client, task_id, headers):
    r = client.post(f"/api/v1/tasks/{task_id}/start", headers=headers)
    assert r.status_code == 200, r.text


def complete(client, task_id, headers, *, device=None, error=None, photo=True, source="CAMERA_LIVE", scene=None,
             description="Filled and compacted the pothole.", expect=200):
    payload = {"description": description, "device_location": device, "device_location_error": error,
               "photo_meta": {"capture_source": source, "captured_at": iso(2) if source == "CAMERA_LIVE" else None,
                              "uploaded_at": iso(0)}}
    files = {"photo": ("done.jpg", scene or pothole_scene(99, repaired=True), "image/jpeg")} if photo else None
    r = client.post(f"/api/v1/tasks/{task_id}/completion", data={"payload": json.dumps(payload)}, files=files, headers=headers)
    assert r.status_code == expect, r.text
    return r.json()


def review(client, completion_id, decision, reason="", expect=200):
    r = client.post(f"/api/v1/completions/{completion_id}/review", json={"decision": decision, "reason": reason}, headers=SUPERVISOR)
    assert r.status_code == expect, r.text
    return r.json()


def status_of(client, incident_id):
    return client.get(f"/api/v1/incidents/{incident_id}", headers=SUPERVISOR).json()["status"]


__all__ = ["CITIZEN", "CITIZEN2", "WORKER12", "WORKER15", "SUPERVISOR", "SPOT", "DEMO_POINT", "offset", "iso", "make_settings",
           "fix", "report", "reported_task", "start", "complete", "review", "status_of"]
