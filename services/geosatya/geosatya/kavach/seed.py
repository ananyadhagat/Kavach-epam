"""KAVACH demo workspaces. Everything here is a clearly labelled sample:
fictional organization and event names, and jurisdictions that are rough
circles, not official boundary data. No worker locations are seeded; a
worker appears on a map only after sharing a real location."""

from datetime import timedelta

from sqlalchemy.orm import Session

from geosatya.kavach.service import _default_settings, ensure_plans
from geosatya.models import UserRow, WorkerProfileRow
from geosatya.platform_models import AuthorityRow, DepartmentRow, WorkspaceRow, ZoneRow
from geosatya.timeutil import utcnow

CITY = (23.259900, 77.412600)      # the same synthetic point GeoSatya's demo uses
EVENT = (23.248500, 77.394200)     # a nearby sample venue
SAMPLE_NOTE = "Sample jurisdiction for the demo. Not official boundary data."

USERS = [
    # user_id, name, role, platform_role, workspace_id, department_id, skills
    ("PA-DEMO-01", "Neha (platform admin)", "SUPERVISOR", "PLATFORM_ADMIN", None, None, None),
    ("ORG-DEMO-01", "Kavya (org admin)", "SUPERVISOR", "ORG_ADMIN", "WS-DEMO-ORG", None, None),
    ("OSUP-DEMO-01", "Farhan (roads supervisor)", "SUPERVISOR", None, "WS-DEMO-ORG", "DEP-DEMO-ROADS", None),
    ("OW-DEMO-21", "Imran (road crew)", "WORKER", None, "WS-DEMO-ORG", "DEP-DEMO-ROADS",
     ["road_repair", "general_maintenance", "electrical"]),
    ("OW-DEMO-22", "Lakshmi (sanitation)", "WORKER", None, "WS-DEMO-ORG", "DEP-DEMO-SAN",
     ["waste_collection", "drain_cleaning", "plumbing", "general_maintenance"]),
    ("EO-DEMO-01", "Arjun (event organizer)", "SUPERVISOR", "EVENT_ORGANIZER", "WS-DEMO-EVT", None, None),
    ("EW-DEMO-31", "Kabir (first aid)", "WORKER", None, "WS-DEMO-EVT", None, ["first_aid", "crowd_control"]),
    ("EW-DEMO-32", "Zoya (security)", "WORKER", None, "WS-DEMO-EVT", None,
     ["security", "crowd_control", "general_maintenance", "waste_collection"]),
]


def seed_kavach_demo(session: Session) -> None:
    ensure_plans(session)
    if session.get(WorkspaceRow, "WS-DEMO-ORG") is not None:
        return
    now = utcnow()
    for user_id, name, role, platform_role, *_ in USERS:
        if session.get(UserRow, user_id) is None:
            session.add(UserRow(user_id=user_id, display_name=name, role=role, is_demo=True, platform_role=platform_role))
    session.flush()

    org = WorkspaceRow(workspace_id="WS-DEMO-ORG", kind="ORGANIZATION", name="Demo City Municipal Corporation (sample)",
                       category="MUNICIPAL_BODY", organization_name="Demo City Municipal Corporation",
                       description="A fictional municipal body used to demonstrate autonomous organization operations.",
                       owner_id="ORG-DEMO-01", verification_status="DEMO", venue="Demo City",
                       center_latitude=CITY[0], center_longitude=CITY[1], radius_m=12000,
                       settings=_default_settings("ORGANIZATION"), plan_id="ORG_STANDARD", subscription_status="DEMO",
                       created_at=now, is_demo=True)
    event_settings = _default_settings("EVENT")
    evt = WorkspaceRow(workspace_id="WS-DEMO-EVT", kind="EVENT", name="City Half Marathon 2026 (sample)", category="SPORTS",
                       organization_name="Demo Events Co.", owner_id="EO-DEMO-01", verification_status="UNVERIFIED",
                       description="A fictional race used to demonstrate event workforce and incident management.",
                       venue="Lakeside start/finish (sample)", center_latitude=EVENT[0], center_longitude=EVENT[1], radius_m=2500,
                       starts_at=now - timedelta(hours=1), ends_at=now + timedelta(days=2), settings=event_settings,
                       plan_id="EVENT_PASS", subscription_status="DEMO", created_at=now, is_demo=True)
    session.add_all([org, evt])
    session.flush()
    session.add_all([
        DepartmentRow(department_id="DEP-DEMO-ROADS", workspace_id=org.workspace_id, name="Roads & Infrastructure",
                      description="Potholes, road damage, public infrastructure and streetlights.",
                      categories=["road_damage", "infrastructure", "streetlight", "safety_hazard"],
                      supervisor_id="OSUP-DEMO-01", created_at=now),
        DepartmentRow(department_id="DEP-DEMO-SAN", workspace_id=org.workspace_id, name="Sanitation & Water",
                      description="Garbage, drainage and water leakage.", categories=["garbage", "drainage", "water_leakage"],
                      created_at=now),
        ZoneRow(zone_id="ZN-DEMO-START", workspace_id=evt.workspace_id, name="Start / Finish", kind="STAGE",
                latitude=EVENT[0], longitude=EVENT[1], radius_m=150, created_at=now),
        ZoneRow(zone_id="ZN-DEMO-MED", workspace_id=evt.workspace_id, name="Medical tent", kind="MEDICAL",
                latitude=EVENT[0] + 0.0016, longitude=EVENT[1] + 0.0012, radius_m=60, created_at=now),
        ZoneRow(zone_id="ZN-DEMO-WATER", workspace_id=evt.workspace_id, name="Water station 1", kind="SERVICE",
                latitude=EVENT[0] - 0.0060, longitude=EVENT[1] + 0.0080, radius_m=80, created_at=now),
    ])
    session.flush()
    for user_id, _name, role, _pr, workspace_id, department_id, skills in USERS:
        user = session.get(UserRow, user_id)
        user.workspace_id, user.department_id = workspace_id, department_id
        if role == "WORKER" and session.get(WorkerProfileRow, user_id) is None:
            session.add(WorkerProfileRow(user_id=user_id, skills=skills or [], equipment=[], available=True, max_active_tasks=3))
    session.add_all([
        AuthorityRow(authority_id="AUTH-DEMO-MUN", name="Demo City Municipal Corporation (sample)", kind="MUNICIPAL",
                     center_latitude=CITY[0], center_longitude=CITY[1], radius_km=12, categories=[], road_types=[],
                     workspace_id=org.workspace_id, integration="NONE", data_note=SAMPLE_NOTE, is_demo=True),
        AuthorityRow(authority_id="AUTH-DEMO-NH", name="National Highway Division (sample)", kind="NATIONAL_HIGHWAY",
                     center_latitude=CITY[0], center_longitude=CITY[1], radius_km=80,
                     categories=["road_damage", "safety_hazard", "streetlight", "infrastructure"], road_types=["NATIONAL_HIGHWAY"],
                     integration="NONE", contact="Forward manually through the authority's own complaint channel.",
                     data_note=SAMPLE_NOTE, is_demo=True),
        AuthorityRow(authority_id="AUTH-DEMO-SH", name="State Highway Division (sample)", kind="STATE_HIGHWAY",
                     center_latitude=CITY[0], center_longitude=CITY[1], radius_km=80,
                     categories=["road_damage", "safety_hazard", "streetlight", "infrastructure"], road_types=["STATE_HIGHWAY"],
                     integration="NONE", contact="Forward manually through the authority's own complaint channel.",
                     data_note=SAMPLE_NOTE, is_demo=True),
    ])
    session.flush()
