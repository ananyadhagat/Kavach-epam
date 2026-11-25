"""Runs only when KAVACH_TEST_DATABASE_URL points at a disposable PostgreSQL database.

    KAVACH_TEST_DATABASE_URL=postgresql://user@127.0.0.1:5432/kavach_test pytest tests/integration/test_postgres_repository.py
"""
import os

import pytest
from fastapi.testclient import TestClient

from conftest import ScriptedLLM, good_json

DSN = os.getenv("KAVACH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DSN, reason="KAVACH_TEST_DATABASE_URL not set")


@pytest.fixture
def repo():
    psycopg = pytest.importorskip("psycopg")
    from kavach.repositories.incident_repository import PostgresIncidentRepository
    with psycopg.connect(DSN) as conn:
        conn.execute("DROP TABLE IF EXISTS incident_records")
    return PostgresIncidentRepository(DSN)


def _orch(repo, llm=None):
    from kavach.agents.incident_intelligence import IncidentIntelligenceAgent
    from kavach.services.incident_intelligence.orchestrator import IncidentIntelligenceOrchestrator
    return IncidentIntelligenceOrchestrator(IncidentIntelligenceAgent(llm or ScriptedLLM(good_json())), repo)


def test_postgres_save_get_roundtrip(repo, make_image):
    from kavach.config import Settings
    from kavach.main import create_app
    orch = _orch(repo)
    client = TestClient(create_app(orch, Settings(read_api_key="k")))
    b = client.post("/api/v1/incidents", data={"complaint_text": "Bin overflowing", "selected_latitude": "23.25",
                                               "selected_longitude": "77.4", "device_latitude": "23.2503",
                                               "device_longitude": "77.4002"},
                    files=[("images", ("p.jpg", make_image(gps=(23.2502, 77.4)), "image/jpeg"))],
                    headers={"X-Request-ID": "pg-1"}).json()
    got = client.get(f"/api/v1/incidents/{b['incident_id']}", headers={"X-API-Key": "k"}).json()
    assert got == b
    assert repo.get_by_request_id("pg-1").complaint_text == "Bin overflowing"


def test_postgres_conflict_returns_stored_record(repo):
    from kavach.schemas.incident_intelligence import IncidentSubmission
    from kavach.services.incident_intelligence.orchestrator import request_fingerprint
    sub = IncidentSubmission(request_id="pg-race", complaint_text="Bin overflowing")
    first = _orch(repo).process(sub)
    # a second worker that skipped the read (lost the race) must get the stored record back
    second = _orch(repo)._process_new(sub, [], request_fingerprint(sub, []))
    assert second.incident_id == first.incident_id


def test_postgres_down_is_repository_error():
    from kavach.errors import RepositoryError
    from kavach.repositories.incident_repository import PostgresIncidentRepository
    with pytest.raises(RepositoryError):
        PostgresIncidentRepository("postgresql://nobody@127.0.0.1:1/none?connect_timeout=1")
