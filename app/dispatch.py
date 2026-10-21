
from math import radians, sin, cos, asin, sqrt
from datetime import datetime, timezone


def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate approximate straight-line distance in kilometres."""
    earth_radius_km = 6371.0

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )

    return 2 * earth_radius_km * asin(sqrt(min(1.0, a)))


def dispatch_task(task, workers):
    """Filter ineligible workers and rank the remaining candidates."""
    candidates = []
    rejected = []

    for worker in workers:
        reasons = []

        if not worker["available"]:
            reasons.append("Worker unavailable")

        if worker["active_tasks"] >= worker["max_active_tasks"]:
            reasons.append("Worker capacity reached")

        if not set(task["required_skills"]).issubset(worker["skills"]):
            reasons.append("Required skills missing")

        if not set(task["required_equipment"]).issubset(
            worker["equipment"]
        ):
            reasons.append("Required equipment missing")

        age_seconds = (
            datetime.now(timezone.utc)
            - worker["location_updated_at"]
        ).total_seconds()

        if age_seconds < 0 or age_seconds > 900:
            reasons.append("Location is stale")

        distance = haversine_km(
            task["latitude"],
            task["longitude"],
            worker["latitude"],
            worker["longitude"],
        )

        if distance > task["max_radius_km"]:
            reasons.append("Outside dispatch radius")

        if reasons:
            rejected.append({
                "worker_id": worker["worker_id"],
                "reasons": reasons,
            })
            continue

        distance_score = distance / task["max_radius_km"]
        workload_score = (
            worker["active_tasks"] / worker["max_active_tasks"]
        )

        total_score = (
            0.70 * distance_score
            + 0.30 * workload_score
        )

        candidates.append({
            "worker_id": worker["worker_id"],
            "worker_name": worker["name"],
            "distance_km": round(distance, 3),
            "active_tasks": worker["active_tasks"],
            "distance_score": round(distance_score, 4),
            "workload_score": round(workload_score, 4),
            "score": round(total_score, 4),
        })

    # Lower score is better; worker ID breaks ties deterministically.
    candidates.sort(
        key=lambda candidate: (
            candidate["score"],
            candidate["worker_id"],
        )
    )

    return {
        "candidates": candidates,
        "rejected_workers": rejected,
    }
