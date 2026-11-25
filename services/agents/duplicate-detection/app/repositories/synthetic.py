"""Deterministic synthetic complaint fixtures.

These are **fictional** records for exercising the repository and, later, the
comparators. They do not represent real-world data and must not be used to claim
model accuracy. IDs, categories, locations and timestamps are all synthetic.

The set intentionally includes cases that future tests need:

* waste overflow at a main entrance (``CMP-2026-0101``),
* a differently worded report of the same overflow at the same location
  (``CMP-2026-0102``) — a likely duplicate,
* a blocked drainage complaint at another site (``CMP-2026-0103``),
* a broken streetlight at a clearly different location (``CMP-2026-0104``),
* two road-damage reports at the same location with different timestamps
  (``CMP-2026-0105``, ``CMP-2026-0106``),
* a record with all optional fields missing (``CMP-2026-0107``).
"""

from __future__ import annotations

from datetime import datetime

from app.schemas.complaint import Complaint, Location

_MARKET = Location(
    facility_id="FAC-CENTRAL-MARKET",
    location_id="LOC-CM-GATE-NORTH",
    latitude=12.971598,
    longitude=77.594566,
)


def synthetic_incidents() -> list[Complaint]:
    """Return a fresh list of deterministic synthetic complaint records.

    A new list of new objects is returned on each call so tests cannot leak
    mutations between one another.
    """
    return [
        Complaint(
            complaint_id="CMP-2026-0101",
            description=(
                "Garbage bins are overflowing at the main entrance of Central "
                "Market and waste is spilling onto the footpath."
            ),
            category="WASTE_MANAGEMENT",
            location=_MARKET.model_copy(deep=True),
            reported_at=datetime.fromisoformat("2026-10-14T08:30:00+05:30"),
        ),
        Complaint(
            complaint_id="CMP-2026-0102",
            description=(
                "Waste containers at the Central Market north gate are full and "
                "rubbish has spread across the pavement."
            ),
            category="WASTE_MANAGEMENT",
            location=Location(
                facility_id="FAC-CENTRAL-MARKET",
                location_id="LOC-CM-GATE-NORTH",
                latitude=12.971600,
                longitude=77.594570,
            ),
            reported_at=datetime.fromisoformat("2026-10-14T09:05:00+05:30"),
        ),
        Complaint(
            complaint_id="CMP-2026-0103",
            description=(
                "Storm drain is blocked near Ward 10 Park, causing water to pool "
                "at the bus stop."
            ),
            category="DRAINAGE",
            location=Location(
                facility_id="FAC-WARD10-PARK",
                location_id="LOC-WP-BUSSTOP",
                latitude=12.935200,
                longitude=77.624500,
            ),
            reported_at=datetime.fromisoformat("2026-10-12T17:45:00+05:30"),
        ),
        Complaint(
            complaint_id="CMP-2026-0104",
            description=(
                "Street light is not working on 5th Avenue, pole number A-23, "
                "and the road is dark at night."
            ),
            category="STREETLIGHT",
            location=Location(
                facility_id="FAC-5TH-AVENUE",
                location_id="LOC-5A-POLE-A23",
                latitude=12.960100,
                longitude=77.610200,
            ),
            reported_at=datetime.fromisoformat("2026-10-13T21:10:00+05:30"),
        ),
        Complaint(
            complaint_id="CMP-2026-0105",
            description=(
                "Large pothole at the Central Market north gate causing "
                "two-wheeler accidents in the rain."
            ),
            category="ROAD_DAMAGE",
            location=_MARKET.model_copy(deep=True),
            reported_at=datetime.fromisoformat("2026-10-14T07:00:00+05:30"),
        ),
        Complaint(
            complaint_id="CMP-2026-0106",
            description=(
                "Deep pothole at the Central Market north gate; bikes are "
                "skidding when it rains."
            ),
            category="ROAD_DAMAGE",
            location=Location(
                facility_id="FAC-CENTRAL-MARKET",
                location_id="LOC-CM-GATE-NORTH",
                latitude=12.971700,
                longitude=77.594600,
            ),
            reported_at=datetime.fromisoformat("2026-10-16T18:30:00+05:30"),
        ),
        Complaint(
            complaint_id="CMP-2026-0107",
            # Intentionally all-optional-fields-missing record.
            description=None,
            category=None,
            location=None,
            reported_at=None,
            image_hash=None,
        ),
    ]
