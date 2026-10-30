"""Live dashboard KPIs: totals, work in progress, resolved, and that the
selected worker's trail is supervisor-only."""

import pytest
from fastapi.testclient import TestClient

from geosatya.main import create_app
from tests.conftest import CITIZEN, SPOT, SUPERVISOR, complete, fix, make_settings, offset, report, review
from tests.test_integration import ping, tracking


@pytest.fixture
def c(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, seed_demo_data=False, tracking_min_interval_s=0))) as client:
        yield client


def kpis(c):
    r = c.get("/api/v1/dashboard/live", headers=SUPERVISOR)
    assert r.status_code == 200, r.text
    return r.json()["kpis"]


def test_kpis_count_reported_open_in_progress_and_resolved(c):
    a, b, d = (report(c, device=fix(offset(SPOT, east_m=200 * n))) for n in range(3))
    k = kpis(c)
    assert k["total_reported"] == 3 and k["open_incidents"] == 3 and k["work_in_progress"] == 0 and k["resolved_total"] == 0

    wb = {"X-GeoSatya-Demo-User": b["task"]["worker_id"]}
    c.post(f"/api/v1/tasks/{b['task']['task_id']}/start", headers=wb)            # b: work in progress
    wa = {"X-GeoSatya-Demo-User": a["task"]["worker_id"]}
    c.post(f"/api/v1/tasks/{a['task']['task_id']}/start", headers=wa)            # a: resolved
    res = complete(c, a["task"]["task_id"], wa, device=fix(offset(SPOT, east_m=3)))
    review(c, res["completion"]["completion_id"], "APPROVE")

    k = kpis(c)
    assert k["total_reported"] == 3 and k["resolved_total"] == 1 and k["resolved_today"] == 1
    assert k["open_incidents"] == 2 and k["work_in_progress"] == 1
    assert k["awaiting_review"] == 0


def test_worker_status_follows_the_job_they_are_travelling_to(c):
    """A worker with one job in progress who then travels to a newer job shows as travelling to the new one."""
    from sqlalchemy import select
    from geosatya.models import TaskRow
    first = report(c, device=fix(SPOT))
    w_id = first["task"]["worker_id"]
    w = {"X-GeoSatya-Demo-User": w_id}
    c.post(f"/api/v1/tasks/{first['task']['task_id']}/start", headers=w)       # first job: work in progress
    second = report(c, device=fix(offset(SPOT, east_m=900)))
    with c.app.state.session_factory() as s:                                     # make sure the same worker has both
        s.get(TaskRow, second["task"]["task_id"]).worker_id = w_id
        s.commit()
    ping(c, second["task"]["task_id"], w, offset(SPOT, east_m=400))             # now travelling to the second
    me = next(x for x in c.get("/api/v1/dashboard/live", headers=SUPERVISOR).json()["workers"] if x["worker_id"] == w_id)
    assert me["current_incident_id"] == second["incident_id"] and me["status"] == "EN_ROUTE"


def test_demo_reset_keeps_a_backup_of_the_old_data(c, tmp_path):
    import sqlite3
    report(c, device=fix(SPOT))
    report(c, device=fix(offset(SPOT, east_m=300)))
    r = c.post("/api/v1/demo/reset", headers=SUPERVISOR)
    assert r.status_code == 200 and r.json()["backup"].startswith("test-before-reset-")
    backup = tmp_path / "backups" / r.json()["backup"]
    with sqlite3.connect(backup) as db:
        assert db.execute("select count(*) from incidents").fetchone()[0] == 2     # the old data is in the backup
    assert kpis(c)["total_reported"] == 0                                          # and the live database was reset


def test_tracking_worker_card_shows_citizens_a_first_name_and_real_job_count(c):
    first = report(c, device=fix(SPOT))
    w_id, w = first["task"]["worker_id"], {"X-GeoSatya-Demo-User": first["task"]["worker_id"]}
    c.post(f"/api/v1/tasks/{first['task']['task_id']}/start", headers=w)
    res = complete(c, first["task"]["task_id"], w, device=fix(offset(SPOT, east_m=3)))
    review(c, res["completion"]["completion_id"], "APPROVE")                     # this worker now has 1 resolved job
    second = report(c, device=fix(offset(SPOT, east_m=800)))
    from sqlalchemy import select
    from geosatya.models import TaskRow
    with c.app.state.session_factory() as s:
        s.get(TaskRow, second["task"]["task_id"]).worker_id = w_id
        s.commit()
    cit = tracking(c, second["incident_id"], CITIZEN)["worker"]
    assert cit == {"first_name": cit["first_name"], "resolved_jobs": 1, "role": "Field worker"}   # no full name or id
    assert cit["first_name"] in ("Ravi", "Meena")
    sup = tracking(c, second["incident_id"], SUPERVISOR)["worker"]
    assert sup["worker_id"] == w_id and "(field worker)" in sup["name"]


def test_trail_is_for_supervisors_only(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
    for north in (900, 700, 500):
        ping(c, tid, w, offset(SPOT, north_m=north))
    sup = tracking(c, inc["incident_id"], SUPERVISOR)
    assert [round(p["distance_m"], -2) for p in sup["history"]] == [900, 700, 500]   # oldest first
    assert "history" not in tracking(c, inc["incident_id"], CITIZEN)
