"""Tenant scope for queries. A supervisor sees only the incidents, tasks and
workers of their own workspace; workspace None is the open civic workspace
GeoSatya has always served, so existing data and behaviour are unchanged."""

from sqlalchemy import select

from geosatya.models import IncidentRow, UserRow


def incident_in(workspace_id: str | None):
    return IncidentRow.workspace_id.is_(None) if workspace_id is None else IncidentRow.workspace_id == workspace_id


def user_in(workspace_id: str | None):
    return UserRow.workspace_id.is_(None) if workspace_id is None else UserRow.workspace_id == workspace_id


def incident_ids_in(workspace_id: str | None):
    return select(IncidentRow.incident_id).where(incident_in(workspace_id))


def same_workspace(a: str | None, b: str | None) -> bool:
    return (a or None) == (b or None)


def is_active(user: UserRow) -> bool:
    return user.is_active is not False
