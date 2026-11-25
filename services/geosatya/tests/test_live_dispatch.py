"""Road routing, route-ETA dispatch, worker accuracy, capacity and supervisor
override, concurrent dispatch, out-of-order pings, confirmed arrival,
progress updates with worker estimates, report rate limit, and the live
supervisor dashboard. The routing provider is a fake or an httpx mock."""

import threading
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from geosatya.integrations.routing import CachedRouter, OsrmRouter, Route
from geosatya.location.coordinates import haversine_m
from geosatya.main import create_app
from geosatya.models import AuditRow, IncidentRow, TaskRow, WorkerProfileRow
from geosatya.services import dispatch as dispatch_service
from tests.conftest import CITIZEN, CITIZEN2, SPOT, SUPERVISOR, WORKER12, WORKER15, complete, fix, iso, make_settings, offset, report
from tests.test_integration import age_pings, check_in, ping, tracking


class FakeRouter:
    """Road time = straight line / speed, with per-worker-position overrides."""
    name = "fake"

    def __init__(self, slow_near=None, fail=False):
        self.calls, self.slow_near, self.fail = 0, slow_near, fail

    def route(self, origin, dest):
        self.calls += 1
        if self.fail:
            return None
        d = haversine_m(origin[0], origin[1], dest[0], dest[1])
        detour = 6.0 if self.slow_near and haversine_m(origin[0], origin[1], *self.slow_near) < 5 else 1.3
        return Route(d * detour, d * detour / 8.0, "FAKE", [list(origin), list(dest)])


@pytest.fixture
def c(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, tracking_min_interval_s=0))) as client:
        yield client


def H(w):
    return {"X-GeoSatya-Demo-User": w}


def sup_detail(c, iid):
    return c.get(f"/api/v1/incidents/{iid}", headers=SUPERVISOR).json()


# ------------------------------------------------------------ routing
def test_dispatch_prefers_lowest_road_travel_time_not_nearest_straight_line(c):
    near_but_slow = offset(SPOT, north_m=300)          # across a river, say: long detour
    farther_but_fast = offset(SPOT, east_m=700)
    c.app.state.router = FakeRouter(slow_near=near_but_slow)
    check_in(c, WORKER15, near_but_slow)
    check_in(c, WORKER12, farther_but_fast)
    inc = report(c, device=fix(SPOT))
    d = sup_detail(c, inc["incident_id"])["dispatch"]
    assert d["method"] == "ROUTE_ETA" and inc["task"]["worker_id"] == "W-DEMO-12"
    by = {r["worker_id"]: r for r in d["ranking"]}
    assert by["W-DEMO-15"]["distance_km"] < by["W-DEMO-12"]["distance_km"]            # straight line says W15
    assert by["W-DEMO-12"]["route_eta_min"] < by["W-DEMO-15"]["route_eta_min"]          # road says W12
    assert "by road" in d["reason"]


def test_routing_failure_falls_back_to_the_ranking(c):
    c.app.state.router = FakeRouter(fail=True)
    check_in(c, WORKER15, offset(SPOT, north_m=300))
    check_in(c, WORKER12, offset(SPOT, east_m=900))
    inc = report(c, device=fix(SPOT))
    d = sup_detail(c, inc["incident_id"])["dispatch"]
    assert d["method"] == "DISPATCH_RANKING" and inc["task"]["worker_id"] == "W-DEMO-15" and "straight line" in d["reason"]
    tid = inc["task"]["task_id"]
    ping(c, tid, H("W-DEMO-15"), offset(SPOT, north_m=300))
    t = tracking(c, inc["incident_id"], CITIZEN)
    assert t["route"] is None and t["eta"]["method"] == "APPROXIMATE_STRAIGHT_LINE" and t["eta"]["road_distance_m"] is None


def test_road_eta_and_route_are_shown_only_while_live(c):
    c.app.state.router = FakeRouter()
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], H(inc["task"]["worker_id"])
    ping(c, tid, w, offset(SPOT, north_m=1000))
    t = tracking(c, inc["incident_id"], CITIZEN)
    eta = t["eta"]
    assert eta["method"] == "ROAD_ROUTE_FAKE" and eta["speed_source"] == "ROAD_ROUTE"
    assert eta["road_distance_m"] == pytest.approx(1300, abs=3) and eta["straight_distance_m"] == pytest.approx(1000, abs=3)
    assert t["route"]["geometry"] and t["route"]["provider"] == "FAKE"
    age_pings(c, tid, 600)                                       # stale: no route from an old position
    t = tracking(c, inc["incident_id"], CITIZEN)
    assert t["state"] == "STALE" and t["route"] is None and t["eta"]["method"] == "APPROXIMATE_STRAIGHT_LINE"


def test_osrm_client_parses_and_fails_gracefully():
    def handler(request):
        if "77.000000" in str(request.url):
            return httpx.Response(500, json={"code": "Error"})
        if "78.000000" in str(request.url):
            return httpx.Response(200, json={"code": "NoRoute", "routes": []})
        if "79.000000" in str(request.url):
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, json={"code": "Ok", "routes": [{"distance": 2882.2, "duration": 311.7,
                                         "geometry": {"coordinates": [[77.4126, 23.2599], [77.42, 23.265]]}}]})
    r = OsrmRouter("http://osrm.test", transport=httpx.MockTransport(handler))
    ok = r.route((23.2599, 77.4126), (23.265, 77.42))
    assert ok.distance_m == 2882.2 and ok.duration_s == 311.7 and ok.geometry[0] == [23.2599, 77.4126]  # lat, lon
    assert r.route((23.0, 77.0), (23.1, 77.1)) is None
    assert r.route((23.0, 78.0), (23.1, 78.1)) is None
    assert r.route((23.0, 79.0), (23.1, 79.1)) is None


def test_route_cache_avoids_repeated_requests():
    inner = FakeRouter()
    cached = CachedRouter(inner, ttl_s=60)
    for _ in range(5):
        cached.route((23.25, 77.38), (23.26, 77.39))
    assert inner.calls == 1
    cached.route((23.27, 77.38), (23.26, 77.39))
    assert inner.calls == 2


# ------------------------------------------------- eligibility, capacity
def test_inaccurate_worker_location_is_not_used_for_distance(c):
    check_in(c, WORKER15, offset(SPOT, north_m=100), accuracy=900)
    check_in(c, WORKER12, offset(SPOT, north_m=1500))
    inc = report(c, device=fix(SPOT))
    d = sup_detail(c, inc["incident_id"])["dispatch"]
    assert inc["task"]["worker_id"] == "W-DEMO-12"
    assert any("Location too inaccurate (±900 m)" in r["reasons"] for r in d["rejected"] if r["worker_id"] == "W-DEMO-15")


def test_full_workers_are_not_double_assigned_and_override_needs_a_reason(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, seed_demo_data=False))) as c:  # no seeded task taking a slot
        _full_workers(c)


def _full_workers(c):
    with c.app.state.session_factory() as s:
        for p in s.scalars(select(WorkerProfileRow)):
            p.max_active_tasks = 1
        s.commit()
    check_in(c, WORKER15, offset(SPOT, north_m=200))
    check_in(c, WORKER12, offset(SPOT, north_m=400))
    a, b, third = (report(c, device=fix(SPOT)) for _ in range(3))
    assert {a["task"]["worker_id"], b["task"]["worker_id"]} == {"W-DEMO-12", "W-DEMO-15"}
    assert third["task"] is None and third["status"] == "SUBMITTED"
    rej = sup_detail(c, third["incident_id"])["dispatch"]["rejected"]
    assert all("Worker capacity reached" in r["reasons"] for r in rej)
    url = f"/api/v1/incidents/{third['incident_id']}/assign"
    r = c.post(url, headers=SUPERVISOR, json={"worker_id": "W-DEMO-12"})
    assert r.status_code == 409 and r.json()["code"] == "WORKER_UNAVAILABLE"
    assert c.post(url, headers=SUPERVISOR, json={"worker_id": "W-DEMO-12", "override": True}).status_code == 422
    r = c.post(url, headers=SUPERVISOR, json={"worker_id": "W-DEMO-12", "override": True, "reason": "Urgent: closest crew"})
    assert r.status_code == 200 and r.json()["task"]["worker_id"] == "W-DEMO-12"
    with c.app.state.session_factory() as s:
        assert s.scalar(select(AuditRow).where(AuditRow.action == "ASSIGNMENT_OVERRIDE")) is not None


def test_concurrent_dispatch_never_exceeds_capacity(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, dispatch_fallback="escalate"))) as c:
        ids = [report(c, device=fix(SPOT))["incident_id"] for _ in range(6)]          # nobody shared a location yet
        with c.app.state.session_factory() as s:
            for p in s.scalars(select(WorkerProfileRow)):
                p.max_active_tasks = 2
            s.commit()
        check_in(c, WORKER15, offset(SPOT, north_m=200))
        check_in(c, WORKER12, offset(SPOT, north_m=300))
        state, errors = c.app.state, []

        def run(iid):
            try:
                with dispatch_service.DISPATCH_LOCK, state.session_factory() as s:
                    dispatch_service.dispatch_incident(s, state.settings, state.categories, s.get(IncidentRow, iid))
                    s.commit()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        threads = [threading.Thread(target=run, args=(i,)) for i in ids]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert not errors
        with state.session_factory() as s:
            tasks = s.scalars(select(TaskRow)).all()
        per_worker = {w: sum(t.worker_id == w for t in tasks) for w in ("W-DEMO-12", "W-DEMO-15")}
        assert per_worker == {"W-DEMO-12": 2, "W-DEMO-15": 2} and len({t.incident_id for t in tasks}) == len(tasks)


# ------------------------------------------------------- tracking edges
def test_duplicate_and_out_of_order_updates_are_ignored(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], H(inc["task"]["worker_id"])
    newer = fix(offset(SPOT, north_m=500), observed=5)
    older = fix(offset(SPOT, north_m=900), observed=60)
    assert c.post(f"/api/v1/tasks/{tid}/location", headers=w, json=newer).json()["stored"] is True
    assert c.post(f"/api/v1/tasks/{tid}/location", headers=w, json=newer).json() == {"stored": False, "reason": "DUPLICATE"}
    assert c.post(f"/api/v1/tasks/{tid}/location", headers=w, json=older).json() == {"stored": False, "reason": "OUT_OF_ORDER"}
    assert tracking(c, inc["incident_id"], SUPERVISOR)["latest"]["distance_m"] == pytest.approx(500, abs=2)


def test_worker_confirms_arrival_only_from_inside_the_radius(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], H(inc["task"]["worker_id"])
    url = f"/api/v1/tasks/{tid}/arrive"
    assert c.post(url, headers=w, json={}).json()["code"] == "LOCATION_REQUIRED"
    r = c.post(url, headers=w, json={"location": fix(offset(SPOT, north_m=200))})
    assert r.status_code == 409 and r.json()["code"] == "ARRIVAL_NOT_CONFIRMED" and "200 m" in r.json()["detail"]
    r = c.post(url, headers=w, json={"location": fix(offset(SPOT, north_m=20), accuracy=120)})
    assert r.status_code == 409                                                    # too inaccurate
    r = c.post(url, headers=w, json={"location": fix(offset(SPOT, north_m=20), accuracy=10)})
    assert r.status_code == 200 and r.json()["arrived"] is True
    assert tracking(c, inc["incident_id"], CITIZEN)["phase"] == "ARRIVED"
    assert c.post(url, headers=CITIZEN, json={"location": fix(SPOT)}).status_code == 403
    c.post(f"/api/v1/tasks/{tid}/start", headers=w)
    assert c.post(url, headers=w, json={"location": fix(SPOT)}).status_code == 409


def test_progress_updates_and_worker_estimate_drive_the_etr(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], H(inc["task"]["worker_id"])
    url = f"/api/v1/tasks/{tid}/progress"
    assert c.post(url, headers=w, json={"note": "Started", "estimate_minutes": 20}).json()["code"] == "TASK_NOT_IN_PROGRESS"
    c.post(f"/api/v1/tasks/{tid}/start", headers=w)
    r = c.post(url, headers=w, json={"note": "Removed loose material, filling now", "estimate_minutes": 25})
    etr = r.json()["progress"]["etr"]
    assert r.status_code == 200 and etr["updated_on"] == "WORKER_ESTIMATE" and etr["basis"]["work_source"] == "WORKER_ESTIMATE"
    assert 54 <= etr["remaining_min"] <= 55                                         # 25 + 30 review buffer
    assert c.post(url, headers=w, json={"note": "x"}).status_code == 422
    assert c.post(url, headers=w, json={"note": "Too long a job", "estimate_minutes": 5000}).status_code == 422
    cit = c.get(f"/api/v1/incidents/{inc['incident_id']}", headers=CITIZEN).json()
    assert "PROGRESS_UPDATE" in [e["event"] for e in cit["progress"]["events"]]
    assert tracking(c, inc["incident_id"], CITIZEN)["progress_updates"][0]["estimate_minutes"] == 25
    # Completion still decides by the geofence, and a later completion replaces the worker's estimate.
    res = complete(c, tid, w, device=fix(offset(SPOT, east_m=3)))
    assert res["completion"]["outcome"] == "PASS"
    assert c.get(f"/api/v1/incidents/{inc['incident_id']}", headers=CITIZEN).json()["progress"]["etr"]["updated_on"] == "COMPLETION_SUBMITTED"


def test_release_works_after_progress_updates(c):
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], H(inc["task"]["worker_id"])
    c.post(f"/api/v1/tasks/{tid}/start", headers=w)
    c.post(f"/api/v1/tasks/{tid}/progress", headers=w, json={"note": "Waiting for material"})
    r = c.post(f"/api/v1/tasks/{tid}/release", headers=SUPERVISOR, json={"kind": "CANCELLED", "reason": "Needs a bigger crew"})
    assert r.status_code == 200, r.text


# ----------------------------------------------------- limits, dashboard
def test_report_rate_limit(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, report_rate_limit_per_min=2))) as c:
        report(c, device=fix(SPOT))
        report(c, device=fix(SPOT))
        report(c, device=fix(SPOT), expect=429)
        report(c, device=fix(SPOT), headers=CITIZEN2)                               # per user


def test_live_dashboard_kpis_and_worker_privacy(c):
    check_in(c, WORKER15, offset(SPOT, north_m=300))
    inc = report(c, device=fix(SPOT))
    tid, w = inc["task"]["task_id"], inc["task"]["worker_id"]
    ping(c, tid, H(w), offset(SPOT, north_m=250))
    d = c.get("/api/v1/dashboard/live", headers=SUPERVISOR).json()
    k = d["kpis"]
    assert k["open_incidents"] >= 2 and k["travelling_workers"] == 1                # seeded demo incident + ours
    me = next(x for x in d["workers"] if x["worker_id"] == w)
    assert me["status"] == "EN_ROUTE" and me["location_state"] == "LIVE" and me["current_incident_id"] == inc["incident_id"]
    other = next(x for x in d["workers"] if x["worker_id"] != w)
    assert other["location"] is None and other["location_state"] == "NONE"          # never shared: no position
    ours = next(i for i in d["incidents"] if i["incident_id"] == inc["incident_id"])
    assert ours["latitude"] == pytest.approx(SPOT[0]) and ours["phase"] == "EN_ROUTE"
    # An old location is not shown at all.
    with c.app.state.session_factory() as s:
        p = s.get(WorkerProfileRow, w)
        p.last_received_at = p.last_received_at - timedelta(hours=1)
        s.commit()
    me = next(x for x in c.get("/api/v1/dashboard/live", headers=SUPERVISOR).json()["workers"] if x["worker_id"] == w)
    assert me["location"] is None and me["location_state"] == "OFFLINE"
    assert c.get("/api/v1/dashboard/live", headers=CITIZEN).status_code == 403
    # With two jobs, the "current" one is the job being tracked, not the oldest.
    inc2 = report(c, device=fix(offset(SPOT, east_m=600)))
    assert inc2["task"]["worker_id"]
    with c.app.state.session_factory() as s:
        t2 = s.get(TaskRow, inc2["task"]["task_id"])
        t2.worker_id = w                                          # give the same worker a second, untracked job
        s.commit()
    me = next(x for x in c.get("/api/v1/dashboard/live", headers=SUPERVISOR).json()["workers"] if x["worker_id"] == w)
    assert me["current_incident_id"] == inc["incident_id"]
    assert c.get("/api/v1/dashboard/live", headers=H(w)).status_code == 403
