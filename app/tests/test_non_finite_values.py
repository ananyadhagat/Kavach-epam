import json
import math

import pytest
from pydantic import ValidationError

from app.api.error_handlers import json_safe
from app.schemas.location_event import LocationEventCreate
from app.schemas.worker_task import TaskLocation
from app.tests.conftest import API, AUTH, count_rows, post_action

NON_FINITE_TOKENS = ["NaN", "Infinity", "-Infinity", "1e400", "-1e400"]
JSON_HEADERS = {**AUTH, "Content-Type": "application/json"}


def strict_json(text: str):
    # Rejects NaN/Infinity, which Python's json module otherwise accepts.
    def reject(constant):
        raise ValueError(f"Non-standard JSON constant: {constant}")

    return json.loads(text, parse_constant=reject)


def raw_location_body(field: str, token: str, event_type="ARRIVAL") -> str:
    values = {"latitude": "23.25", "longitude": "77.41",
              "accuracy_meters": "10"}
    values[field] = token
    return (
        '{"event_type":"%s","capture_status":"CAPTURED",'
        '"latitude":%s,"longitude":%s,"accuracy_meters":%s}'
        % (event_type, values["latitude"], values["longitude"],
           values["accuracy_meters"])
    )


def location_count(client) -> int:
    return count_rows(client, "location_events")


@pytest.fixture
def in_progress(client):
    post_action(client, "TASK-001", "accept")
    post_action(client, "TASK-001", "start")
    return client


@pytest.mark.parametrize("token", NON_FINITE_TOKENS)
@pytest.mark.parametrize("field", ["latitude", "longitude", "accuracy_meters"])
@pytest.mark.parametrize("endpoint", ["arrival", "completion-location"])
def test_non_finite_location_values_return_422_json(in_progress, endpoint,
                                                    field, token):
    event_type = "ARRIVAL" if endpoint == "arrival" else "COMPLETION"

    response = in_progress.post(
        f"{API}/TASK-001/{endpoint}",
        content=raw_location_body(field, token, event_type),
        headers=JSON_HEADERS,
    )

    assert response.status_code == 422
    body = strict_json(response.text)
    error = body["detail"][0]
    assert error["loc"] == ["body", field]
    assert error["type"] == "finite_number"
    assert isinstance(error["input"], str)
    assert location_count(in_progress) == 0


def test_non_finite_in_other_fields_returns_valid_json(in_progress):
    # The handler fix is generic: any field echoing NaN must stay valid JSON.
    response = in_progress.patch(
        f"{API}/TASK-001/checklist/STEP-001",
        content=b'{"status": NaN}',
        headers=JSON_HEADERS,
    )

    assert response.status_code == 422
    assert strict_json(response.text)["detail"][0]["input"] == "nan"


def test_non_finite_completion_notes_returns_valid_json(in_progress):
    response = in_progress.post(
        f"{API}/TASK-001/completion",
        content=b'{"checklist_step_ids":["STEP-001"],'
                b'"evidence_ids":["a","b"],"notes":Infinity}',
        headers={**JSON_HEADERS, "Idempotency-Key": "k1"},
    )

    assert response.status_code == 422
    strict_json(response.text)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("field", ["latitude", "longitude", "accuracy_meters"])
def test_schema_rejects_non_finite(field, value):
    payload = {"event_type": "ARRIVAL", "capture_status": "CAPTURED",
               "latitude": 1.0, "longitude": 1.0, "accuracy_meters": 5.0}
    payload[field] = value

    with pytest.raises(ValidationError) as exc:
        LocationEventCreate(**payload)

    assert exc.value.errors()[0]["type"] == "finite_number"


@pytest.mark.parametrize("value", [math.nan, math.inf])
def test_task_location_rejects_non_finite(value):
    with pytest.raises(ValidationError):
        TaskLocation(latitude=value, longitude=1.0, address="x")


def test_json_safe_converts_nested_non_finite_values():
    assert json_safe({"a": [math.nan, {"b": math.inf}], "c": 1.5,
                      "d": (-math.inf, "x")}) == {
        "a": ["nan", {"b": "inf"}], "c": 1.5, "d": ["-inf", "x"],
    }


def test_finite_values_still_accepted(in_progress):
    response = in_progress.post(
        f"{API}/TASK-001/arrival",
        content=raw_location_body("latitude", "-90"),
        headers=JSON_HEADERS,
    )

    assert response.status_code == 200
