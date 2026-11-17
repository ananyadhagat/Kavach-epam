"""KAVACH Dispatch prototype API.

Dispatch offers are kept in memory in this prototype. A production deployment
should move offers, reservations, and idempotency records to a shared database
and publish notifications through the configured mobile push provider.
"""

import asyncio
import copy
import hashlib
import json
import os
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.data import get_worker, list_workers
from app.dispatch import dispatch_task


DEFAULT_OFFER_TIMEOUT_SECONDS = 15 * 60
try:
    OFFER_TIMEOUT_SECONDS = max(
        1, int(os.getenv("KAVACH_OFFER_TIMEOUT_SECONDS", DEFAULT_OFFER_TIMEOUT_SECONDS))
    )
except ValueError:
    OFFER_TIMEOUT_SECONDS = DEFAULT_OFFER_TIMEOUT_SECONDS

# One process-wide lock protects candidate selection and capacity reservation.
# This prevents simultaneous requests in this process taking the same last slot.
dispatch_lock = RLock()
dispatch_records: dict[str, dict[str, Any]] = {}
dispatch_events: dict[str, str] = {}
offers: dict[str, dict[str, Any]] = {}
reserved_by_worker: dict[str, int] = {}
DISPATCH_MAX_RADIUS_KM = 10.0


class PlanLocation(BaseModel):
    model_config = ConfigDict(extra="allow")

    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    accuracy_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    source: str | None = None
    facility_id: str | None = None
    location_id: str | None = None


class RoutingInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = "UNRESOLVED"
    facility_id: str | None = None
    location_id: str | None = None
    ward_id: str | None = None
    queue_id: str | None = None


class TemplateReference(BaseModel):
    model_config = ConfigDict(extra="allow")

    template_id: str = Field(min_length=1)
    template_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)


class TaskDuration(BaseModel):
    model_config = ConfigDict(extra="allow")

    minutes: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    status: str = "UNKNOWN"
    basis: list[str] = Field(default_factory=list)


class ResourceRequirement(BaseModel):
    model_config = ConfigDict(extra="allow")

    resource_code: str = Field(min_length=1)
    quantity: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    unit: str | None = None
    basis: str | None = None


class SanitationTask(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    task_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    task_code: str = Field(min_length=1)
    title: str = Field(min_length=1)
    task_name: str | None = None
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    estimated_duration: TaskDuration = Field(default_factory=TaskDuration)
    required_resources: list[ResourceRequirement] = Field(default_factory=list)
    completion_criteria: list[str] = Field(default_factory=list)
    checklist: list[str] = Field(default_factory=list)
    status: str = "NOT_STARTED"


class ResourceEstimate(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = "UNKNOWN"
    required_resources: list[str] = Field(default_factory=list)
    estimated_worker_demand: dict[str, Any] | None = None
    availability_confirmed: bool | None = None
    resource_policy_version: str | None = None


class DurationEstimate(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = "UNKNOWN"
    total_minutes: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    range_minutes: Any = None
    method: str | None = None
    basis: list[str] = Field(default_factory=list)
    sla_response_due_at: datetime | None = None
    sla_resolution_due_at: datetime | None = None

    @field_validator("sla_response_due_at", "sla_resolution_due_at")
    @classmethod
    def sla_timestamps_must_be_aware(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("SLA timestamps must include a timezone")
        return value


class DispatchRequest(BaseModel):
    """Validated Sanitation plan contract consumed by Dispatch."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    contract_version: Literal["1.0.0"] = "1.0.0"
    plan_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    incident_id: str = Field(min_length=1, max_length=120)
    complaint_id: str = Field(min_length=1)
    supervisor_decision_id: str = Field(min_length=1)
    planning_status: str = Field(min_length=1)
    dispatch_eligible: bool = False
    hold_reason_codes: list[str] = Field(default_factory=list)
    department: str = "SANITATION"
    priority: str = "MEDIUM"
    routing: RoutingInfo = Field(default_factory=RoutingInfo)
    location: PlanLocation
    template: TemplateReference | None = None
    objective: str | None = None
    tasks: list[SanitationTask] = Field(default_factory=list)
    resource_estimate: ResourceEstimate = Field(default_factory=ResourceEstimate)
    duration_estimate: DurationEstimate = Field(default_factory=DurationEstimate)
    safety_constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    policy_versions: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    previous_plan_id: str | None = None
    replan_reason: str | None = None


    @field_validator("created_at")
    @classmethod
    def created_at_must_be_aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value

    @model_validator(mode="after")
    def task_ids_and_dependencies_must_be_valid(self):
        task_ids = [task.task_id for task in self.tasks]
        sequences = [task.sequence for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task_id values must be unique")
        if len(sequences) != len(set(sequences)):
            raise ValueError("task sequence values must be unique")
        by_id = {task.task_id: task for task in self.tasks}
        for task in self.tasks:
            for dependency_id in task.depends_on:
                dependency = by_id.get(dependency_id)
                if dependency is None:
                    raise ValueError(f"task {task.task_id} depends on unknown task {dependency_id}")
                if dependency.sequence >= task.sequence:
                    raise ValueError(f"dependency {dependency_id} must appear before task {task.task_id}")
        return self


class WorkerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    worker_id: str = Field(min_length=1, max_length=120)
    reason: str = Field(default="", max_length=300)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _request_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _derive_worker_skills(payload: dict[str, Any]) -> list[str]:
    resource_estimate = payload.get("resource_estimate") or {}
    demand = resource_estimate.get("estimated_worker_demand") or {}
    skills = demand.get("roles") or []
    if isinstance(skills, str):
        skills = [skills]
    return sorted(set(skills))


def _gate_reasons(request: DispatchRequest) -> list[str]:
    """Fail closed when the upstream plan says Dispatch must hold."""
    reasons = list(request.hold_reason_codes)
    if request.dispatch_eligible is not True:
        reasons.append("PLAN_NOT_DISPATCH_ELIGIBLE")
    if request.planning_status != "PLAN_READY":
        reasons.append("PLAN_NOT_READY")
    if request.routing.status != "RESOLVED":
        reasons.append("ROUTING_UNRESOLVED")
    if (
        request.routing.facility_id
        and request.location.facility_id
        and request.routing.facility_id != request.location.facility_id
    ) or (
        request.routing.location_id
        and request.location.location_id
        and request.routing.location_id != request.location.location_id
    ):
        reasons.append("ROUTING_LOCATION_MISMATCH")
    if request.resource_estimate.status != "COMPLETE":
        reasons.append("RESOURCE_ESTIMATE_INCOMPLETE")
    if request.duration_estimate.status not in ("CALCULATED", "COMPLETE"):
        reasons.append("DURATION_ESTIMATE_INCOMPLETE")
    if not request.resource_estimate.estimated_worker_demand or not request.resource_estimate.estimated_worker_demand.get("roles"):
        reasons.append("WORKER_ROLE_UNKNOWN")
    if not request.tasks:
        reasons.append("TASKS_MISSING")
    return sorted(set(reasons))


def _target_location(payload: dict[str, Any]) -> dict[str, Any]:
    location = payload.get("location")
    return dict(location or {})


def _worker_details(worker: dict[str, Any]) -> dict[str, Any]:
    """Return useful worker profile data without exposing their GPS position."""
    details = {
        "worker_id": worker["worker_id"],
        "display_name": worker.get("name") or worker["worker_id"],
        "skills": list(worker.get("skills") or []),
        "equipment": list(worker.get("equipment") or []),
        "active_tasks": int(worker.get("active_tasks", 0)),
        "max_active_tasks": int(worker.get("max_active_tasks", 0)),
    }
    if worker.get("team_id") is not None:
        details["team_id"] = worker["team_id"]
    return details


def _notification_payload(record: dict[str, Any], offer: dict[str, Any]) -> dict[str, Any]:
    plan = record["request"]
    location = copy.deepcopy(record["target_location"])
    place = location.get("location_id") or location.get("facility_id") or plan["incident_id"]
    task_titles = [task.get("title") or task.get("task_name") for task in plan.get("tasks", [])]
    return {
        "type": "DISPATCH_OFFER",
        "offer_id": offer["offer_id"],
        "incident_id": plan["incident_id"],
        "department": plan.get("department"),
        "priority": plan.get("priority"),
        "title": f"{plan.get('department') or 'Field'} assignment near {place}",
        "objective": plan.get("objective") or "Respond to the assigned incident.",
        "task_titles": [title for title in task_titles if title],
        "destination": location,
        "navigation_target": {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "label": place,
        },
        "safety_constraints": list(plan.get("safety_constraints") or []),
        "acceptance_deadline": offer["acceptance_deadline"],
        "respond_to": f"/api/v1/dispatch/offers/{offer['offer_id']}/accept",
    }


def _record_view(record: dict[str, Any]) -> dict[str, Any]:
    result = {
        "incident_id": record["incident_id"],
        "plan_id": record.get("request", {}).get("plan_id"),
        "status": record["status"],
    }
    current_id = record.get("current_offer_id")
    if current_id:
        result["offer"] = _public_offer(offers[current_id])
    if record.get("assignment") is not None:
        result["assignment"] = copy.deepcopy(record["assignment"])
    if record.get("reason_codes"):
        result["reason_codes"] = list(record["reason_codes"])
    return result


def _public_offer(offer: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(offer)
    result.pop("_deadline", None)
    return result


def _release_reservation(worker_id: str) -> None:
    current = reserved_by_worker.get(worker_id, 0)
    if current <= 1:
        reserved_by_worker.pop(worker_id, None)
    else:
        reserved_by_worker[worker_id] = current - 1


def _offer_next_worker(record: dict[str, Any]) -> dict[str, Any] | None:
    plan = record["request"]
    location = record["target_location"]
    candidates = dispatch_task(
        latitude=location["latitude"],
        longitude=location["longitude"],
        required_skills=record["required_skills"],
        max_radius_km=record["max_radius_km"],
        reserved_by_worker=reserved_by_worker,
        excluded_worker_ids=set(record["attempted_worker_ids"]),
    )
    if not candidates:
        record["status"] = "UNASSIGNED"
        record["current_offer_id"] = None
        record["reason_codes"] = ["NO_ELIGIBLE_WORKER"]
        return None

    selected = candidates[0]
    now = _now()
    deadline = now + timedelta(seconds=OFFER_TIMEOUT_SECONDS)
    offer_id = f"OFF-{uuid4().hex}"
    offer = {
        "offer_id": offer_id,
        "incident_id": plan["incident_id"],
        "worker_id": selected["worker_id"],
        "worker": _worker_details(selected),
        "distance_km": selected["distance_km"],
        "status": "OFFERED",
        "offered_at": _iso(now),
        "acceptance_deadline": _iso(deadline),
        "notification": None,
        "_deadline": deadline,
    }
    offer["notification"] = _notification_payload(record, offer)
    offers[offer_id] = offer
    record["status"] = "OFFERED"
    record["current_offer_id"] = offer_id
    record["reason_codes"] = []
    reserved_by_worker[selected["worker_id"]] = reserved_by_worker.get(selected["worker_id"], 0) + 1
    return offer


def _build_assignment(record: dict[str, Any], offer: dict[str, Any], worker: dict[str, Any]) -> dict[str, Any]:
    plan = record["request"]
    now = _iso(_now())
    assignment_id = f"ASN-{uuid4().hex}"
    location = copy.deepcopy(record["target_location"])
    duration = plan.get("duration_estimate") or {}
    resources = plan.get("resource_estimate") or {}
    return {
        "contract_version": "1.0.0",
        "message_type": "FIELD_WORKER_TASK_ASSIGNMENT",
        "assignment": {
            "assignment_id": assignment_id,
            "dispatch_job_id": plan.get("event_id") or plan["incident_id"],
            "offer_id": offer["offer_id"],
            "incident_id": plan["incident_id"],
            "worker_id": worker["worker_id"],
            "status": "ACCEPTED",
            "accepted_at": now,
            "attempt_number": len(record["attempted_worker_ids"]) + 1,
        },
        "worker": _worker_details(worker),
        "incident": {
            "incident_id": plan["incident_id"],
            "plan_id": plan.get("plan_id"),
            "event_id": plan.get("event_id"),
            "complaint_id": plan.get("complaint_id"),
            "supervisor_decision_id": plan.get("supervisor_decision_id"),
            "priority": plan.get("priority"),
            "category": plan.get("department"),
            "department": plan.get("department"),
            "ward_id": (plan.get("routing") or {}).get("ward_id"),
            "facility_id": location.get("facility_id"),
            "location": location,
        },
        "task_package": {
            "package_id": f"PKG-{uuid4().hex}",
            "title": plan.get("objective") or f"Respond to incident {plan['incident_id']}",
            "objective": plan.get("objective"),
            "sla": {
                "response_due_at": duration.get("sla_response_due_at"),
                "resolution_due_at": duration.get("sla_resolution_due_at"),
            },
            "tasks": copy.deepcopy(plan.get("tasks") or []),
            "required_resources": copy.deepcopy(resources.get("required_resources") or []),
            "estimated_worker_demand": copy.deepcopy(resources.get("estimated_worker_demand")),
            "template": copy.deepcopy(plan.get("template") or {}),
            "safety_constraints": copy.deepcopy(plan.get("safety_constraints") or []),
            "completion_criteria": [
                criterion
                for task in plan.get("tasks") or []
                for criterion in task.get("completion_criteria") or []
            ],
        },
        "worker_actions": {
            "allowed_actions": ["ACKNOWLEDGE", "START_TASK", "UPDATE_CHECKLIST", "REPORT_BLOCKER", "SUBMIT_FOR_VERIFICATION"]
        },
        "handoff": {
            "source_module": "MODULE_05_DISPATCH",
            "target_module": "MODULE_06_FIELD_WORKER",
            "created_at": now,
            "schema_version": "1.0.0",
        },
    }


def _expire_offer(offer: dict[str, Any], *, at: datetime | None = None) -> None:
    if offer["status"] != "OFFERED":
        return
    record = dispatch_records[offer["incident_id"]]
    _release_reservation(offer["worker_id"])
    offer["status"] = "EXPIRED"
    offer["expired_at"] = _iso(at or _now())
    record["attempted_worker_ids"].append(offer["worker_id"])
    record["current_offer_id"] = None
    _offer_next_worker(record)


def _expire_due_offers_locked(now: datetime | None = None) -> None:
    now = now or _now()
    for offer in list(offers.values()):
        if offer["status"] == "OFFERED" and offer["_deadline"] <= now:
            _expire_offer(offer, at=now)


async def _offer_expiry_loop() -> None:
    while True:
        await asyncio.sleep(1)
        with dispatch_lock:
            _expire_due_offers_locked()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    expiry_task = asyncio.create_task(_offer_expiry_loop())
    try:
        yield
    finally:
        expiry_task.cancel()
        with suppress(asyncio.CancelledError):
            await expiry_task


app = FastAPI(title="KAVACH Dispatch Agent", lifespan=lifespan)


@app.get("/api/v1/dispatch/health")
def health():
    return {"status": "healthy"}


@app.get("/api/v1/workers")
def get_workers():
    with dispatch_lock:
        result = []
        for worker in list_workers():
            item = copy.deepcopy(worker)
            reserved = reserved_by_worker.get(worker["worker_id"], 0)
            item["reserved_tasks"] = reserved
            item["available_for_dispatch"] = bool(worker["available"]) and (
                worker["active_tasks"] + reserved < worker["max_active_tasks"]
            )
            result.append(item)
        return result


@app.post("/api/v1/dispatch/assign")
def assign_worker(request: DispatchRequest):
    payload = request.model_dump(mode="json", exclude_none=True)
    request_hash = _request_hash(payload)

    with dispatch_lock:
        _expire_due_offers_locked()
        existing = dispatch_records.get(request.incident_id)
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "DUPLICATE_PAYLOAD_CONFLICT",
                        "message": "This incident_id was already received with a different payload.",
                    },
                )
            return _record_view(existing)

        if request.event_id and request.event_id in dispatch_events:
            prior_incident_id = dispatch_events[request.event_id]
            prior = dispatch_records[prior_incident_id]
            if prior["request_hash"] != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "DUPLICATE_EVENT_CONFLICT",
                        "message": "This event_id was already received with a different payload.",
                    },
                )
            return _record_view(prior)

        target = _target_location(payload)
        required_skills = _derive_worker_skills(payload)
        record = {
            "incident_id": request.incident_id,
            "request_hash": request_hash,
            "request": payload,
            "target_location": target,
            "required_skills": required_skills,
            "max_radius_km": DISPATCH_MAX_RADIUS_KM,
            "attempted_worker_ids": [],
            "current_offer_id": None,
            "assignment": None,
            "reason_codes": [],
            "status": "READY",
        }
        dispatch_records[request.incident_id] = record
        if request.event_id:
            dispatch_events[request.event_id] = request.incident_id

        hold_reasons = _gate_reasons(request)
        if hold_reasons:
            record["status"] = "HOLD"
            record["reason_codes"] = hold_reasons
            return _record_view(record)

        offer = _offer_next_worker(record)
        if offer is None:
            return _record_view(record)
        return _record_view(record)


@app.get("/api/v1/workers/{worker_id}/offers")
def get_worker_offers(worker_id: str):
    """Worker-app polling endpoint; a push-provider adapter can use the same payload."""
    with dispatch_lock:
        _expire_due_offers_locked()
        return [
            _public_offer(offer)
            for offer in offers.values()
            if offer["worker_id"] == worker_id and offer["status"] == "OFFERED"
        ]


@app.get("/api/v1/dispatch/incidents/{incident_id}")
def get_dispatch_status(incident_id: str):
    with dispatch_lock:
        _expire_due_offers_locked()
        record = dispatch_records.get(incident_id)
        if record is None:
            raise HTTPException(status_code=404, detail="No dispatch record for this incident.")
        return _record_view(record)


@app.post("/api/v1/dispatch/offers/{offer_id}/accept")
def accept_offer(offer_id: str, decision: WorkerDecision):
    with dispatch_lock:
        _expire_due_offers_locked()
        offer = offers.get(offer_id)
        if offer is None:
            raise HTTPException(status_code=404, detail="Offer not found.")
        if offer["worker_id"] != decision.worker_id:
            raise HTTPException(status_code=403, detail="This offer belongs to another worker.")
        if offer["status"] == "ACCEPTED":
            return _record_view(dispatch_records[offer["incident_id"]])
        if offer["status"] != "OFFERED":
            raise HTTPException(status_code=409, detail=f"Offer is {offer['status']}.")
        if offer["_deadline"] <= _now():
            _expire_offer(offer)
            raise HTTPException(status_code=409, detail="Offer expired; Dispatch has moved to the next worker.")

        record = dispatch_records[offer["incident_id"]]
        worker = get_worker(decision.worker_id)
        if worker is None:
            _expire_offer(offer)
            raise HTTPException(status_code=409, detail="Worker is no longer available.")

        # Convert the reserved slot into an active task atomically.
        _release_reservation(worker["worker_id"])
        worker["active_tasks"] += 1
        offer["status"] = "ACCEPTED"
        offer["accepted_at"] = _iso(_now())
        offer.pop("_deadline", None)
        record["status"] = "ASSIGNED"
        record["current_offer_id"] = offer_id
        record["assignment"] = _build_assignment(record, offer, worker)
        record["reason_codes"] = []
        return _record_view(record)


@app.post("/api/v1/dispatch/offers/{offer_id}/reject")
def reject_offer(offer_id: str, decision: WorkerDecision):
    with dispatch_lock:
        _expire_due_offers_locked()
        offer = offers.get(offer_id)
        if offer is None:
            raise HTTPException(status_code=404, detail="Offer not found.")
        if offer["worker_id"] != decision.worker_id:
            raise HTTPException(status_code=403, detail="This offer belongs to another worker.")
        if offer["status"] != "OFFERED":
            raise HTTPException(status_code=409, detail=f"Offer is {offer['status']}.")

        record = dispatch_records[offer["incident_id"]]
        _release_reservation(offer["worker_id"])
        offer["status"] = "REJECTED"
        offer["rejected_at"] = _iso(_now())
        offer["rejection_reason"] = decision.reason
        offer.pop("_deadline", None)
        record["attempted_worker_ids"].append(offer["worker_id"])
        record["current_offer_id"] = None
        _offer_next_worker(record)
        return _record_view(record)
