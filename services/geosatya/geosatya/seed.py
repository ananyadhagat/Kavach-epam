"""Demo data: three demo identities per role, and one synthetic incident so the
worker view isn't empty. All of it is flagged is_demo and the incident's
location is labelled SIMULATED; none of it is real field data."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from geosatya.models import IncidentRow, UserRow
from geosatya.services.common import Actor
from geosatya.services.incidents import create_incident
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


def ensure_users(session: Session) -> None:
    for user_id, name, role in DEMO_USERS:
        if session.get(UserRow, user_id) is None:
            session.add(UserRow(user_id=user_id, display_name=name, role=role, is_demo=True))
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
    create_incident(session, storage, settings, categories, Actor("CIT-DEMO-02", "CITIZEN"), payload, [photo], is_demo=True)
    return True
