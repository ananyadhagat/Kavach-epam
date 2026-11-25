"""The team's Verification agent (MrBadDrip), run in-process on GeoSatya's
real completion photos and device fixes. Advisory only."""

import pytest
from fastapi.testclient import TestClient

from geosatya.kavach.seed import CITY
from geosatya.main import create_app
from tests.conftest import complaint_post, CITIZEN, SPOT, SUPERVISOR, complete, fix, make_settings, offset, report

K = "/api/v1/kavach"
ORG_ADMIN = {"X-GeoSatya-Demo-User": "ORG-DEMO-01"}


@pytest.fixture
def c(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        assert client.app.state.verifier is not None, "Verification agent should load (OpenCV installed)"
        yield client


def finish(c, inc, device):
    w = {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
    c.post(f"/api/v1/tasks/{inc['task']['task_id']}/start", headers=w)
    return complete(c, inc["task"]["task_id"], w, device=device)


def verification(c, incident_id, headers=SUPERVISOR):
    a = c.get(f"{K}/incidents/{incident_id}/agents", headers=headers).json()["agents"]
    return next(x for x in a if x["agent"] == "VERIFICATION")


def test_runs_on_the_real_completion_photo_and_gps_without_changing_geosatya(c):
    inc = report(c, device=fix(SPOT))
    res = finish(c, inc, fix(offset(SPOT, east_m=3)))
    assert res["completion"]["outcome"] == "PASS"                         # GeoSatya's own verdict
    v = verification(c, inc["incident_id"])
    s = v["summary"]
    assert v["status"] == "COMPLETED" and s["completion_id"] == res["completion"]["completion_id"]
    assert s["before_photos"] == 1 and s["after_photos"] == 1 and s["gps_passed_on"] is True
    assert any("within 15 m" in r for r in s["remarks"])                 # the agent's own GPS check, on GeoSatya's radius
    # Offline vision invents nothing: no visual score, so no PASS from the agent.
    assert s["verification_status"] in ("INCONCLUSIVE", "MANUAL_REVIEW") and s["score"] is None
    assert "ANALYSIS_UNAVAILABLE" in s["reason_codes"]
    assert c.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).json()["status"] == "AWAITING_VERIFICATION"


def test_a_far_away_completion_is_flagged_by_the_agent_too(c):
    inc = report(c, device=fix(SPOT))
    finish(c, inc, fix(offset(SPOT, east_m=400)))
    s = verification(c, inc["incident_id"])["summary"]
    assert s["verification_status"] != "PASS"
    assert any("beyond the 15 m tolerance" in r for r in s["remarks"]), s["remarks"]


def test_a_simulated_fix_is_not_passed_on_as_gps(c):
    inc = report(c, device=fix(SPOT))
    finish(c, inc, fix(offset(SPOT, east_m=2), mode="SIMULATED"))
    s = verification(c, inc["incident_id"])["summary"]
    assert s["gps_passed_on"] is False
    assert any("No usable GPS" in r for r in s["remarks"])


def test_public_complaint_photo_is_used_as_the_before_photo(c):
    """Complaints now always carry a camera photo; the Verification agent uses it as the before photo."""
    w = {"X-GeoSatya-Demo-User": "OW-DEMO-21"}
    c.post("/api/v1/workers/me/check-in", json={"available": True, "location": fix(offset(CITY, east_m=50))}, headers=w)
    body = {"category": "road_damage", "title": "Pothole", "description": "A deep pothole on the main road.", "device_location": fix(CITY)}
    inc = complaint_post(c, body, headers=CITIZEN).json()
    assert inc["task"]["worker_id"] == "OW-DEMO-21"
    c.post(f"/api/v1/tasks/{inc['task']['task_id']}/start", headers=w)
    complete(c, inc["task"]["task_id"], w, device=fix(offset(CITY, east_m=2)))
    s = verification(c, inc["incident_id"], ORG_ADMIN)["summary"]
    assert s["before_photos"] == 1


def test_sanitation_plan_tasks_become_the_requirements(c):
    from geosatya.models import IncidentRow
    from geosatya.platform_models import AgentRunRow
    from geosatya.timeutil import utcnow
    inc = report(c, device=fix(SPOT), category="garbage", title="Garbage pile", description="Garbage pile near the gate.")
    with c.app.state.session_factory() as s:
        row = s.get(AgentRunRow, (inc["incident_id"], "SANITATION"))
        if row is None:
            row = AgentRunRow(incident_id=inc["incident_id"], agent="SANITATION", attempts=1)
            s.add(row)
        row.status, row.updated_at = "COMPLETED", utcnow()
        row.result = {"tasks": [{"task_code": "INSPECT_AREA", "title": "Inspect garbage pile"}, {"task_code": "REMOVE_WASTE", "title": "Load and contain garbage pile"}]}
        s.commit()
    finish(c, inc, fix(offset(SPOT, east_m=2)))
    with c.app.state.session_factory() as s:
        req = s.get(AgentRunRow, (inc["incident_id"], "VERIFICATION")).request
    assert req["requirements"] == ["Inspect garbage pile", "Load and contain garbage pile"]


def test_an_agent_failure_never_affects_the_completion(c, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("vision crashed")
    monkeypatch.setattr(c.app.state.verifier, "verify", boom)
    inc = report(c, device=fix(SPOT))
    res = finish(c, inc, fix(offset(SPOT, east_m=3)))
    assert res["completion"]["outcome"] == "PASS"
    v = verification(c, inc["incident_id"])
    assert v["status"] == "FAILED" and "vision crashed" in v["error"]


def test_retry_runs_verification_again(c, monkeypatch):
    inc = report(c, device=fix(SPOT))
    original = c.app.state.verifier.verify
    monkeypatch.setattr(c.app.state.verifier, "verify", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    finish(c, inc, fix(offset(SPOT, east_m=3)))
    assert verification(c, inc["incident_id"])["status"] == "FAILED"
    monkeypatch.setattr(c.app.state.verifier, "verify", original)
    r = c.post(f"{K}/incidents/{inc['incident_id']}/agents/retry", headers=SUPERVISOR).json()
    assert next(a for a in r["agents"] if a["agent"] == "VERIFICATION")["status"] == "COMPLETED"


def test_switched_off_means_not_configured(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, verification_agent="off"))) as c2:
        inc = report(c2, device=fix(SPOT))
        res = finish(c2, inc, fix(offset(SPOT, east_m=3)))
        assert res["completion"]["outcome"] == "PASS"
        assert verification(c2, inc["incident_id"])["status"] == "NOT_CONFIGURED"


# ------------------------------------------------ before photo and checklist
import json as _json

from geosatya.synthetic_images import pothole_scene


def start_job(c, inc):
    w = {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
    c.post(f"/api/v1/tasks/{inc['task']['task_id']}/start", headers=w)
    return inc["task"]["task_id"], w


def before(c, task_id, w, expect=201, key=None):
    payload = {"photo_meta": {"capture_source": "GALLERY", "uploaded_at": "2026-11-15T10:00:00+00:00"}, "device_location": fix(SPOT)}
    r = c.post(f"{K}/tasks/{task_id}/before-photo", data={"payload": _json.dumps(payload)},
               files={"photo": ("b.jpg", pothole_scene(31), "image/jpeg")}, headers={**w, **({"Idempotency-Key": key} if key else {})})
    assert r.status_code == expect, r.text
    return r.json()


def test_worker_before_photo_and_ticked_steps_reach_the_verification_agent(c):
    inc = report(c, device=fix(SPOT))
    tid, w = start_job(c, inc)
    wc = c.get(f"{K}/tasks/{tid}/work-check", headers=w).json()
    assert wc["steps_source"] == "CATEGORY" and len(wc["steps"]) == 3 and wc["before_photo"] is None
    wc = before(c, tid, w)
    assert wc["before_photo"]["media_id"]
    ids = [s["id"] for s in wc["steps"]]
    wc = c.post(f"{K}/tasks/{tid}/checklist", json={"completed": ids[:2]}, headers=w).json()
    assert [s["done"] for s in wc["steps"]] == [True, True, False]
    complete(c, tid, w, device=fix(offset(SPOT, east_m=3)))
    s = verification(c, inc["incident_id"])["summary"]
    with c.app.state.session_factory() as db:
        from geosatya.platform_models import AgentRunRow
        req = db.get(AgentRunRow, (inc["incident_id"], "VERIFICATION")).request
    assert req["before_source"] == "WORKER" and req["steps_ticked"] == 2 and req["steps_total"] == 3
    # Ticked steps are now claimed; the unticked one stays unknown rather than failed.
    # Ticks are claims; without vision confirming them they stay unconfirmed, never "supported".
    assert any("ROAD_DAMAGE-01" in r for r in s["remarks"]) and not any("STEP-0" in r for r in s["remarks"])
    assert s["failed_requirements"] == []


def test_checklist_rules(c):
    inc = report(c, device=fix(SPOT))
    tid, w = start_job(c, inc)
    assert c.post(f"{K}/tasks/{tid}/checklist", json={"completed": ["ROAD_DAMAGE-99"]}, headers=w).status_code == 422
    assert c.post(f"{K}/tasks/{tid}/checklist", json={"completed": []}, headers=CITIZEN).status_code == 403
    other = {"X-GeoSatya-Demo-User": "W-DEMO-15" if inc["task"]["worker_id"] == "W-DEMO-12" else "W-DEMO-12"}
    assert c.post(f"{K}/tasks/{tid}/checklist", json={"completed": []}, headers=other).status_code == 404
    assert c.get(f"{K}/tasks/{tid}/work-check", headers=SUPERVISOR).status_code == 200      # supervisors can read it
    complete(c, tid, w, device=fix(offset(SPOT, east_m=3)))
    assert c.post(f"{K}/tasks/{tid}/checklist", json={"completed": ["ROAD_DAMAGE-01"]}, headers=w).status_code == 409   # locked once submitted


def test_before_photo_rules_and_offline_resend(c):
    inc = report(c, device=fix(SPOT))
    tid, w = start_job(c, inc)
    first = before(c, tid, w, key="k-1")
    again = before(c, tid, w, key="k-1")                      # the phone re-sent it after a dropped connection
    assert again["before_photo"]["media_id"] == first["before_photo"]["media_id"]
    before(c, tid, SUPERVISOR, expect=403)
    with c.app.state.session_factory() as db:
        from geosatya.models import EvidenceRow
        rows = db.query(EvidenceRow).filter(EvidenceRow.media_id == first["before_photo"]["media_id"]).all()
    assert {r.source_type for r in rows} == {"IMAGE_EXIF", "DEVICE_GEOLOCATION"}   # recorded like every GeoSatya photo


def test_completion_still_works_without_before_photo_or_checklist(c):
    inc = report(c, device=fix(SPOT))
    tid, w = start_job(c, inc)
    assert complete(c, tid, w, device=fix(offset(SPOT, east_m=3)))["completion"]["outcome"] == "PASS"


def test_category_steps_never_borrow_the_agents_built_in_waste_meanings(c):
    from geosatya.kavach.agents import requirements_for
    from geosatya.models import IncidentRow
    inc = report(c, device=fix(SPOT))
    with c.app.state.session_factory() as db:
        reqs = requirements_for(db, c.app.state.categories, db.get(IncidentRow, inc["incident_id"]))
    assert all(r["requirement_id"].startswith("ROAD_DAMAGE-") and r["target_observation"] is None for r in reqs)
