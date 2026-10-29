"""Integration of Incident Intelligence, Dispatch, live tracking, ETA and ETR
with the GeoSatya workflow. The intelligence agent is replaced by an httpx
mock transport; no network, GPS or browser is needed."""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from geosatya.dispatch.ranking import dispatch_task
from geosatya.integrations.intelligence import IntelligenceClient
from geosatya.main import create_app
from geosatya.models import LocationPingRow, TaskProgressRow, TaskRow
from geosatya.services import estimates
from tests.conftest import (
    CITIZEN, CITIZEN2, SPOT, SUPERVISOR, WORKER12, WORKER15, complete, fix, make_settings, offset, report, review, start,
)


def agent_record(severity="HIGH", category="MAINTENANCE", incident_type="ROAD_DAMAGE"):
    return {"incident_id": "INC-TEST01", "request_id": "x", "incident_summary": "Deep pothole in the left lane",
            "category": category, "incident_type": incident_type, "severity_recommendation": severity,
            "severity_reason": "Safety rule(s) INJURY matched", "severity_rule_matches": ["INJURY"],
            "needs_clarification": False, "clarification_questions": [], "missing_information": [],
            "location_evidence_summary": {"check": {"status": "NOT_CHECKED"}}, "prompt_version": "p-1"}


class FakeAgent:
    """Records each call; answers with the queued responses in order."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        nxt = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def use_agent(client, agent):
    client.app.state.intelligence = IntelligenceClient("http://intel.test", 2, transport=httpx.MockTransport(agent))


def check_in(client, headers, point, available=True, accuracy=10.0):
    r = client.post("/api/v1/workers/me/check-in", headers=headers,
                    json={"available": available, "location": fix(point, accuracy=accuracy) if point else None})
    assert r.status_code == 200, r.text
    return r.json()


def ping(client, task_id, headers, point, accuracy=8.0, expect=200, mode="LIVE"):
    r = client.post(f"/api/v1/tasks/{task_id}/location", headers=headers, json=fix(point, accuracy=accuracy, mode=mode))
    assert r.status_code == expect, r.text
    return r.json()


def age_pings(client, task_id, seconds):
    with client.app.state.session_factory() as s:
        for p in s.scalars(select(LocationPingRow).where(LocationPingRow.task_id == task_id)):
            p.received_at = p.received_at - timedelta(seconds=seconds)
        s.commit()


def tracking(client, incident_id, headers):
    r = client.get(f"/api/v1/incidents/{incident_id}/tracking", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def fast_client(tmp_path):
    """Pings may be sent back to back (the normal minimum interval is 10 s)."""
    with TestClient(create_app(make_settings(tmp_path, tracking_min_interval_s=0))) as c:
        yield c


# ------------------------------------------------------------ intelligence
def test_report_is_saved_and_dispatched_when_intelligence_is_not_configured(client):
    inc = report(client, device=fix(SPOT))
    assert inc["task"]["status"] == "ASSIGNED"
    detail = client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).json()
    assert detail["intelligence"]["status"] == "NOT_CONFIGURED" and detail["intelligence"]["priority"] == "NORMAL"


def test_intelligence_output_is_stored_separately_and_sets_priority(client):
    agent = FakeAgent(httpx.Response(201, json=agent_record("HIGH")))
    use_agent(client, agent)
    inc = report(client, device=fix(SPOT), description="Someone was injured falling into this pothole.")
    sup = client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).json()
    intel = sup["intelligence"]
    assert intel["status"] == "COMPLETED" and intel["severity"] == "HIGH" and intel["priority"] == "HIGH"
    assert intel["external_incident_id"] == "INC-TEST01" and intel["severity_rule_matches"] == ["INJURY"]
    # The citizen's own words and category are untouched.
    assert sup["category"] == "road_damage" and sup["description"] == "Someone was injured falling into this pothole."
    assert sup["dispatch"]["priority"] == "HIGH"
    # The request carried the stable request id and the incident's own location.
    sent = agent.calls[0]
    assert sent.headers["X-Request-ID"] == f"geosatya-{inc['incident_id']}"
    body = sent.content.decode("latin-1")
    assert f"{SPOT[0]}" in body and "Someone was injured" in body
    # Citizens see that it ran, not the system's details.
    mine = client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=CITIZEN).json()
    assert set(mine["intelligence"]) == {"status", "priority", "source"} and "dispatch" not in mine


@pytest.mark.parametrize("failure, status", [
    (httpx.Response(503, json={"detail": {"code": "LLM_UNAVAILABLE"}}), "UNAVAILABLE"),
    (httpx.ConnectError("refused"), "UNAVAILABLE"),
    (httpx.ReadTimeout("slow"), "UNAVAILABLE"),
    (httpx.Response(502, json={"detail": {"code": "MODEL_OUTPUT_INVALID"}}), "FAILED"),
    (httpx.Response(409, json={"detail": {"code": "REQUEST_ID_REUSED"}}), "CONFLICT"),
    (httpx.Response(200, text="not json"), "FAILED"),
])
def test_unavailable_intelligence_never_loses_the_report(client, failure, status):
    use_agent(client, FakeAgent(failure))
    inc = report(client, device=fix(SPOT))
    assert inc["task"]["status"] == "ASSIGNED"            # still dispatched
    intel = client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).json()["intelligence"]
    assert intel["status"] == status and intel["priority"] == "NORMAL" and intel["attempts"] == 1


def test_intelligence_retry_uses_the_same_request_id_and_completes(client):
    agent = FakeAgent(httpx.Response(503), httpx.Response(201, json=agent_record("MEDIUM")))
    use_agent(client, agent)
    inc = report(client, device=fix(SPOT))
    r = client.post(f"/api/v1/incidents/{inc['incident_id']}/intelligence/retry", headers=SUPERVISOR)
    assert r.status_code == 200 and r.json()["status"] == "COMPLETED" and r.json()["attempts"] == 2
    assert agent.calls[0].headers["X-Request-ID"] == agent.calls[1].headers["X-Request-ID"]
    # A completed analysis is not requested again.
    client.post(f"/api/v1/incidents/{inc['incident_id']}/intelligence/retry", headers=SUPERVISOR)
    assert len(agent.calls) == 2
    assert client.post(f"/api/v1/incidents/{inc['incident_id']}/intelligence/retry", headers=CITIZEN).status_code == 403


# ---------------------------------------------------------------- dispatch
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def worker(wid, lat, lon, *, skills=("road_repair",), active=0, cap=3, available=True, age_s=60):
    return {"worker_id": wid, "name": wid, "latitude": lat, "longitude": lon, "skills": list(skills), "equipment": [],
            "available": available, "active_tasks": active, "max_active_tasks": cap,
            "location_updated_at": None if lat is None else NOW - timedelta(seconds=age_s)}


JOB = {"latitude": SPOT[0], "longitude": SPOT[1], "required_skills": ["road_repair"], "required_equipment": [],
       "max_radius_km": 2.0}


def test_ranking_rules_from_the_dispatch_agent_are_preserved():
    near, far = offset(SPOT, north_m=300), offset(SPOT, north_m=1500)
    result = dispatch_task(JOB, [
        worker("W1", *far), worker("W2", *near), worker("W3", *near, skills=("electrical",)),
        worker("W4", *near, available=False), worker("W5", *near, active=3), worker("W6", *near, age_s=1000),
        worker("W7", *offset(SPOT, north_m=5000)), worker("W8", None, None),
    ], now=NOW)
    assert [c["worker_id"] for c in result["candidates"]] == ["W2", "W1"]
    reasons = {r["worker_id"]: r["reasons"] for r in result["rejected_workers"]}
    assert reasons == {"W3": ["Required skills missing"], "W4": ["Worker unavailable"], "W5": ["Worker capacity reached"],
                       "W6": ["Location is stale"], "W7": ["Outside dispatch radius"], "W8": ["Location unavailable"]}
    # 70% distance + 30% workload, lower is better.
    w2 = result["candidates"][0]
    assert w2["score"] == pytest.approx(0.7 * w2["distance_km"] / 2.0, abs=1e-3)


def test_workload_breaks_close_distances_and_ties_are_deterministic():
    p = offset(SPOT, north_m=200)
    result = dispatch_task(JOB, [worker("WB", *p, active=2), worker("WA", *p, active=0), worker("WC", *p, active=0)], now=NOW)
    assert [c["worker_id"] for c in result["candidates"]] == ["WA", "WC", "WB"]


def test_nearest_worker_with_a_fresh_location_is_dispatched(client):
    check_in(client, WORKER12, offset(SPOT, north_m=1500))
    check_in(client, WORKER15, offset(SPOT, north_m=200))
    inc = report(client, device=fix(SPOT))
    assert inc["task"]["worker_id"] == "W-DEMO-15"
    d = client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).json()["dispatch"]
    assert d["method"] == "DISPATCH_RANKING" and [c["worker_id"] for c in d["ranking"]] == ["W-DEMO-15", "W-DEMO-12"]


def test_unavailable_worker_is_not_dispatched(client):
    check_in(client, WORKER15, offset(SPOT, north_m=100), available=False)
    check_in(client, WORKER12, offset(SPOT, north_m=900))
    inc = report(client, device=fix(SPOT))
    assert inc["task"]["worker_id"] == "W-DEMO-12"


def test_without_shared_locations_the_fallback_is_labelled(client):
    inc = report(client, device=fix(SPOT))
    d = client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).json()["dispatch"]
    assert d["method"] == "WORKLOAD_FALLBACK" and "distance not considered" in d["reason"]
    assert all("Location unavailable" in r["reasons"] for r in d["rejected"])


def test_escalate_mode_leaves_it_for_a_supervisor_and_never_duplicates(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, dispatch_fallback="escalate"))) as c:
        inc = report(c, device=fix(SPOT))
        iid = inc["incident_id"]
        assert inc["task"] is None and inc["status"] == "SUBMITTED"
        sup = c.get(f"/api/v1/incidents/{iid}", headers=SUPERVISOR).json()
        assert sup["dispatch"]["status"] == "UNASSIGNED" and sup["progress"]["etr"]["state"] == "UNAVAILABLE"
        assert c.post(f"/api/v1/incidents/{iid}/dispatch/retry", headers=SUPERVISOR).json()["task"] is None
        # A worker shares a location: retry now dispatches.
        check_in(c, WORKER12, offset(SPOT, east_m=400))
        first = c.post(f"/api/v1/incidents/{iid}/dispatch/retry", headers=SUPERVISOR).json()
        again = c.post(f"/api/v1/incidents/{iid}/dispatch/retry", headers=SUPERVISOR).json()
        assert first["task"]["task_id"] == again["task"]["task_id"]
        with c.app.state.session_factory() as s:
            assert len(s.scalars(select(TaskRow).where(TaskRow.incident_id == iid)).all()) == 1
        r = c.post(f"/api/v1/incidents/{iid}/assign", headers=SUPERVISOR, json={"worker_id": "W-DEMO-15"})
        assert r.status_code == 409


def test_supervisor_can_assign_an_escalated_incident(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, dispatch_fallback="escalate"))) as c:
        inc = report(c, device=fix(SPOT))
        bad = c.post(f"/api/v1/incidents/{inc['incident_id']}/assign", headers=SUPERVISOR, json={"worker_id": "CIT-DEMO-01"})
        assert bad.status_code == 422
        r = c.post(f"/api/v1/incidents/{inc['incident_id']}/assign", headers=SUPERVISOR,
                   json={"worker_id": "W-DEMO-15", "reason": "Closest crew today"})
        assert r.status_code == 200 and r.json()["task"]["worker_id"] == "W-DEMO-15" and r.json()["status"] == "ASSIGNED"
        assert r.json()["dispatch"]["method"] == "SUPERVISOR_MANUAL"


def test_retried_report_with_the_same_idempotency_key_is_not_filed_twice(client):
    payload = {"category": "garbage", "title": "Bin overflowing", "description": "Waste spilling on the road.",
               "device_location": fix(SPOT), "photos_meta": [{"capture_source": "GALLERY"}]}
    from geosatya.synthetic_images import pothole_scene

    def send(headers):
        return client.post("/api/v1/incidents", data={"payload": json.dumps(payload)},
                           files=[("photos", ("a.jpg", pothole_scene(3), "image/jpeg"))], headers=headers)
    first = send({**CITIZEN, "Idempotency-Key": "abc-123"})
    second = send({**CITIZEN, "Idempotency-Key": "abc-123"})
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["incident_id"] == second.json()["incident_id"]
    other = send({**CITIZEN2, "Idempotency-Key": "abc-123"})   # keys are per user
    assert other.json()["incident_id"] != first.json()["incident_id"]
    assert len(client.get("/api/v1/incidents", headers=CITIZEN).json()) == 1


# ---------------------------------------------------------------- tracking
def test_only_the_assigned_worker_can_share_and_only_while_active(fast_client):
    c = fast_client
    inc = report(c, device=fix(SPOT))
    task, me = inc["task"], {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
    other = WORKER15 if task["worker_id"] == "W-DEMO-12" else WORKER12
    assert c.post(f"/api/v1/tasks/{task['task_id']}/location", headers=other, json=fix(SPOT)).status_code == 404
    assert c.post(f"/api/v1/tasks/{task['task_id']}/location", headers=CITIZEN, json=fix(SPOT)).status_code == 403
    assert c.post(f"/api/v1/tasks/{task['task_id']}/location", headers=me,
                  json={"latitude": 95, "longitude": 0}).status_code == 422
    assert c.post(f"/api/v1/tasks/{task['task_id']}/location", headers=me,
                  content='{"latitude": NaN, "longitude": 1}', ).status_code == 422
    ping(c, task["task_id"], me, offset(SPOT, north_m=800))
    # Unrelated people cannot see the worker.
    assert c.get(f"/api/v1/incidents/{inc['incident_id']}/tracking", headers=CITIZEN2).status_code == 404
    assert c.get(f"/api/v1/tasks/{task['task_id']}/tracking", headers=other).status_code == 404
    # After the field work is over, sharing is refused.
    start(c, task["task_id"], me)
    complete(c, task["task_id"], me, device=fix(offset(SPOT, east_m=3)))
    ping(c, task["task_id"], me, SPOT, expect=409)


def test_eta_states_and_approximate_range(fast_client):
    c = fast_client
    inc = report(c, device=fix(SPOT))
    tid, me = inc["task"]["task_id"], {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
    t = tracking(c, inc["incident_id"], CITIZEN)
    assert t["state"] == "NOT_STARTED" and t["eta"]["state"] == "WAITING_FOR_LOCATION" and t["latest"] is None

    ping(c, tid, me, offset(SPOT, north_m=3000))
    t = tracking(c, inc["incident_id"], CITIZEN)
    eta = t["eta"]
    assert t["state"] == "LIVE" and eta["state"] == "AVAILABLE" and eta["speed_source"] == "ASSUMED"
    assert eta["method"] == "APPROXIMATE_STRAIGHT_LINE" and eta["uncertain"] is True
    # 3 km straight line * 1.4 road factor at 20 km/h ~= 12.6 min, shown as a range.
    assert eta["minutes_low"] <= 12.6 <= eta["minutes_high"] and eta["distance_m"] == pytest.approx(3000, abs=5)
    assert t["latest"]["kind"] == "CURRENT"

    # The worker moved 1.2 km closer in 2 minutes: observed approach speed is used.
    age_pings(c, tid, 120)
    ping(c, tid, me, offset(SPOT, north_m=1800))
    eta = tracking(c, inc["incident_id"], SUPERVISOR)["eta"]
    assert eta["speed_source"] == "OBSERVED_APPROACH"
    assert eta["minutes_high"] <= 6  # 1.8 km * 1.4 at 10 m/s ~= 4.2 min

    # No update for longer than the stale limit.
    age_pings(c, tid, 600)
    t = tracking(c, inc["incident_id"], CITIZEN)
    assert t["state"] == "STALE" and t["eta"]["state"] == "STALE" and t["latest"]["kind"] == "LAST_KNOWN"


def test_too_frequent_updates_are_not_stored(client):
    inc = report(client, device=fix(SPOT))
    tid, me = inc["task"]["task_id"], {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
    assert ping(client, tid, me, offset(SPOT, north_m=900))["stored"] is True
    again = ping(client, tid, me, offset(SPOT, north_m=850))
    assert again == {"stored": False, "reason": "TOO_FREQUENT", "min_interval_s": 10}


def test_arrival_is_detected_but_the_geofence_still_decides(fast_client):
    c = fast_client
    inc = report(c, device=fix(SPOT))
    tid, me = inc["task"]["task_id"], {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
    ping(c, tid, me, offset(SPOT, north_m=400))
    # Poor accuracy near the spot does not count as arrival.
    assert ping(c, tid, me, offset(SPOT, north_m=30), accuracy=300)["arrived"] is False
    assert ping(c, tid, me, offset(SPOT, north_m=30), accuracy=10)["arrived"] is True
    t = tracking(c, inc["incident_id"], CITIZEN)
    assert t["eta"]["state"] == "ARRIVED" and t["arrived_at"]
    start(c, tid, me)
    # "Arrived" by the 50 m arrival radius, but the work is checked against the 15 m geofence.
    res = complete(c, tid, me, device=fix(offset(SPOT, north_m=45)))
    assert res["completion"]["outcome"] == "FAIL" and res["task"]["status"] == "IN_PROGRESS"
    # The target is still the citizen's original location.
    with c.app.state.session_factory() as s:
        task = s.get(TaskRow, tid)
        assert (task.target_latitude, task.target_longitude) == pytest.approx(SPOT)


def test_citizen_sees_location_only_while_tracking_and_history_is_limited_and_purged(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, tracking_min_interval_s=0, tracking_history_keep=3))) as c:
        inc = report(c, device=fix(SPOT))
        tid, me = inc["task"]["task_id"], {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
        for north in (900, 800, 700, 600, 500):
            ping(c, tid, me, offset(SPOT, north_m=north))
        sup = tracking(c, inc["incident_id"], SUPERVISOR)
        assert [h["distance_m"] for h in sup["history"]] == pytest.approx([700, 600, 500], abs=2)
        assert "history" not in tracking(c, inc["incident_id"], CITIZEN)

        assert c.post(f"/api/v1/tasks/{tid}/tracking/stop", headers=me).status_code == 200
        cit = tracking(c, inc["incident_id"], CITIZEN)
        assert cit["state"] == "STOPPED" and cit["latest"] is None
        assert tracking(c, inc["incident_id"], SUPERVISOR)["latest"]["kind"] == "LAST_KNOWN"

        ping(c, tid, me, offset(SPOT, north_m=5))  # sharing again restarts tracking
        start(c, tid, me)
        complete(c, tid, me, device=fix(offset(SPOT, east_m=3)))
        with c.app.state.session_factory() as s:
            assert s.scalars(select(LocationPingRow).where(LocationPingRow.task_id == tid)).all() == []
        assert tracking(c, inc["incident_id"], SUPERVISOR)["state"] == "ENDED"


def test_reassignment_stops_tracking_and_moves_access(fast_client):
    c = fast_client
    inc = report(c, device=fix(SPOT))
    tid, old = inc["task"]["task_id"], inc["task"]["worker_id"]
    new = "W-DEMO-15" if old == "W-DEMO-12" else "W-DEMO-12"
    ping(c, tid, {"X-GeoSatya-Demo-User": old}, offset(SPOT, north_m=600))
    start(c, tid, {"X-GeoSatya-Demo-User": old})
    assert c.post(f"/api/v1/tasks/{tid}/reassign", headers=SUPERVISOR, json={"worker_id": new}).status_code == 422
    r = c.post(f"/api/v1/tasks/{tid}/reassign", headers=SUPERVISOR, json={"worker_id": new, "reason": "Vehicle broke down"})
    assert r.status_code == 200 and r.json()["task"]["worker_id"] == new and r.json()["status"] == "ASSIGNED"
    assert c.get(f"/api/v1/tasks/{tid}", headers={"X-GeoSatya-Demo-User": old}).status_code == 404
    t = tracking(c, inc["incident_id"], SUPERVISOR)
    assert t["latest"] is None and t["state"] == "STOPPED" and t["eta"]["state"] == "WAITING_FOR_LOCATION"
    ping(c, tid, {"X-GeoSatya-Demo-User": new}, offset(SPOT, north_m=300))


# --------------------------------------------------------------------- ETR
def test_etr_is_updated_on_events_and_resolution_time_is_from_records(fast_client):
    c = fast_client
    inc = report(c, device=fix(SPOT))
    iid, tid, me = inc["incident_id"], inc["task"]["task_id"], {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
    etr = inc["progress"]["etr"]
    # Assigned, location unknown: default travel (30) + road_damage baseline (90) + review buffer (30).
    assert etr["state"] == "ESTIMATED" and etr["approximate"] is True and etr["updated_on"] == "ASSIGNED"
    assert etr["basis"]["travel_source"] == "DEFAULT_ALLOWANCE" and etr["basis"]["work_min"] == 90
    assert 149 <= etr["remaining_min"] <= 150

    ping(c, tid, me, offset(SPOT, north_m=3000))
    etr = tracking(c, iid, CITIZEN)["etr"]
    assert etr["updated_on"] == "FIRST_LOCATION" and etr["basis"]["travel_source"] == "ETA_UPPER_BOUND"
    # Further pings while travelling do not keep changing it.
    ping(c, tid, me, offset(SPOT, north_m=2500))
    assert tracking(c, iid, CITIZEN)["etr"]["updated_on"] == "FIRST_LOCATION"

    start(c, tid, me)
    assert tracking(c, iid, CITIZEN)["etr"]["updated_on"] == "WORK_STARTED"
    res = complete(c, tid, me, device=fix(offset(SPOT, east_m=3)))
    assert res["task"]["status"] == "AWAITING_VERIFICATION"
    etr = c.get(f"/api/v1/incidents/{iid}", headers=CITIZEN).json()["progress"]["etr"]
    assert etr["updated_on"] == "COMPLETION_SUBMITTED" and etr["basis"]["work_min"] == 0 and etr["remaining_min"] <= 30

    review(c, res["completion"]["completion_id"], "APPROVE")
    prog = c.get(f"/api/v1/incidents/{iid}", headers=CITIZEN).json()["progress"]
    actual = prog["etr"]["actual"]
    assert prog["etr"]["state"] == "RESOLVED" and prog["resolved_at"] and actual["total_min"] is not None
    assert actual["resolved_at"] == prog["resolved_at"] and actual["work_min"] is not None


def test_etr_uses_the_median_of_resolved_work_once_history_exists(fast_client):
    c = fast_client
    for minutes in (20, 40, 60):
        inc = report(c, device=fix(SPOT))
        tid, me = inc["task"]["task_id"], {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
        start(c, tid, me)
        res = complete(c, tid, me, device=fix(offset(SPOT, east_m=3)), scene=None)
        review(c, res["completion"]["completion_id"], "APPROVE", "Checked the photos")
        with c.app.state.session_factory() as s:
            p = s.get(TaskProgressRow, tid)
            p.work_started_at = p.completion_submitted_at - timedelta(minutes=minutes)
            s.commit()
    inc = report(c, device=fix(SPOT))
    basis = inc["progress"]["etr"]["basis"]
    assert basis["work_source"] == "HISTORICAL_MEDIAN" and basis["work_min"] == 40 and basis["history_samples"] == 3


def test_rework_recomputes_the_estimate(fast_client):
    c = fast_client
    inc = report(c, device=fix(SPOT))
    tid, me = inc["task"]["task_id"], {"X-GeoSatya-Demo-User": inc["task"]["worker_id"]}
    start(c, tid, me)
    res = complete(c, tid, me, device=fix(offset(SPOT, east_m=3)))
    review(c, res["completion"]["completion_id"], "REJECT", "Photo does not show the repair")
    etr = c.get(f"/api/v1/incidents/{inc['incident_id']}", headers=CITIZEN).json()["progress"]["etr"]
    assert etr["updated_on"] == "REWORK" and etr["state"] == "ESTIMATED"


def test_observed_speed_ignores_moving_away_and_short_gaps():
    def p(d, t):
        return LocationPingRow(distance_to_target_m=d, received_at=NOW + timedelta(seconds=t))
    assert estimates.observed_speed_mps([p(1000, 0), p(500, 30)]) is None        # gap under 60 s
    assert estimates.observed_speed_mps([p(1000, 0), p(1100, 120)]) is None      # moving away
    assert estimates.observed_speed_mps([p(1000, 0), p(400, 120)]) == pytest.approx(5.0)
    assert estimates.observed_speed_mps([p(5000, 0), p(100, 61)]) == 20.0        # capped


def test_simulated_tracking_is_refused_in_production():
    from geosatya.config import Settings
    from geosatya.services.common import ServiceError
    from geosatya.services.tracking import _validated

    prod = Settings(app_env="production", auth_mode="token", _env_file=None)
    with pytest.raises(ServiceError):
        _validated(prod, fix(SPOT, mode="SIMULATED"))
    assert _validated(prod, fix(SPOT))[3] == "LIVE"


def test_existing_tasks_without_progress_rows_still_work(client):
    """Tasks from a database created before this feature have no progress row."""
    inc = report(client, device=fix(SPOT))
    with client.app.state.session_factory() as s:
        s.execute(update(TaskProgressRow).where(TaskProgressRow.task_id == inc["task"]["task_id"]).values(etr_due_at=None))
        s.delete(s.get(TaskProgressRow, inc["task"]["task_id"]))
        s.commit()
    assert client.get(f"/api/v1/incidents/{inc['incident_id']}", headers=CITIZEN).json()["progress"]["etr"]["state"] == "UNAVAILABLE"
    assert tracking(client, inc["incident_id"], CITIZEN)["eta"]["state"] == "WAITING_FOR_LOCATION"
