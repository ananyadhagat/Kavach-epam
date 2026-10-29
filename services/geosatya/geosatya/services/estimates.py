"""ETA (when the worker may reach the incident) and ETR (when the incident
may be resolved). They are separate numbers and never merged.

ETA is approximate. No road-routing service is configured, so remaining
distance is the straight-line distance multiplied by a road factor
(ETA_ROUTE_FACTOR, default 1.4) and divided by a speed: the speed the worker
was actually observed approaching at, if the shared locations show it, else
an assumed speed (ETA_ASSUMED_SPEED_KMH, default 20). It is shown as a range
rounded to minutes, never as a precise time.

ETR is recomputed only on events (assignment, arrival, work start, completion
submitted, rework, reassignment). Its work duration is the median of resolved
tasks in the same category once enough exist, else the category's baseline
in categories.json. Actual durations come from recorded timestamps only.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timedelta

from sqlalchemy import select

from geosatya.models import IncidentRow, LocationPingRow, TaskProgressRow, TaskRow
from geosatya.timeutil import as_utc, iso, utcnow

ACTIVE = ("ASSIGNED", "IN_PROGRESS")


# ------------------------------------------------------------------ ETA
def observed_speed_mps(pings: list[LocationPingRow]) -> float | None:
    """Approach speed toward the target from the shared locations: the drop in
    distance between the latest ping and one at least 60 s older (within 10 min)."""
    if len(pings) < 2:
        return None
    latest = pings[-1]
    t1 = as_utc(latest.received_at)
    for older in reversed(pings[:-1]):
        dt = (t1 - as_utc(older.received_at)).total_seconds()
        if 60 <= dt <= 600:
            speed = (older.distance_to_target_m - latest.distance_to_target_m) / dt
            return min(speed, 20.0) if speed >= 0.5 else None
    return None


def eta(task: TaskRow, progress: TaskProgressRow | None, pings: list[LocationPingRow], settings,
        now: datetime | None = None) -> dict:
    now = now or utcnow()
    base = {"method": "APPROXIMATE_STRAIGHT_LINE", "route_factor": settings.eta_route_factor,
            "computed_at": iso(now), "minutes_low": None, "minutes_high": None, "eta_at_low": None,
            "eta_at_high": None, "distance_m": None, "location_age_s": None, "speed_source": None, "uncertain": True}
    if task.status not in ACTIVE:
        return {**base, "state": "NOT_APPLICABLE", "message": "The worker is no longer travelling to this task."}
    if progress is not None and progress.arrived_at is not None:
        return {**base, "state": "ARRIVED", "message": "The worker has reached the incident area.",
                "arrived_at": iso(progress.arrived_at)}
    if task.status == "IN_PROGRESS":
        return {**base, "state": "ARRIVED", "message": "Work has started at the site.", "arrived_at": None}
    if not pings:
        return {**base, "state": "WAITING_FOR_LOCATION",
                "message": "Waiting for the worker to share their location. ETA unavailable."}

    latest = pings[-1]
    age = (now - as_utc(latest.received_at)).total_seconds()
    distance = latest.distance_to_target_m
    speed = observed_speed_mps(pings)
    source = "OBSERVED_APPROACH" if speed else "ASSUMED"
    speed = speed or settings.eta_assumed_speed_kmh / 3.6
    minutes = distance * settings.eta_route_factor / speed / 60
    low = max(1, round(minutes * 0.8))
    high = max(low + 1, math.ceil(minutes * 1.3))
    stale = age > settings.tracking_stale_s
    poor = (latest.accuracy_m or 0) > 100
    data = {**base, "distance_m": round(distance), "location_age_s": int(age), "speed_source": source,
            "minutes_low": low, "minutes_high": high,
            "eta_at_low": iso(as_utc(latest.received_at) + timedelta(minutes=low)),
            "eta_at_high": iso(as_utc(latest.received_at) + timedelta(minutes=high)),
            "uncertain": stale or poor or source == "ASSUMED"}
    if stale:
        return {**data, "state": "STALE",
                "message": "Location update is stale; this estimate is based on the last known position and may be wrong."}
    msg = "Approximate: straight-line distance with a road allowance, not turn-by-turn routing. Arrival estimate may change."
    if poor:
        msg = "GPS accuracy is poor, so the distance is uncertain. " + msg
    return {**data, "state": "AVAILABLE", "message": msg}


# ------------------------------------------------------------------ ETR
def work_minutes(session, categories, category: str, settings) -> tuple[float, str, int]:
    """Median on-site work duration of resolved tasks in this category, or the baseline."""
    rows = session.execute(
        select(TaskProgressRow.work_started_at, TaskProgressRow.completion_submitted_at)
        .join(TaskRow, TaskRow.task_id == TaskProgressRow.task_id)
        .join(IncidentRow, IncidentRow.incident_id == TaskRow.incident_id)
        .where(IncidentRow.category == category, TaskRow.status == "RESOLVED",
               TaskProgressRow.work_started_at.is_not(None), TaskProgressRow.completion_submitted_at.is_not(None))).all()
    samples = [(as_utc(b) - as_utc(a)).total_seconds() / 60 for a, b in rows if b > a]
    if len(samples) >= settings.etr_history_min_samples:
        return statistics.median(samples), "HISTORICAL_MEDIAN", len(samples)
    baseline = ((categories.get(category) or {}).get("dispatch") or {}).get("work_minutes", 60)
    return float(baseline), "CATEGORY_BASELINE", len(samples)


def recompute_etr(session, settings, categories, task: TaskRow, incident: IncidentRow, progress: TaskProgressRow,
                  event: str, eta_info: dict | None = None, now: datetime | None = None) -> None:
    now = now or utcnow()
    work, work_source, samples = work_minutes(session, categories, incident.category, settings)
    review = settings.etr_review_buffer_min
    notes, travel, travel_source = [], 0.0, None
    if event == "RESOLVED":
        progress.etr_due_at = None
        progress.etr_basis = {"approximate": False, "notes": ["Resolved: see the actual resolution time."]}
    else:
        if event == "COMPLETION_SUBMITTED":
            start, work_left = as_utc(progress.completion_submitted_at) or now, 0.0
        elif progress.work_started_at is not None and task.status == "IN_PROGRESS":
            start, work_left = as_utc(progress.work_started_at), work
        else:
            start, work_left = now, work
            if progress.arrived_at is None:
                if eta_info and eta_info.get("minutes_high"):
                    travel, travel_source = float(eta_info["minutes_high"]), "ETA_UPPER_BOUND"
                else:
                    travel, travel_source = float(settings.etr_default_travel_min), "DEFAULT_ALLOWANCE"
                    notes.append("Worker location unknown: a default travel allowance is used.")
        if work_source == "CATEGORY_BASELINE":
            notes.append(f"No history yet ({samples} resolved task(s) in this category): the category baseline is used.")
        due = start + timedelta(minutes=travel + work_left + review)
        progress.etr_due_at = max(due, now)
        progress.etr_basis = {"approximate": True, "travel_min": round(travel), "travel_source": travel_source,
                              "work_min": round(work_left), "work_source": work_source, "history_samples": samples,
                              "review_min": review, "notes": notes}
    progress.etr_event, progress.etr_updated_at = event, now


def etr_view(task: TaskRow | None, progress: TaskProgressRow | None, incident: IncidentRow, now: datetime | None = None) -> dict:
    now = now or utcnow()
    if task is None or progress is None:
        return {"state": "UNAVAILABLE", "message": "No field task yet, so no resolution estimate.",
                "approximate": True, "due_at": None}
    if task.status == "RESOLVED" and progress.resolved_at is not None:
        return {"state": "RESOLVED", "message": "Resolved.", "approximate": False, "due_at": None,
                "actual": actual_durations(incident, task, progress)}
    if progress.etr_due_at is None:
        return {"state": "UNAVAILABLE", "message": "Estimate unavailable.", "approximate": True, "due_at": None}
    remaining = (as_utc(progress.etr_due_at) - now).total_seconds() / 60
    overdue = remaining < 0
    return {"state": "OVERDUE" if overdue else "ESTIMATED", "approximate": True, "due_at": iso(progress.etr_due_at),
            "remaining_min": max(0, round(remaining)), "updated_at": iso(progress.etr_updated_at),
            "updated_on": progress.etr_event, "basis": progress.etr_basis,
            "message": ("Taking longer than estimated." if overdue else
                        "Approximate estimate, not a deadline. It is updated when the work moves to a new stage.")}


def _minutes(a, b):
    a, b = as_utc(a), as_utc(b)
    return round((b - a).total_seconds() / 60, 1) if a and b and b >= a else None


def actual_durations(incident: IncidentRow, task: TaskRow, progress: TaskProgressRow) -> dict:
    """From recorded timestamps only. Missing milestones stay null."""
    return {"total_min": _minutes(incident.created_at, progress.resolved_at),
            "to_assignment_min": _minutes(incident.created_at, task.assigned_at),
            "travel_min": _minutes(progress.tracking_started_at, progress.arrived_at),
            "work_min": _minutes(progress.work_started_at, progress.completion_submitted_at),
            "review_min": _minutes(progress.completion_submitted_at, progress.resolved_at),
            "reported_at": iso(incident.created_at), "resolved_at": iso(progress.resolved_at)}
