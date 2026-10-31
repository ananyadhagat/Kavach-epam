import math
from datetime import datetime, timezone


def calculate_distance(lat1, lon1, lat2, lon2):

    earth_radius = 6371

    lat1, lon1, lat2, lon2 = map(
        math.radians,
        [lat1, lon1, lat2, lon2]
    )

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return earth_radius * c


def dispatch_task(
    latitude,
    longitude,
    required_skills,
    required_equipment,
    max_radius_km=10
):

    from app.data import workers

    candidates = []

    for worker in workers:

        if not worker["available"]:
            continue

        if worker["active_tasks"] >= worker["max_active_tasks"]:
            continue

        if not set(required_skills).issubset(set(worker["skills"])):
            continue

        if not set(required_equipment).issubset(set(worker["equipment"])):
            continue

        last_updated = worker["location_updated_at"]

        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=timezone.utc)

        age_minutes = (
            datetime.now(timezone.utc) - last_updated
        ).total_seconds() / 60

        if age_minutes > 15:
            continue

        distance = calculate_distance(
            latitude,
            longitude,
            worker["latitude"],
            worker["longitude"]
        )

        if distance > max_radius_km:
            continue

        worker_copy = worker.copy()
        worker_copy["distance_km"] = round(distance, 2)

        candidates.append(worker_copy)

    candidates.sort(
        key=lambda w: (
            w["distance_km"],
            w["active_tasks"] / w["max_active_tasks"],
            w["worker_id"]
        )
    )

    return candidates