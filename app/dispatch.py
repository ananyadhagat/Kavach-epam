"""Eligibility filtering and low-latency nearest-worker selection."""

import math
from datetime import datetime, timezone


def calculate_distance(lat1, lon1, lat2, lon2):
    """Return straight-line distance in kilometres (Haversine)."""
    earth_radius = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    a = min(1.0, max(0.0, a))
    return earth_radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def dispatch_task(
    latitude,
    longitude,
    required_skills,
    max_radius_km=10,
    reserved_by_worker=None,
    excluded_worker_ids=None,
    now=None,
):
    """Return eligible candidates ordered by nearest distance.

    Filtering is hard-gated before ranking. Active offers count against worker
    capacity so concurrent incidents cannot reserve the same final slot.
    """
    from app.data import list_workers

    now = now or datetime.now(timezone.utc)
    reserved_by_worker = reserved_by_worker or {}
    excluded_worker_ids = excluded_worker_ids or set()
    required_skills = set(required_skills or [])
    nearest = None
    nearest_key = None

    for worker in list_workers():
        worker_id = worker["worker_id"]
        if worker_id in excluded_worker_ids:
            continue
        if not worker.get("available", False):
            continue

        active = int(worker.get("active_tasks", 0))
        maximum = int(worker.get("max_active_tasks", 0))
        reserved = int(reserved_by_worker.get(worker_id, 0))
        if maximum <= 0 or active + reserved >= maximum:
            continue
        if not required_skills.issubset(set(worker.get("skills") or [])):
            continue
        last_updated = worker.get("location_updated_at")
        worker_latitude, worker_longitude = worker.get("latitude"), worker.get("longitude")
        if last_updated is None or worker_latitude is None or worker_longitude is None:
            continue
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=timezone.utc)
        age_seconds = (now - last_updated.astimezone(timezone.utc)).total_seconds()
        if age_seconds < 0 or age_seconds > 15 * 60:
            continue

        distance = calculate_distance(
            latitude, longitude, worker_latitude, worker_longitude
        )
        if distance > max_radius_km:
            continue

        candidate = worker.copy()
        candidate["distance_km"] = round(distance, 3)
        candidate["reserved_tasks"] = reserved
        # One pass is O(number of workers) time and O(1) candidate memory.
        # Worker ID makes exact-distance ties deterministic.
        key = (distance, worker_id)
        if nearest_key is None or key < nearest_key:
            nearest, nearest_key = candidate, key

    # Dispatch sends one offer at a time; after a decline/timeout it invokes
    # this again with the previous worker excluded.
    return [nearest] if nearest is not None else []
