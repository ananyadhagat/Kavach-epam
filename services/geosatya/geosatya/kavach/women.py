"""KAVACH Women's Safety: Trusted Allies and SOS.

Privacy rules (enforced here, on the server):
- Allies, SOS history and locations belong to the signed-in user only. They are kept in their own
  tables, never in the shared audit log, never in public statistics, and no supervisor or
  admin endpoint reads them.
- Location is only shared after the user adds an ally with explicit consent AND triggers an SOS.
  There is no background tracking: updates arrive only while the user's SOS screen is open and
  the SOS is ACTIVE. Cancelling or resolving stops sharing at once; an SOS left open is closed
  after SOS_MAX_ACTIVE_HOURS.
- The location an ally sees comes from the phone's real GPS. Simulated fixes are refused. A hand-
  placed point is allowed only as a clearly labelled fallback ("not GPS").
- No delivery provider (SMS, WhatsApp, push) is connected. Notification rows therefore stay
  PENDING_INTEGRATION and are never shown as delivered; the user sends the private link from
  their own phone (share sheet / WhatsApp / SMS buttons).
"""

from __future__ import annotations

import re
import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from geosatya.api.deps import get_actor, get_session
from geosatya.api.schemas import DeviceError, DeviceLocation, UserLocation
from geosatya.models import UserRow
from geosatya.platform_models import SosEventRow, SosNotificationRow, SosRow, TrustedAllyRow
from geosatya.ratelimit import SlidingWindowLimiter
from geosatya.services.common import Actor, ServiceError, new_id
from geosatya.timeutil import as_utc, iso, utcnow
from geosatya.kavach.audio import sos_notes

router = APIRouter(prefix="/women", tags=["Women's safety"])
_LIMITS = {"trigger": 6, "update": 40, "share": 60}


def _limiter(request: Request, name: str) -> SlidingWindowLimiter:
    """One limiter per app instance (not shared across processes' apps or tests)."""
    store = request.app.state.__dict__.setdefault("women_limiters", {})
    if name not in store:
        store[name] = SlidingWindowLimiter(_LIMITS[name])
    return store[name]

RELATIONSHIPS = {"PARENT": "Parent", "SIBLING": "Brother or sister", "PARTNER": "Husband or partner", "FRIEND": "Friend",
                 "FAMILY": "Other family member", "OTHER": "Other trusted person"}
EMERGENCY_NUMBERS = [
    {"number": "100", "label": "Police", "tel": "tel:100"},
    {"number": "108", "label": "Ambulance", "tel": "tel:108"},
    {"number": "112", "label": "Emergency helpline", "tel": "tel:112"},
]
DISCLAIMER = ("KAVACH does not replace the police, ambulance or emergency services. In danger, call 112 first. "
              "KAVACH only helps you share your location with the people you trust.")
STATUS_TEXT = {"ACTIVE": "SOS active", "CANCELLED": "Cancelled by you", "RESOLVED": "Ended: you are safe", "EXPIRED": "Closed automatically"}
DELIVERY_TEXT = {
    "PENDING_INTEGRATION": "Not sent yet. SMS and WhatsApp are not connected to KAVACH, so send this link from your own phone.",
    "SENT": "Sent", "FAILED": "Could not be sent",
}
PHONE_RE = re.compile(r"^\+?\d{7,15}$")


def _client(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")


def _citizen(actor: Actor) -> Actor:
    if actor.role != "CITIZEN":
        raise ServiceError("Women's safety is part of the citizen account.", 403, "FORBIDDEN")
    return actor


def _event(session, sos_id: str, event: str, **details) -> None:
    session.add(SosEventRow(event_id=new_id("SEV", 5), sos_id=sos_id, event=event, at=utcnow(), details=details))


# ------------------------------------------------------------------- schemas
class AllyIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=7, max_length=24)
    relationship: Literal["PARENT", "SIBLING", "PARTNER", "FRIEND", "FAMILY", "OTHER"]
    consent: bool = False


class AllyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=2, max_length=80)
    phone: str | None = Field(default=None, min_length=7, max_length=24)
    relationship: Literal["PARENT", "SIBLING", "PARTNER", "FRIEND", "FAMILY", "OTHER"] | None = None


class SosTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["BUTTON", "LONG_PRESS"] = "BUTTON"
    device_location: DeviceLocation | None = None
    device_location_error: DeviceError | None = None


class LocationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_location: DeviceLocation


# --------------------------------------------------------------------- allies
def _phone(value: str) -> str:
    cleaned = re.sub(r"[\s\-().]", "", value or "")
    if not PHONE_RE.match(cleaned):
        raise ServiceError("Enter a valid phone number (7 to 15 digits, optionally starting with +).", 422, "INVALID_PHONE")
    return cleaned


def ally_view(a: TrustedAllyRow) -> dict:
    return {"ally_id": a.ally_id, "name": a.name, "phone": a.phone, "relationship": a.relationship,
            "relationship_label": RELATIONSHIPS.get(a.relationship, a.relationship), "consent_at": iso(a.consent_at),
            "created_at": iso(a.created_at)}


def list_allies(session, user_id: str) -> list[TrustedAllyRow]:
    return list(session.scalars(select(TrustedAllyRow).where(TrustedAllyRow.user_id == user_id, TrustedAllyRow.active.is_(True))
                                .order_by(TrustedAllyRow.created_at)))


def _own_ally(session, user_id: str, ally_id: str) -> TrustedAllyRow:
    a = session.get(TrustedAllyRow, ally_id)
    if a is None or a.user_id != user_id or not a.active:
        raise ServiceError("Trusted ally not found.", 404, "NOT_FOUND")
    return a


def _duplicate(session, user_id: str, phone: str, except_id: str | None = None) -> bool:
    return any(a.phone == phone and a.ally_id != except_id for a in list_allies(session, user_id))


# ------------------------------------------------------------------------ SOS
def _expire(session, settings, sos: SosRow) -> None:
    if sos.status == "ACTIVE" and utcnow() - as_utc(sos.triggered_at) > timedelta(hours=settings.sos_max_active_hours):
        sos.status, sos.ended_at, sos.ended_reason = "EXPIRED", utcnow(), "MAX_DURATION"
        _event(session, sos.sos_id, "EXPIRED", hours=settings.sos_max_active_hours)


def _active(session, user_id: str) -> SosRow | None:
    return session.scalar(select(SosRow).where(SosRow.user_id == user_id, SosRow.status == "ACTIVE").order_by(SosRow.triggered_at.desc()))


def _own_sos(session, settings, user_id: str, sos_id: str) -> SosRow:
    sos = session.get(SosRow, sos_id)
    if sos is None or sos.user_id != user_id:
        raise ServiceError("SOS not found.", 404, "NOT_FOUND")
    _expire(session, settings, sos)
    return sos


def _apply_fix(sos: SosRow, loc: DeviceLocation, settings) -> str | None:
    """Store a real GPS fix on the SOS; returns an error code if it can't be used as current."""
    if loc.mode != "LIVE":
        raise ServiceError("An SOS can only share your phone's real location. Simulated locations are not accepted.", 422, "SIMULATED_NOT_ALLOWED")
    now = utcnow()
    observed = as_utc(loc.observed_at) if loc.observed_at else now
    if observed - now > timedelta(seconds=60):
        return "LOCATION_TIME_INVALID"
    if now - observed > timedelta(seconds=settings.sos_location_max_age_s):
        return "LOCATION_TOO_OLD"
    if sos.last_mode == "LIVE" and sos.last_observed_at is not None and observed <= as_utc(sos.last_observed_at):
        return "OUT_OF_ORDER"
    sos.last_latitude, sos.last_longitude, sos.last_accuracy_m = loc.latitude, loc.longitude, loc.accuracy_m
    sos.last_observed_at, sos.last_received_at, sos.last_mode = observed, now, "LIVE"
    sos.location_status, sos.location_error = "SHARING", None
    sos.updates = (sos.updates or 0) + 1
    return None


def trigger(session, settings, actor: Actor, body: SosTrigger) -> SosRow:
    existing = _active(session, actor.user_id)
    if existing is not None:
        _expire(session, settings, existing)
        if existing.status == "ACTIVE":
            return existing                       # pressing again never creates a second SOS
    now = utcnow()
    sos = SosRow(sos_id=new_id("SOS", 5), user_id=actor.user_id, status="ACTIVE", method=body.method, triggered_at=now,
                 location_status="WAITING_FOR_GPS", location_error=body.device_location_error or "NOT_PROVIDED", updates=0)
    session.add(sos)
    session.flush()
    _event(session, sos.sos_id, "TRIGGERED", method=body.method)
    if body.device_location is not None:
        problem = _apply_fix(sos, body.device_location, settings)
        if problem:
            sos.location_error = problem
            _event(session, sos.sos_id, "LOCATION_REJECTED", reason=problem)
        else:
            _event(session, sos.sos_id, "LOCATION", mode="LIVE", accuracy_m=body.device_location.accuracy_m)
    else:
        _event(session, sos.sos_id, "LOCATION_UNAVAILABLE", reason=sos.location_error)
    for i, a in enumerate(list_allies(session, actor.user_id)):      # created_at keeps the user's own order of allies
        session.add(SosNotificationRow(notification_id=new_id("NTF", 5), sos_id=sos.sos_id, ally_id=a.ally_id, ally_name=a.name,
                                       ally_phone=a.phone, relationship=a.relationship, kind="ALERT", channel="SMS_WHATSAPP",
                                       status="PENDING_INTEGRATION", token=secrets.token_urlsafe(18),
                                       created_at=now + timedelta(microseconds=i)))
    session.flush()
    return sos


def update_location(session, settings, actor: Actor, sos_id: str, loc: DeviceLocation) -> tuple[SosRow, str | None]:
    sos = _own_sos(session, settings, actor.user_id, sos_id)
    if sos.status != "ACTIVE":
        raise ServiceError("This SOS has ended, so your location is no longer being shared.", 409, "SOS_ENDED")
    problem = _apply_fix(sos, loc, settings)
    if problem in ("LOCATION_TOO_OLD", "LOCATION_TIME_INVALID"):
        sos.location_error = problem
        if sos.last_mode != "LIVE":
            sos.location_status = "WAITING_FOR_GPS"
        _event(session, sos.sos_id, "LOCATION_REJECTED", reason=problem)
    return sos, problem


def manual_location(session, settings, actor: Actor, sos_id: str, point: UserLocation) -> SosRow:
    sos = _own_sos(session, settings, actor.user_id, sos_id)
    if sos.status != "ACTIVE":
        raise ServiceError("This SOS has ended, so your location is no longer being shared.", 409, "SOS_ENDED")
    now = utcnow()
    sos.last_latitude, sos.last_longitude, sos.last_accuracy_m = point.latitude, point.longitude, None
    sos.last_observed_at = sos.last_received_at = now
    sos.last_mode, sos.location_status, sos.location_error = "MANUAL", "MANUAL", None
    sos.updates = (sos.updates or 0) + 1
    _event(session, sos.sos_id, "LOCATION", mode="MANUAL")
    return sos


def end(session, settings, actor: Actor, sos_id: str, *, outcome: str) -> SosRow:
    """outcome: CANCELLED (a mistake / changed mind) or RESOLVED (the user is safe)."""
    sos = _own_sos(session, settings, actor.user_id, sos_id)
    if sos.status != "ACTIVE":
        raise ServiceError("This SOS has already ended.", 409, "SOS_ENDED")
    now = utcnow()
    sos.status, sos.ended_at = outcome, now
    sos.ended_reason = "USER_CANCELLED" if outcome == "CANCELLED" else "USER_SAFE"
    _event(session, sos.sos_id, outcome)
    alerts = session.scalars(select(SosNotificationRow).where(SosNotificationRow.sos_id == sos.sos_id, SosNotificationRow.kind == "ALERT"))
    for i, n in enumerate(alerts):       # tell the allies who got the alert (same delivery rules: pending until a provider exists)
        session.add(SosNotificationRow(notification_id=new_id("NTF", 5), sos_id=sos.sos_id, ally_id=n.ally_id, ally_name=n.ally_name,
                                       ally_phone=n.ally_phone, relationship=n.relationship, kind=outcome, channel=n.channel,
                                       status="PENDING_INTEGRATION", token=None, created_at=now + timedelta(microseconds=i)))
    session.flush()
    return sos


# ---------------------------------------------------------------------- views
def _location_view(sos: SosRow, settings) -> dict | None:
    if sos.last_latitude is None:
        return None
    age = int((utcnow() - as_utc(sos.last_received_at)).total_seconds()) if sos.last_received_at else None
    return {"latitude": sos.last_latitude, "longitude": sos.last_longitude, "accuracy_m": sos.last_accuracy_m, "mode": sos.last_mode,
            "observed_at": iso(sos.last_observed_at), "received_at": iso(sos.last_received_at), "age_s": age,
            "stale": age is not None and age > 120 and sos.status == "ACTIVE"}


def _location_text(sos: SosRow) -> str:
    if sos.status != "ACTIVE":
        return "Location sharing has stopped."
    if sos.location_status == "SHARING":
        return "Sharing your live phone location with your allies."
    if sos.location_status == "MANUAL":
        return "Sharing a point you placed by hand. This is not GPS."
    why = {"PERMISSION_DENIED": "Location permission is blocked on this phone.", "POSITION_UNAVAILABLE": "The phone could not find its position.",
           "TIMEOUT": "Getting a GPS fix took too long.", "UNSUPPORTED": "This browser can't give a location here.",
           "LOCATION_TOO_OLD": "The last GPS fix was too old to share."}.get(sos.location_error or "", "No GPS fix has been received yet.")
    return f"No location is being shared yet. {why}"


def sos_view(session, settings, sos: SosRow, *, owner: bool = True) -> dict:
    notes = list(session.scalars(select(SosNotificationRow).where(SosNotificationRow.sos_id == sos.sos_id)
                                 .order_by(SosNotificationRow.created_at, SosNotificationRow.notification_id)))
    alerts = [n for n in notes if n.kind == "ALERT"]
    followups = [n for n in notes if n.kind != "ALERT"]
    events = list(session.scalars(select(SosEventRow).where(SosEventRow.sos_id == sos.sos_id).order_by(SosEventRow.at)))
    return {
        "sos_id": sos.sos_id, "status": sos.status, "status_text": STATUS_TEXT[sos.status], "method": sos.method,
        "triggered_at": iso(sos.triggered_at), "ended_at": iso(sos.ended_at), "ended_reason": sos.ended_reason,
        "location_status": sos.location_status, "location_text": _location_text(sos), "location_error": sos.location_error,
        "location": _location_view(sos, settings), "updates": sos.updates,
        "allies": [{"name": n.ally_name, "phone": n.ally_phone, "relationship_label": RELATIONSHIPS.get(n.relationship, n.relationship),
                    "channel": n.channel, "status": n.status, "status_text": DELIVERY_TEXT[n.status], "token": n.token,
                    "share_path": f"#/sos/{n.token}" if n.token and sos.status == "ACTIVE" else None,
                    "opened_at": iso(n.last_opened_at),
                    "followup": next((f.kind for f in reversed(followups) if f.ally_id == n.ally_id and f.ally_name == n.ally_name), None)}
                   for n in alerts],
        "no_allies": not alerts,
        "history": [{"event": e.event, "at": iso(e.at), "details": e.details} for e in events],
        "audio_notes": sos_notes(session, sos.sos_id),
        "emergency": EMERGENCY_NUMBERS, "disclaimer": DISCLAIMER,
        "delivery_note": "SMS, WhatsApp and push are not connected yet. Nothing is shown as delivered until a provider confirms it.",
    }


def share_view(session, settings, token: str) -> dict:
    """What a trusted ally sees from their private link: the person's name, when it started,
    and the live location while the SOS is active. Nothing else."""
    n = session.scalar(select(SosNotificationRow).where(SosNotificationRow.token == token, SosNotificationRow.kind == "ALERT"))
    sos = session.get(SosRow, n.sos_id) if n else None
    if n is None or sos is None:
        raise ServiceError("This link is not valid.", 404, "NOT_FOUND")
    _expire(session, settings, sos)
    n.last_opened_at = utcnow()
    user = session.get(UserRow, sos.user_id)
    active = sos.status == "ACTIVE"
    return {"person": (user.display_name if user else "Someone you know").replace(" (citizen)", ""), "ally": n.ally_name,
            "status": sos.status,
            "status_text": "Needs help now" if active else {"CANCELLED": "Cancelled: it was a false alarm", "RESOLVED": "They have said they are safe",
                                                            "EXPIRED": "Closed automatically after a long time"}.get(sos.status, "Ended"),
            "triggered_at": iso(sos.triggered_at), "ended_at": iso(sos.ended_at),
            "location": _location_view(sos, settings) if active else None,   # nothing once the SOS has ended
            "location_note": _location_text(sos) if active else "This alert has ended. Location is no longer shared.",
            "audio_notes": sos_notes(session, sos.sos_id, token=token) if active else [],   # voice notes, only while active
            "emergency": EMERGENCY_NUMBERS, "disclaimer": DISCLAIMER}


# ------------------------------------------------------------------ endpoints
@router.get("/overview")
def overview(request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    _citizen(actor)
    settings = request.app.state.settings
    active = _active(session, actor.user_id)
    if active is not None:
        _expire(session, settings, active)
        session.commit()
    allies = list_allies(session, actor.user_id)
    history = list(session.scalars(select(SosRow).where(SosRow.user_id == actor.user_id).order_by(SosRow.triggered_at.desc()).limit(30)))
    return {"allies": [ally_view(a) for a in allies], "max_allies": settings.sos_max_allies,
            "relationships": [{"id": k, "label": v} for k, v in RELATIONSHIPS.items()],
            "active": sos_view(session, settings, active) if active is not None and active.status == "ACTIVE" else None,
            "history": [{"sos_id": s.sos_id, "status": s.status, "status_text": STATUS_TEXT[s.status], "triggered_at": iso(s.triggered_at),
                         "ended_at": iso(s.ended_at), "updates": s.updates} for s in history],
            "emergency": EMERGENCY_NUMBERS, "disclaimer": DISCLAIMER,
            "who_gets_it": "Your trusted allies get your name, the time, and your live location link only when you trigger an SOS."}


@router.post("/allies", status_code=201)
def add_ally(body: AllyIn, request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    _citizen(actor)
    settings = request.app.state.settings
    if not body.consent:
        raise ServiceError("Please confirm you agree to share your location and name with this person during an SOS.", 422, "CONSENT_REQUIRED")
    phone = _phone(body.phone)
    allies = list_allies(session, actor.user_id)
    if len(allies) >= settings.sos_max_allies:
        raise ServiceError(f"You can have up to {settings.sos_max_allies} trusted allies. Remove one to add another.", 409, "LIMIT_REACHED")
    if _duplicate(session, actor.user_id, phone):
        raise ServiceError("This phone number is already one of your trusted allies.", 409, "DUPLICATE_ALLY")
    now = utcnow()
    ally = TrustedAllyRow(ally_id=new_id("ALY", 4), user_id=actor.user_id, name=body.name, phone=phone, relationship=body.relationship,
                          consent_at=now, active=True, created_at=now, updated_at=now)
    session.add(ally)
    session.commit()
    return ally_view(ally)


@router.patch("/allies/{ally_id}")
def update_ally(ally_id: str, body: AllyUpdate, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    _citizen(actor)
    ally = _own_ally(session, actor.user_id, ally_id)
    if body.phone is not None:
        phone = _phone(body.phone)
        if _duplicate(session, actor.user_id, phone, except_id=ally.ally_id):
            raise ServiceError("This phone number is already one of your trusted allies.", 409, "DUPLICATE_ALLY")
        if phone != ally.phone:
            ally.consent_at = utcnow()      # a new number is a new person: the user's consent applies from now
        ally.phone = phone
    if body.name is not None:
        ally.name = body.name
    if body.relationship is not None:
        ally.relationship = body.relationship
    ally.updated_at = utcnow()
    session.commit()
    return ally_view(ally)


@router.delete("/allies/{ally_id}")
def remove_ally(ally_id: str, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    _citizen(actor)
    ally = _own_ally(session, actor.user_id, ally_id)
    session.delete(ally)       # their contact details are removed; past SOS history keeps only a name snapshot
    session.commit()
    return {"removed": True}


@router.post("/sos", status_code=201)
def trigger_sos(body: SosTrigger, request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    _citizen(actor)
    settings = request.app.state.settings
    # Pressing again while an SOS is active just returns it, so only brand-new SOS creation is limited (abuse guard).
    if _active(session, actor.user_id) is None and not _limiter(request, "trigger").allow(actor.user_id):
        raise ServiceError("Too many SOS attempts in a minute. If you are in danger, call 112.", 429, "RATE_LIMITED")
    sos = trigger(session, settings, actor, body)
    session.commit()
    return sos_view(session, settings, sos)


@router.get("/sos/{sos_id}")
def get_sos(sos_id: str, request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    _citizen(actor)
    settings = request.app.state.settings
    sos = _own_sos(session, settings, actor.user_id, sos_id)
    session.commit()
    return sos_view(session, settings, sos)


@router.post("/sos/{sos_id}/location")
def post_location(sos_id: str, body: LocationIn, request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    _citizen(actor)
    if not _limiter(request, "update").allow(actor.user_id):
        raise ServiceError("Location updates are too frequent.", 429, "RATE_LIMITED")
    settings = request.app.state.settings
    sos, problem = update_location(session, settings, actor, sos_id, body.device_location)
    session.commit()
    return {**sos_view(session, settings, sos), "update_ignored": problem}


@router.post("/sos/{sos_id}/manual-location")
def post_manual_location(sos_id: str, body: UserLocation, request: Request, actor: Actor = Depends(get_actor),
                         session: Session = Depends(get_session)):
    _citizen(actor)
    settings = request.app.state.settings
    sos = manual_location(session, settings, actor, sos_id, body)
    session.commit()
    return sos_view(session, settings, sos)


@router.post("/sos/{sos_id}/cancel")
def cancel_sos(sos_id: str, request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    _citizen(actor)
    settings = request.app.state.settings
    sos = end(session, settings, actor, sos_id, outcome="CANCELLED")
    session.commit()
    return sos_view(session, settings, sos)


@router.post("/sos/{sos_id}/resolve")
def resolve_sos(sos_id: str, request: Request, actor: Actor = Depends(get_actor), session: Session = Depends(get_session)):
    _citizen(actor)
    settings = request.app.state.settings
    sos = end(session, settings, actor, sos_id, outcome="RESOLVED")
    session.commit()
    return sos_view(session, settings, sos)


@router.get("/share/{token}")
def ally_share(token: str, request: Request, session: Session = Depends(get_session)):
    """Public (token-protected). The only women's-safety data that leaves the owner's account."""
    if not _limiter(request, "share").allow(f"share:{_client(request)}"):
        raise ServiceError("Too many requests. Try again in a minute.", 429, "RATE_LIMITED")
    out = share_view(session, request.app.state.settings, token[:60])
    session.commit()
    return out
