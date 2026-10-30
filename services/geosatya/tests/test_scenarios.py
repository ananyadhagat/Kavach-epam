"""End-to-end civic incident journeys (scenarios A–J of the integration brief),
plus acceptance, decline, timeout, cancellation, stationary workers, the
supervisor board, the citizen timeline and the additive column migration."""

import sqlite3
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from geosatya.main import create_app
from geosatya.models import LocationPingRow, TaskProgressRow, TaskRow
from tests.conftest import CITIZEN, SPOT, SUPERVISOR, WORKER12, WORKER15, complete, fix, make_settings, offset, report, review
from tests.test_integration import FakeAgent, agent_record, age_pings, check_in, ping, tracking, use_agent


@pytest.fixture
def c(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, tracking_min_interval_s=0))) as client:
        yield client


def H(worker_id):
    return {"X-GeoSatya-Demo-User": worker_id}


def detail(c, iid, headers=SUPERVISOR):
    r = c.get(f"/api/v1/incidents/{iid}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def events(c, iid, headers=CITIZEN):
    return [e["event"] for e in detail(c, iid, headers)["progress"]["events"]]


def post(c, path, headers, json=None, expect=200):
    r = c.post(f"/api/v1{path}", headers=headers, json=json)
    assert r.status_code == expect, r.text
    return r.json()


def board_row(c, iid):
    return next(r for r in post_get(c, "/dispatch/board")["incidents"] if r["incident_id"] == iid)


def post_get(c, path):
    r = c.get(f"/api/v1{path}", headers=SUPERVISOR)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ A
def test_scenario_a_successful_resolution(c):
    use_agent(c, FakeAgent(httpx.Response(201, json=agent_record("HIGH"))))
    check_in(c, WORKER15, offset(SPOT, north_m=800))
    check_in(c, WORKER12, offset(SPOT, north_m=1900))
    inc = report(c, device=fix(SPOT))
    iid, tid, w = inc["incident_id"], inc["task"]["task_id"], H(inc["task"]["worker_id"])
    assert inc["task"]["worker_id"] == "W-DEMO-15" and inc["progress"]["phase"] == "AWAITING_ACCEPTANCE"

    post(c, f"/tasks/{tid}/accept", w)
    assert tracking(c, iid, CITIZEN)["phase"] == "ACCEPTED"
    ping(c, tid, w, offset(SPOT, north_m=600))
    t = tracking(c, iid, CITIZEN)
    assert t["phase"] == "EN_ROUTE" and t["eta"]["state"] == "AVAILABLE" and t["latest"]["kind"] == "CURRENT"
    ping(c, tid, w, offset(SPOT, north_m=20))
    ping(c, tid, w, offset(SPOT, north_m=10))
    assert tracking(c, iid, CITIZEN)["phase"] == "ARRIVED"
    post(c, f"/tasks/{tid}/start", w)
    t = tracking(c, iid, CITIZEN)
    assert t["phase"] == "IN_PROGRESS" and t["etr"]["updated_on"] == "WORK_STARTED"
    res = complete(c, tid, w, device=fix(offset(SPOT, east_m=4)))
    assert res["completion"]["outcome"] == "PASS"
    review(c, res["completion"]["completion_id"], "APPROVE")
    d = detail(c, iid, CITIZEN)
    assert d["status"] == "RESOLVED" and d["progress"]["phase"] == "RESOLVED"
    assert d["progress"]["etr"]["state"] == "RESOLVED" and d["progress"]["etr"]["actual"]["total_min"] is not None
    assert events(c, iid) == ["REPORTED", "ANALYSED", "ASSIGNED", "ACCEPTED", "EN_ROUTE", "ARRIVED", "WORK_STARTED",
                              "EVIDENCE_SUBMITTED", "LOCATION_VERIFIED", "REVIEWED", "RESOLVED"]


# ------------------------------------------------------------------ B
def test_scenario_b_no_suitable_worker(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, dispatch_fallback="escalate"))) as c:
        inc = report(c, device=fix(SPOT))
        iid = inc["incident_id"]
        d = detail(c, iid, CITIZEN)
        assert d["status"] == "SUBMITTED" and d["progress"]["phase"] == "UNASSIGNED"
        assert d["progress"]["phase_text"] == "Finding a field worker"
        assert events(c, iid) == ["REPORTED", "ASSIGNMENT_PENDING"]
        assert d["progress"]["etr"]["state"] == "UNAVAILABLE"            # scenario I: ETR unavailable, not invented
        assert c.get(f"/api/v1/incidents/{iid}/tracking", headers=CITIZEN).status_code == 404
        assert "UNASSIGNED" in board_row(c, iid)["flags"]


# ------------------------------------------------------------------ C
def test_scenario_c_decline_redispatches_without_duplicates(c):
    inc = report(c, device=fix(SPOT))
    iid, first = inc["incident_id"], inc["task"]["worker_id"]
    other = "W-DEMO-15" if first == "W-DEMO-12" else "W-DEMO-12"
    assert post(c, f"/tasks/{inc['task']['task_id']}/decline", H(other), {"reason": "x"}, expect=404)  # not theirs
    post(c, f"/tasks/{inc['task']['task_id']}/decline", H(first), {"reason": "Vehicle in repair"})
    d = detail(c, iid)
    assert d["task"]["worker_id"] == other and d["progress"]["phase"] == "AWAITING_ACCEPTANCE"
    with c.app.state.session_factory() as s:
        assert len(s.scalars(select(TaskRow).where(TaskRow.incident_id == iid)).all()) == 1
    assert c.get(f"/api/v1/tasks/{inc['task']['task_id']}", headers=H(first)).status_code == 404
    # The second worker declines too: nobody left, so it waits for a supervisor (even in workload mode).
    post(c, f"/tasks/{d['task']['task_id']}/decline", H(other), {})
    d = detail(c, iid)
    assert d["task"] is None and d["status"] == "SUBMITTED" and d["dispatch"]["status"] == "UNASSIGNED"
    assert "already released" in d["dispatch"]["reason"]
    assert events(c, iid, CITIZEN).count("ASSIGNMENT_RELEASED") == 2
    # A supervisor can still assign it by hand.
    post(c, f"/incidents/{iid}/assign", SUPERVISOR, {"worker_id": first, "reason": "Repaired vehicle"})


def test_decline_is_refused_after_accepting(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], H(inc["task"]["worker_id"])
    post(c, f"/tasks/{tid}/accept", w)
    assert c.post(f"/api/v1/tasks/{tid}/decline", headers=w, json={}).json()["code"] == "ALREADY_ACCEPTED"


def test_acceptance_timeout_is_flagged_and_can_be_redispatched(c):
    inc = report(c, device=fix(SPOT))
    iid, tid, first = inc["incident_id"], inc["task"]["task_id"], inc["task"]["worker_id"]
    body = {"kind": "ACCEPTANCE_TIMEOUT", "reason": "No response from worker"}
    assert c.post(f"/api/v1/tasks/{tid}/release", headers=SUPERVISOR, json=body).json()["code"] == "NOT_OVERDUE"
    with c.app.state.session_factory() as s:
        t = s.get(TaskRow, tid)
        t.assigned_at = t.assigned_at - timedelta(minutes=16)
        s.commit()
    assert "ACCEPTANCE_OVERDUE" in board_row(c, iid)["flags"]
    assert c.post(f"/api/v1/tasks/{tid}/release", headers=CITIZEN, json=body).status_code == 403
    d = post(c, f"/tasks/{tid}/release", SUPERVISOR, body)
    assert d["task"]["worker_id"] != first


# ------------------------------------------------------------------ D, E
def test_scenario_d_location_unavailable(c):
    inc = report(c, device=fix(SPOT))
    post(c, f"/tasks/{inc['task']['task_id']}/accept", H(inc["task"]["worker_id"]))
    t = tracking(c, inc["incident_id"], CITIZEN)
    assert t["latest"] is None and t["eta"]["state"] == "WAITING_FOR_LOCATION" and t["eta"]["minutes_low"] is None
    assert t["state"] == "NOT_STARTED"


def test_scenario_e_stale_location_is_labelled_and_flagged(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], H(inc["task"]["worker_id"])
    ping(c, tid, w, offset(SPOT, north_m=900))
    age_pings(c, tid, 300)
    t = tracking(c, inc["incident_id"], CITIZEN)
    assert t["state"] == "STALE" and t["latest"]["kind"] == "LAST_KNOWN" and t["eta"]["state"] == "STALE"
    assert "TRACKING_STALE" in board_row(c, inc["incident_id"])["flags"]
    ping(c, tid, w, offset(SPOT, north_m=700))                      # fresh data resumes normal updates
    assert tracking(c, inc["incident_id"], CITIZEN)["state"] == "LIVE"


def test_stationary_worker_makes_eta_uncertain(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], H(inc["task"]["worker_id"])
    ping(c, tid, w, offset(SPOT, north_m=900))
    age_pings(c, tid, 200)
    ping(c, tid, w, offset(SPOT, north_m=895))
    eta = tracking(c, inc["incident_id"], SUPERVISOR)["eta"]
    assert eta["stationary"] is True and eta["uncertain"] is True and "hasn't moved closer" in eta["message"]
    assert "WORKER_STATIONARY" in board_row(c, inc["incident_id"])["flags"]


# ------------------------------------------------------------------ F
def test_scenario_f_arrival_needs_confirmed_fresh_readings(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], H(inc["task"]["worker_id"])
    old_fix = fix(offset(SPOT, north_m=10), observed=600)           # a 10-minute-old fix sent now
    assert c.post(f"/api/v1/tasks/{tid}/location", headers=w, json=old_fix).json()["arrived"] is False
    assert ping(c, tid, w, offset(SPOT, north_m=10))["arrived"] is False   # previous one doesn't count
    assert ping(c, tid, w, offset(SPOT, north_m=8))["arrived"] is True
    assert "ARRIVED" in events(c, inc["incident_id"])


# ------------------------------------------------------------------ G, H
def test_scenario_g_and_h_outside_geofence_then_review_pending(c):
    inc = report(c, device=fix(SPOT))
    iid, tid, w = inc["incident_id"], inc["task"]["task_id"], H(inc["task"]["worker_id"])
    post(c, f"/tasks/{tid}/start", w)
    bad = complete(c, tid, w, device=fix(offset(SPOT, north_m=60)))
    assert bad["completion"]["outcome"] == "FAIL" and bad["completion"]["accepted"] is False
    assert "EVIDENCE_SUBMITTED" not in events(c, iid)               # rejected attempts aren't shown as submissions
    complete(c, tid, w, device=fix(offset(SPOT, east_m=3)))
    d = detail(c, iid, CITIZEN)
    assert d["status"] == "AWAITING_VERIFICATION" and d["progress"]["phase"] == "AWAITING_REVIEW"
    assert "RESOLVED" not in events(c, iid) and d["progress"]["resolved_at"] is None
    assert "AWAITING_REVIEW" in board_row(c, iid)["flags"]


# ------------------------------------------------------------------ J
def test_scenario_j_cancel_stops_tracking_and_new_worker_starts_clean(c):
    inc = report(c, device=fix(SPOT))
    iid, tid, first = inc["incident_id"], inc["task"]["task_id"], inc["task"]["worker_id"]
    ping(c, tid, H(first), offset(SPOT, north_m=500))
    assert c.post(f"/api/v1/tasks/{tid}/release", headers=SUPERVISOR, json={"kind": "CANCELLED"}).status_code == 422
    d = post(c, f"/tasks/{tid}/release", SUPERVISOR, {"kind": "CANCELLED", "reason": "Wrong crew for this job"})
    new = d["task"]
    assert new["worker_id"] != first and new["task_id"] != tid and d["progress"]["phase"] == "AWAITING_ACCEPTANCE"
    with c.app.state.session_factory() as s:
        assert s.scalars(select(LocationPingRow).where(LocationPingRow.task_id == tid)).all() == []
        assert s.get(TaskProgressRow, tid) is None
    t = tracking(c, iid, CITIZEN)
    assert t["latest"] is None and t["eta"]["state"] == "WAITING_FOR_LOCATION"
    ping(c, tid, H(first), SPOT, expect=404)                        # the old session is invalid


def test_cancel_is_refused_once_evidence_exists(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], H(inc["task"]["worker_id"])
    post(c, f"/tasks/{tid}/start", w)
    complete(c, tid, w, device=fix(offset(SPOT, north_m=60)))      # FAIL, but recorded
    r = c.post(f"/api/v1/tasks/{tid}/release", headers=SUPERVISOR, json={"kind": "CANCELLED", "reason": "Wrong crew"})
    assert r.status_code == 409 and r.json()["code"] == "HAS_EVIDENCE"


# ---------------------------------------------------------- authorization
def test_only_the_assigned_worker_can_accept(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], inc["task"]["worker_id"]
    other = WORKER15 if w == "W-DEMO-12" else WORKER12
    assert c.post(f"/api/v1/tasks/{tid}/accept", headers=other).status_code == 404
    assert c.post(f"/api/v1/tasks/{tid}/accept", headers=CITIZEN).status_code == 403
    assert c.get("/api/v1/dispatch/board", headers=CITIZEN).status_code == 403


def test_starting_work_counts_as_accepting(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], H(inc["task"]["worker_id"])
    post(c, f"/tasks/{tid}/start", w)
    assert detail(c, inc["incident_id"])["progress"]["accepted_at"] is not None


def test_journey_started_before_acceptance_existed_is_not_overdue(c):
    """Tasks tracked before accepted_at existed: a started journey counts as accepted."""
    inc = report(c, device=fix(SPOT))
    tid = inc["task"]["task_id"]
    with c.app.state.session_factory() as s:
        t, p = s.get(TaskRow, tid), s.get(TaskProgressRow, tid)
        t.assigned_at = t.assigned_at - timedelta(minutes=60)
        p.tracking_started_at, p.accepted_at = t.assigned_at + timedelta(minutes=2), None
        s.commit()
    row = board_row(c, inc["incident_id"])
    assert row["phase"] == "EN_ROUTE" and "ACCEPTANCE_OVERDUE" not in row["flags"]


def test_board_lists_open_incidents_with_eta_and_etr(c):
    inc = report(c, device=fix(SPOT))
    row = board_row(c, inc["incident_id"])
    assert row["phase"] == "AWAITING_ACCEPTANCE" and row["worker_name"] and row["etr"]["state"] == "ESTIMATED"
    assert row["eta"]["state"] == "WAITING_FOR_LOCATION" and row["since_assigned_min"] is not None


# -------------------------------------------------------------- migration
def test_older_database_gains_new_columns_without_losing_data(tmp_path):
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as c:
        iid = report(c, device=fix(SPOT))["incident_id"]
    db = tmp_path / "test.db"
    with sqlite3.connect(db) as con:                                # simulate the previous schema
        con.execute("ALTER TABLE task_progress DROP COLUMN accepted_at")
    with TestClient(create_app(settings)) as c:
        d = detail(c, iid)
        assert d["task"] is not None and d["progress"]["accepted_at"] is None
    with sqlite3.connect(db) as con:
        assert "accepted_at" in [r[1] for r in con.execute("PRAGMA table_info(task_progress)")]
