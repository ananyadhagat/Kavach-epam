"""Demo data: three demo identities per role, and one synthetic incident so the
worker view isn't empty. All of it is flagged is_demo and the incident's
location is labelled SIMULATED; none of it is real field data."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from geosatya.models import IncidentRow, UserRow, WorkerProfileRow
from geosatya.services.common import Actor
from geosatya.services.incidents import create_incident, process_incident
from geosatya.synthetic_images import streetlight_scene
from geosatya.timeutil import utcnow

DEMO_USERS = [
    ("CIT-DEMO-01", "Aarav (citizen)", "CITIZEN"),
    ("CIT-DEMO-02", "Sana (citizen)", "CITIZEN"),
    ("W-DEMO-12", "Ravi (field worker)", "WORKER"),
    ("W-DEMO-15", "Meena (field worker)", "WORKER"),
    ("SUP-DEMO-03", "Priya (supervisor)", "SUPERVISOR"),
]
# A synthetic point in Bhopal, used only for the seeded incident.
DEMO_POINT = (23.259900, 77.412600)
# Dispatch needs skills per worker. Demo workers get these; no location is
# seeded: a worker's location exists only once they share it.
DEMO_SKILLS = {
    "W-DEMO-12": ["road_repair", "electrical", "general_maintenance", "drain_cleaning"],
    "W-DEMO-15": ["road_repair", "waste_collection", "drain_cleaning", "plumbing", "general_maintenance"],
}


def ensure_users(session: Session) -> None:
    for user_id, name, role in DEMO_USERS:
        if session.get(UserRow, user_id) is None:
            session.add(UserRow(user_id=user_id, display_name=name, role=role, is_demo=True))
    session.flush()
    ensure_worker_profiles(session)


def ensure_worker_profiles(session: Session) -> None:
    """Every worker gets a profile. Non-demo workers start with no skills, so
    Dispatch will not pick them until their skills are set."""
    for user in session.scalars(select(UserRow).where(UserRow.role == "WORKER")):
        if session.get(WorkerProfileRow, user.user_id) is None:
            session.add(WorkerProfileRow(user_id=user.user_id, skills=DEMO_SKILLS.get(user.user_id, []), equipment=[],
                                         available=True, max_active_tasks=3))
    session.flush()


def seed_demo_data(session: Session, storage, settings, categories) -> bool:
    ensure_users(session)
    if session.scalar(select(IncidentRow.incident_id).limit(1)) is not None:
        return False
    payload = {
        "category": "streetlight", "title": "Streetlight not working on pole SL-0147 (demo)",
        "description": "Synthetic demo report: the streetlight has been off for a week.",
        "asset_identifier": "SL-0147",
        "device_location": {"latitude": DEMO_POINT[0], "longitude": DEMO_POINT[1], "accuracy_m": 9.0,
                            "observed_at": utcnow(), "mode": "SIMULATED"},
    }
    photo = (streetlight_scene(1, lit=False), {"capture_source": "GALLERY", "uploaded_at": utcnow()})
    incident = create_incident(session, storage, settings, categories, Actor("CIT-DEMO-02", "CITIZEN"), payload, [photo],
                               is_demo=True)
    process_incident(session, storage, settings, categories, None, incident)  # no agent call for seed data
    return True
