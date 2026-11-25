"""Team live demo (TEAM_DEMO=1, development only, with AUTH_MODE=demo).

Runs on its own database file, so no existing record is touched. The app then has exactly the
ten Team Codyssey members: Namrata supervises the open civic team, three citizens report, and six
field workers take the jobs. The built-in sample identities that the base seeding always creates
are switched off in this database (is_active = False), never deleted, so the people list, the
login list and dispatch only ever see the team.

The login screen in this mode only looks like a sign-in: any password is accepted. It exists so
the demo is easy to follow on everyone's phone; real sign-in (AUTH_MODE=jwt) is unchanged.
"""

from __future__ import annotations

from sqlalchemy import select

from geosatya.models import UserRow, WorkerProfileRow

# Every skill and piece of equipment any category asks for, so any complaint can go to any team worker.
ALL_SKILLS = ["crowd_control", "drain_cleaning", "electrical", "first_aid", "general_maintenance", "plumbing",
              "road_repair", "security", "waste_collection"]

TEAM_USERS = [
    ("TEAM-NAMRATA", "Namrata Digarse", "SUPERVISOR"),
    ("TEAM-DIVYANSH", "Divyansh Kackker", "CITIZEN"),
    ("TEAM-SHREYA", "Shreya Kaushik", "CITIZEN"),
    ("TEAM-SHWETA", "Shweta Mishra", "CITIZEN"),
    ("TEAM-KAVYANSH", "Kavyansh Gupta", "WORKER"),
    ("TEAM-YASH", "Yash Dadlani", "WORKER"),
    ("TEAM-SHUBHRIT", "Shubhrit Tiwari", "WORKER"),
    ("TEAM-ANANYA", "Ananya Dhagat", "WORKER"),
    ("TEAM-KARANVEER", "Karanveer Singh Malhotra", "WORKER"),
    ("TEAM-OM", "Om Gupta", "WORKER"),
]
TEAM_IDS = {u for u, _, _ in TEAM_USERS}


def seed_team(session) -> None:
    for user_id, name, role in TEAM_USERS:
        user = session.get(UserRow, user_id)
        if user is None:
            session.add(UserRow(user_id=user_id, display_name=name, role=role, is_demo=True))
        else:
            user.display_name, user.role, user.is_active = name, role, None
    session.flush()
    for user_id, _, role in TEAM_USERS:
        if role != "WORKER":
            continue
        prof = session.get(WorkerProfileRow, user_id)
        if prof is None:
            session.add(WorkerProfileRow(user_id=user_id, skills=list(ALL_SKILLS), equipment=[], available=True, max_active_tasks=3))
        else:
            prof.skills = list(ALL_SKILLS)
    # Everyone else in this team database (the base sample identities) is switched off, not deleted.
    for user in session.scalars(select(UserRow).where(UserRow.user_id.not_in(TEAM_IDS))):
        user.is_active = False
    session.flush()
