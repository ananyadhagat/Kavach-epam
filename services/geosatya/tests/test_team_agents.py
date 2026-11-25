"""Team agents after Incident Intelligence: Duplicate Detection, Supervisor and
Sanitation. The agents are replaced by mock transports returning the shapes
their own code returns; nothing here needs the agent services running."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from geosatya.integrations.agents import AgentClient, TeamAgents
from geosatya.kavach.seed import CITY, EVENT
from geosatya.main import create_app
from tests.conftest import complaint_post, CITIZEN, SUPERVISOR, fix, make_settings, offset, report

K = "/api/v1/kavach"
ORG_ADMIN = {"X-GeoSatya-Demo-User": "ORG-DEMO-01"}
GUARD = {"X-GeoSatya-Demo-User": "EW-DEMO-32"}
ORGANIZER = {"X-GeoSatya-Demo-User": "EO-DEMO-01"}


class FakeAgents:
    """Records every call; behaves like the three agents."""

    def __init__(self):
        self.calls = []
        self.store = []           # duplicate agent's complaint store
        self.down = set()
        self.reject = set()

    def handler(self, name):
        def handle(request: httpx.Request):
            body = json.loads(request.content or b"{}")
            self.calls.append((name, request.url.path, body, request.headers.get("Idempotency-Key")))
            if name in self.down:
                raise httpx.ConnectError("down")
            if name in self.reject:
                return httpx.Response(422, json={"detail": {"code": "INVALID_COMPLAINT_PAYLOAD"}})
            if name == "dup":
                match = next((c for c in self.store if c["category"] == body["category"]
                              and abs(c["location"]["latitude"] - body["location"]["latitude"]) < 0.001), None)
                self.store.append(body)
                return httpx.Response(201, json={"complaint_id": body["complaint_id"], "decision": "DUPLICATE" if match else "NEW",
                                                 "consolidation_status": "DUPLICATE" if match else "PRIMARY",
                                                 "matched_incident_id": match["complaint_id"] if match else None,
                                                 "primary_complaint_id": match["complaint_id"] if match else body["complaint_id"],
                                                 "score": 0.93 if match else None, "reasons": ["SCORE_ABOVE_HIGH_THRESHOLD"] if match else ["NO_ELIGIBLE_CANDIDATES"],
                                                 "active_duplicate_count": 1 if match else 0})
            if name == "sup":
                return httpx.Response(200, json={
                    "supervisor_decision": {"decision_id": "dec-1", "incident_id": body["incident_id"], "department": "SANITATION_DEPT",
                                            "priority": "P2", "decision_status": "APPROVED_TO_PROCEED", "ward_or_route": "WARD_01_MP_NAGAR"},
                    "routing": {"next_process": "4.0_SANITATION_PLANNING", "dispatch_eligible": True},
                    "audit": {"reason_codes": ["DEPT_RESOLVED"], "rationale": "Waste in ward 1"}, "llm_response": {"mode": "mock"}})
            if name == "san":
                return httpx.Response(200, json={"plan_id": f"SAN-PLAN-{body['incident']['incident_id']}", "planning_status": "PRELIMINARY_PLAN",
                                                 "dispatch_eligible": False, "hold_reason_codes": ["QUANTITY_NOT_MEASURED"],
                                                 "template": {"template_id": body["supervisor_decision"]["action_plan"]["template_id"]},
                                                 "tasks": [{"sequence": 1, "title": "Inspect", "estimated_duration": {"minutes": 15},
                                                            "required_resources": [{"resource_code": "PPE_GENERAL"}], "completion_criteria": ["Recorded"]}]})
            return httpx.Response(404)
        return handle

    def install(self, app):
        app.state.agents = TeamAgents(*(AgentClient(n, f"http://{n}", 5, transport=httpx.MockTransport(self.handler(n)))
                                        for n in ("dup", "sup", "san")))


@pytest.fixture
def env(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, tracking_min_interval_s=0))) as c:
        fake = FakeAgents()
        fake.install(c.app)
        yield c, fake


def garbage(c, point=None, headers=CITIZEN, text="Garbage pile dumped next to the bus stop, smells bad", expect=201):
    body = {"category": "garbage", "title": "Garbage pile at bus stop", "description": text, "device_location": fix(point or offset(CITY, north_m=300))}
    r = complaint_post(c, body, headers=headers)
    assert r.status_code == expect, r.text
    return r.json()


def agents(c, incident_id, headers=SUPERVISOR):
    r = c.get(f"{K}/incidents/{incident_id}/agents", headers=headers)
    assert r.status_code == 200, r.text
    return {a["agent"]: a for a in r.json()["agents"]}


def test_all_three_agents_run_in_order_with_real_upstream_output(env):
    c, fake = env
    inc = garbage(c)
    names = [n for n, *_ in fake.calls]
    assert names == ["dup", "sup", "san"]
    dup_body, sup_body, san_body = (b for _, _, b, _ in fake.calls)
    assert dup_body["complaint_id"] == inc["incident_id"] and set(dup_body) == {"complaint_id", "description", "category", "location", "reported_at"}
    assert sup_body["duplicate_check"]["decision"] == "NEW"                      # Supervisor sees the duplicate result
    assert san_body["supervisor_decision"]["priority"] == "HIGH"                 # P2 from the Supervisor agent
    assert san_body["supervisor_decision"]["action_plan"]["template_id"] == "GARBAGE_PILE_REMOVAL"
    a = agents(c, inc["incident_id"], ORG_ADMIN)                                  # routed to the municipal workspace
    assert a["DUPLICATE_DETECTION"]["summary"]["decision"] == "NEW"
    assert a["SUPERVISOR"]["summary"]["department"] == "SANITATION_DEPT"
    assert a["SANITATION"]["summary"]["tasks"][0]["title"] == "Inspect"


def test_second_similar_report_is_flagged_duplicate_and_linked(env):
    c, fake = env
    first = garbage(c)
    second = garbage(c, point=offset(CITY, north_m=310), text="Overflowing garbage heap at the bus stop again")
    d = agents(c, second["incident_id"], ORG_ADMIN)["DUPLICATE_DETECTION"]["summary"]
    assert d["decision"] == "DUPLICATE" and d["matched_incident_id"] == first["incident_id"]


def test_a_down_agent_never_blocks_the_report_and_can_be_retried(env):
    c, fake = env
    fake.down = {"dup", "sup", "san"}
    inc = garbage(c)                                                             # still 201
    a = agents(c, inc["incident_id"], ORG_ADMIN)
    assert {x["status"] for k, x in a.items() if k != "VERIFICATION"} == {"UNAVAILABLE"}
    # Sanitation was still asked, but told honestly that nothing upstream approved it.
    san_body = [b for n, _, b, _ in fake.calls if n == "san"][0]
    assert san_body["supervisor_decision"]["decision_status"] == "NEEDS_REVIEW"
    fake.down = set()
    r = c.post(f"{K}/incidents/{inc['incident_id']}/agents/retry", headers=ORG_ADMIN).json()
    assert {x["status"] for x in r["agents"] if x["agent"] != "VERIFICATION"} == {"COMPLETED"}


def test_a_rejected_payload_is_recorded_not_hidden(env):
    c, fake = env
    fake.reject = {"dup"}
    inc = garbage(c)
    a = agents(c, inc["incident_id"], ORG_ADMIN)["DUPLICATE_DETECTION"]
    assert a["status"] == "REJECTED" and a["error"] == "INVALID_COMPLAINT_PAYLOAD"


def test_sanitation_runs_only_for_waste_incidents(env):
    c, fake = env
    body = {"category": "streetlight", "title": "Streetlight off", "description": "The streetlight has been off for days.",
            "device_location": fix(offset(CITY, east_m=500))}
    inc = complaint_post(c, body, headers=CITIZEN).json()
    assert "san" not in [n for n, *_ in fake.calls]
    assert agents(c, inc["incident_id"], ORG_ADMIN)["SANITATION"]["status"] == "NOT_APPLICABLE"


def test_bin_wording_selects_the_bin_template(env):
    c, fake = env
    garbage(c, text="The dustbin is overflowing onto the road")
    san_body = [b for n, _, b, _ in fake.calls if n == "san"][0]
    assert san_body["supervisor_decision"]["action_plan"]["template_id"] == "BIN_OVERFLOW_RESPONSE"


def test_private_event_incidents_are_never_sent_to_the_shared_duplicate_store(env):
    c, fake = env
    body = {"category": "garbage", "title": "Bins overflowing at food court", "description": "Bins are overflowing near stall 4.",
            "device_location": fix(offset(EVENT, east_m=20))}
    r = c.post(f"{K}/workspaces/WS-DEMO-EVT/incidents", json=body, headers=GUARD)
    assert r.status_code == 201, r.text
    assert "dup" not in [n for n, *_ in fake.calls]
    assert agents(c, r.json()["incident_id"], ORGANIZER)["DUPLICATE_DETECTION"]["status"] == "NOT_APPLICABLE"


def test_a_match_in_another_workspace_is_not_revealed(env):
    c, fake = env
    civic = garbage(c, point=(12.97, 77.59))                                    # outside every jurisdiction: open civic team
    routed = garbage(c, point=(12.9701, 77.5901))                               # same spot, but pretend it was routed elsewhere
    with c.app.state.session_factory() as s:
        from geosatya.models import IncidentRow
        s.get(IncidentRow, routed["incident_id"]).workspace_id = "WS-DEMO-ORG"
        s.commit()
    d = agents(c, routed["incident_id"], ORG_ADMIN)["DUPLICATE_DETECTION"]["summary"]
    assert d["decision"] == "DUPLICATE" and d["matched_incident_id"] is None and d["matched_elsewhere"] is True
    assert civic["incident_id"] not in json.dumps(agents(c, routed["incident_id"], ORG_ADMIN))


def test_agent_results_are_staff_only_and_workspace_scoped(env):
    c, fake = env
    inc = garbage(c)
    assert c.get(f"{K}/incidents/{inc['incident_id']}/agents", headers=CITIZEN).status_code == 403
    assert c.get(f"{K}/incidents/{inc['incident_id']}/agents", headers=ORGANIZER).status_code == 404


def test_original_geosatya_reports_also_run_the_agents(env):
    c, fake = env
    inc = report(c, device=fix(offset(CITY, north_m=-200)), category="garbage", title="Garbage pile", description="Garbage pile near the park gate.")
    assert [n for n, *_ in fake.calls] == ["dup", "sup", "san"]
    assert agents(c, inc["incident_id"])["DUPLICATE_DETECTION"]["status"] == "COMPLETED"


def test_without_configured_agents_everything_works_as_before(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as c:
        inc = garbage(c)
        statuses = agents(c, inc["incident_id"], ORG_ADMIN)
        assert {a["status"] for k, a in statuses.items() if k != "VERIFICATION"} == {"NOT_CONFIGURED"}
        assert statuses["VERIFICATION"]["status"] == "NOT_RUN"           # no completion yet
        assert {a["configured"] for a in c.get(f"{K}/agents/status").json()["agents"] if a["agent"] != "VERIFICATION"} == {False}
