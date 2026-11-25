import pytest
from fastapi.testclient import TestClient

from conftest import ScriptedLLM, good_json
from kavach.agents.incident_intelligence import IncidentIntelligenceAgent, MockLLM
from kavach.errors import LLMUnavailableError
from kavach.main import create_app
from kavach.repositories.incident_repository import InMemoryIncidentRepository
from kavach.services.incident_intelligence.orchestrator import IncidentIntelligenceOrchestrator

URL = "/api/v1/incidents"
PIN = {"selected_latitude": "23.2500", "selected_longitude": "77.4000"}
NEAR = {"device_latitude": "23.2503", "device_longitude": "77.4002", "device_accuracy_meters": "15"}
FAR = {"device_latitude": "23.3500", "device_longitude": "77.4000", "device_accuracy_meters": "15"}
TEXT = {"complaint_text": "The dustbin near the main gate is overflowing and blocking the path"}


def make_client(llm=None):
    llm = llm or MockLLM()
    orch = IncidentIntelligenceOrchestrator(IncidentIntelligenceAgent(llm), InMemoryIncidentRepository())
    return TestClient(create_app(orch)), orch, llm


def img(data, name="photo.jpg", mime="image/jpeg"):
    return [("images", (name, data, mime))]


def test_text_only_complaint_produces_structured_record():
    client, _, _ = make_client()
    r = client.post(URL, data=TEXT)
    assert r.status_code == 201
    b = r.json()
    assert (b["category"], b["incident_type"]) == ("SANITATION", "WASTE_OVERFLOW")
    assert b["severity_recommendation"] == "MEDIUM" and b["incident_id"].startswith("INC-")
    assert b["location_evidence_summary"]["check"]["status"] == "NOT_CHECKED"
    assert "INCIDENT_LOCATION_UNKNOWN" in b["missing_information"] and b["needs_clarification"]
    assert b["image_observations"] == []  # text-only: no image observations


def test_pin_and_nearby_device_is_consistent():
    client, _, _ = make_client()
    b = client.post(URL, data={**TEXT, **PIN, **NEAR}).json()
    ev = b["location_evidence_summary"]
    assert ev["check"]["status"] == "CONSISTENT" and ev["reported_location_source"] == "USER_SELECTED_PIN"
    assert "INCIDENT_LOCATION_UNKNOWN" not in b["missing_information"]


def test_remote_citizen_report_is_accepted_not_labelled_fake():
    client, _, _ = make_client()
    r = client.post(URL, data={**TEXT, **PIN, **FAR})
    b = r.json()
    assert r.status_code == 201
    check = b["location_evidence_summary"]["check"]
    assert check["status"] == "MISMATCH" and check["requires_human_review"] is False
    assert any("remote" in c.lower() for c in b["conflicting_information"])


def test_image_exif_gps_is_read_and_kept_separate(make_image):
    client, _, _ = make_client()
    r = client.post(URL, data={**TEXT, **PIN, **NEAR}, files=img(make_image(gps=(23.2502, 77.4001))))
    ev = r.json()["location_evidence_summary"]
    assert ev["images_with_gps"] == 1 and ev["images_total"] == 1
    assert set(ev["check"]["evidence_sources"]) == {"DEVICE_GEOLOCATION", "IMAGE_EXIF"}


def test_device_vs_exif_conflict_requires_review(make_image):
    client, _, _ = make_client()
    r = client.post(URL, data={**TEXT, **PIN, **NEAR}, files=img(make_image(gps=(23.35, 77.40))))
    check = r.json()["location_evidence_summary"]["check"]
    assert "SOURCE_CONFLICT" in check["reason_codes"] and check["requires_human_review"] is True


def test_malformed_image_is_rejected_safely_and_request_continues():
    client, _, _ = make_client()
    r = client.post(URL, data=TEXT, files=img(b"definitely not an image"))
    assert r.status_code == 201
    assert any(m.startswith("IMAGE_REJECTED:img-1") for m in r.json()["missing_information"])


def test_oversized_image_rejected(make_image):
    orch = IncidentIntelligenceOrchestrator(IncidentIntelligenceAgent(MockLLM()), InMemoryIncidentRepository(),
                                            max_image_bytes=100)
    r = TestClient(create_app(orch)).post(URL, data=TEXT, files=img(make_image()))
    assert "IMAGE_REJECTED:img-1:FILE_TOO_LARGE" in r.json()["missing_information"]


@pytest.mark.parametrize("extra", [
    {"selected_latitude": "200", "selected_longitude": "77"},
    {"selected_latitude": "nan", "selected_longitude": "77"},
    {"selected_latitude": "abc", "selected_longitude": "77"},
    {"selected_latitude": "23.2"},                     # lat without lon
    {"device_latitude": "10", "device_longitude": "10", "device_accuracy_meters": "-5"},
])
def test_invalid_coordinates_return_422(extra):
    client, _, llm = make_client(ScriptedLLM(good_json()))
    assert client.post(URL, data={**TEXT, **extra}).status_code == 422
    assert llm.calls == 0  # invalid input never reaches the LLM


def test_empty_complaint_returns_422():
    client, _, _ = make_client()
    assert client.post(URL, data={"complaint_text": ""}).status_code == 422
    assert client.post(URL, data={}).status_code == 422


def test_severity_floor_overrides_low_model_rating():
    llm = ScriptedLLM(good_json(severity_recommendation="LOW"))
    client, _, _ = make_client(llm)
    b = client.post(URL, data={"complaint_text": "Live wire fallen near the bench, sparking"}).json()
    assert b["severity_recommendation"] == "HIGH" and "ELECTRICAL_HAZARD" in b["severity_rule_matches"]


def test_unknown_category_flagged():
    client, _, _ = make_client(ScriptedLLM(good_json(category="PIZZA", incident_type="CALZONE")))
    b = client.post(URL, data=TEXT).json()
    assert (b["category"], b["incident_type"]) == ("OTHER", "UNKNOWN") and b["needs_clarification"]


def test_llm_unavailable_returns_503_and_stores_nothing():
    client, orch, _ = make_client(ScriptedLLM(LLMUnavailableError("quota")))
    r = client.post(URL, data=TEXT, headers={"X-Request-ID": "req-1"})
    assert r.status_code == 503 and r.headers["retry-after"] == "30"
    assert orch.repository.get_by_request_id("req-1") is None


def test_invalid_model_output_is_repaired_once():
    llm = ScriptedLLM("garbage", good_json())
    client, _, _ = make_client(llm)
    assert client.post(URL, data=TEXT).status_code == 201 and llm.calls == 2


def test_invalid_model_output_twice_is_controlled_failure():
    llm = ScriptedLLM("garbage", "still garbage")
    client, orch, _ = make_client(llm)
    r = client.post(URL, data=TEXT, headers={"X-Request-ID": "req-2"})
    assert r.status_code == 502 and r.json()["detail"]["code"] == "MODEL_OUTPUT_INVALID"
    assert llm.calls == 2 and orch.repository.get_by_request_id("req-2") is None


def test_same_request_id_is_idempotent():
    llm = ScriptedLLM(good_json())
    client, _, _ = make_client(llm)
    a = client.post(URL, data=TEXT, headers={"X-Request-ID": "req-3"}).json()
    b = client.post(URL, data=TEXT, headers={"X-Request-ID": "req-3"}).json()
    assert a["incident_id"] == b["incident_id"] and llm.calls == 1


def test_get_incident_roundtrip_and_404():
    from kavach.config import Settings
    orch = IncidentIntelligenceOrchestrator(IncidentIntelligenceAgent(MockLLM()), InMemoryIncidentRepository())
    client = TestClient(create_app(orch, Settings(read_api_key="test-key")))
    key = {"X-API-Key": "test-key"}
    created = client.post(URL, data=TEXT).json()
    assert client.get(f"{URL}/{created['incident_id']}", headers=key).json()["incident_id"] == created["incident_id"]
    assert client.get(f"{URL}/INC-NOPE", headers=key).status_code == 404


def test_provenance_records_sources_and_model():
    client, _, _ = make_client()
    b = client.post(URL, data={**TEXT, **PIN, **NEAR}).json()
    sources = {e["source"] for e in b["evidence_provenance"]}
    assert {"COMPLAINT_TEXT", "DEVICE_GEOLOCATION", "USER_SELECTED_PIN", "LOCATION_CHECK", "LLM"} <= sources
