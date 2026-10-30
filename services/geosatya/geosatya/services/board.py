"""Supervisor dispatch board: every open incident with its assignment phase,
tracking freshness, ETA/ETR and verification state, plus attention flags.
Read-only; actions stay on the existing endpoints (assign, reassign, release, review)."""

from __future__ import annotations

from sqlalchemy import func, select

from geosatya.models import (
    CompletionRow, DispatchRow, IncidentRow, IntelligenceRow, LocationPingRow, TaskProgressRow, TaskRow, UserRow, WorkerProfileRow,
)
from geosatya.services import estimates
from geosatya.services.dispatch import acceptance_overdue
from geosatya.services.intelligence import priority_of
from geosatya.services.tracking import PHASE_TEXT, phase_of, recent_pings
from geosatya.timeutil import as_utc, iso, seen_time, utcnow

PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "NORMAL": 2, "LOW": 3}


def _mins(a, b):
    return round((as_utc(b) - as_utc(a)).total_seconds() / 60, 1) if a and b else None


def board(session, settings, categories, *, include_resolved: int = 5) -> dict:
    now = utcnow()
    rows = []
    incidents = list(session.scalars(select(IncidentRow).where(IncidentRow.status != "RESOLVED").order_by(IncidentRow.created_at)))
    incidents += list(session.scalars(select(IncidentRow).where(IncidentRow.status == "RESOLVED")
                                      .order_by(IncidentRow.updated_at.desc()).limit(include_resolved)))
    for inc in incidents:
        task = session.scalar(select(TaskRow).where(TaskRow.incident_id == inc.incident_id))
        progress = session.get(TaskProgressRow, task.task_id) if task else None
        pings = recent_pings(session, task.task_id) if task else []
        phase = phase_of(task, progress)
        intel = session.get(IntelligenceRow, inc.incident_id)
        last_dispatch = session.scalar(select(DispatchRow).where(DispatchRow.incident_id == inc.incident_id)
                                       .order_by(DispatchRow.created_at.desc()).limit(1))
        latest_completion = session.scalar(select(CompletionRow).where(CompletionRow.incident_id == inc.incident_id)
                                           .order_by(CompletionRow.submitted_at.desc()).limit(1))
        worker = session.get(UserRow, task.worker_id) if task else None
        profile = session.get(WorkerProfileRow, task.worker_id) if task else None
        eta = estimates.eta(task, progress, pings, settings, now) if task else None
        etr = estimates.etr_view(task, progress, inc, now)
        last_loc_age = int((now - seen_time(pings[-1].received_at, pings[-1].observed_at)).total_seconds()) if pings else None
        tracking_stale = bool(progress and progress.tracking_active and (last_loc_age is None or last_loc_age > settings.tracking_stale_s))

        flags = []
        if task is None:
            flags.append("UNASSIGNED")
        if task is not None and acceptance_overdue(settings, task, progress, now):
            flags.append("ACCEPTANCE_OVERDUE")
        if tracking_stale:
            flags.append("TRACKING_STALE")
        if eta and eta.get("stationary"):
            flags.append("WORKER_STATIONARY")
        if etr.get("state") == "OVERDUE":
            flags.append("ETR_OVERDUE")
        if task is not None and task.rework_reason and task.status in ("ASSIGNED", "IN_PROGRESS"):
            flags.append("AWAITING_EVIDENCE")
        if phase == "AWAITING_REVIEW":
            flags.append("AWAITING_REVIEW")

        cat = categories.get(inc.category) or {}
        rows.append({
            "incident_id": inc.incident_id, "title": inc.title, "category": inc.category, "category_label": cat.get("label", inc.category),
            "status": inc.status, "priority": priority_of(intel), "intelligence_status": intel.status if intel else "NOT_RUN",
            "is_demo": inc.is_demo, "reported_at": iso(inc.created_at),
            "phase": phase, "phase_text": PHASE_TEXT[phase],
            "dispatch_status": last_dispatch.status if last_dispatch else None,
            "dispatch_method": last_dispatch.method if last_dispatch else None,
            "task_id": task.task_id if task else None, "worker_id": task.worker_id if task else None,
            "worker_name": worker.display_name if worker else None,
            "worker_available": profile.available if profile else None,
            "assigned_at": iso(task.assigned_at) if task else None, "accepted_at": iso(progress.accepted_at) if progress else None,
            "since_assigned_min": _mins(task.assigned_at, now) if task and task.status in ("ASSIGNED", "IN_PROGRESS") else None,
            "since_arrived_min": _mins(progress.arrived_at, now) if progress and progress.arrived_at and task.status in ("ASSIGNED", "IN_PROGRESS") else None,
            "in_progress_min": _mins(progress.work_started_at, now) if progress and progress.work_started_at and task.status == "IN_PROGRESS" else None,
            "tracking_active": bool(progress and progress.tracking_active),
            "last_location_age_s": last_loc_age, "tracking_stale": tracking_stale,
            "eta": {k: eta[k] for k in ("state", "minutes_low", "minutes_high", "distance_m", "stationary")} if eta else None,
            "etr": {k: etr.get(k) for k in ("state", "due_at", "remaining_min")},
            "verification_outcome": latest_completion.outcome if latest_completion else None,
            "review_decision": latest_completion.review_decision if latest_completion else None,
            "flags": flags,
        })
    rows.sort(key=lambda r: (r["status"] == "RESOLVED", -len(r["flags"]), PRIORITY_ORDER.get(r["priority"], 9), r["reported_at"]))
    counts = {f: sum(f in r["flags"] for r in rows) for f in
              ("UNASSIGNED", "ACCEPTANCE_OVERDUE", "TRACKING_STALE", "WORKER_STATIONARY", "ETR_OVERDUE", "AWAITING_EVIDENCE", "AWAITING_REVIEW")}
    return {"generated_at": iso(now), "acceptance_timeout_min": settings.acceptance_timeout_min, "counts": counts, "incidents": rows}


def live_overview(session, settings, categories) -> dict:
    """Supervisor live map. Worker positions are included only while recent:
    LIVE (≤ TRACKING_STALE_S), STALE (≤ DISPATCH_LOCATION_MAX_AGE_S, labelled),
    otherwise OFFLINE with no coordinates."""
    from datetime import datetime, time as dtime

    now = utcnow()
    b = board(session, settings, categories, include_resolved=0)
    by_id = {r["incident_id"]: r for r in b["incidents"]}
    incidents = []
    for inc in session.scalars(select(IncidentRow).where(IncidentRow.incident_id.in_(list(by_id)))):
        r = by_id[inc.incident_id]
        cat = categories.get(inc.category) or {}
        incidents.append({**{k: r[k] for k in ("incident_id", "title", "category", "category_label", "status", "phase", "phase_text",
                                                "priority", "worker_id", "worker_name", "task_id", "flags", "eta", "etr", "is_demo",
                                                "verification_outcome", "reported_at")},
                          "icon": cat.get("icon", "dots"), "latitude": inc.latitude, "longitude": inc.longitude})

    tasks = list(session.scalars(select(TaskRow).where(TaskRow.status.in_(("ASSIGNED", "IN_PROGRESS", "AWAITING_VERIFICATION")))))
    progress = {t.task_id: session.get(TaskProgressRow, t.task_id) for t in tasks}
    last_ping = {tid: as_utc(at).timestamp() for tid, at in session.execute(
        select(LocationPingRow.task_id, func.max(LocationPingRow.received_at)).group_by(LocationPingRow.task_id))}
    workers = []
    for user, prof in session.execute(select(UserRow, WorkerProfileRow).join(WorkerProfileRow, WorkerProfileRow.user_id == UserRow.user_id)
                                      .where(UserRow.role == "WORKER").order_by(UserRow.display_name)):
        mine = [t for t in tasks if t.worker_id == user.user_id]
        # The job the worker is on now: the one they last sent a position for, then work in
        # progress, then the newest assignment. Their status follows that job.
        active = [t for t in mine if t.status in ("ASSIGNED", "IN_PROGRESS")]
        active.sort(key=lambda t: (-(last_ping.get(t.task_id) or 0), t.status != "IN_PROGRESS", -as_utc(t.assigned_at).timestamp()))
        current = active[0] if active else None
        phase = phase_of(current, progress.get(current.task_id)) if current else None
        if phase in ("IN_PROGRESS", "ARRIVED"):
            status = "ON_SITE"
        elif phase == "EN_ROUTE":
            status = "EN_ROUTE"
        elif phase:
            status = "ASSIGNED"
        elif not prof.available:
            status = "UNAVAILABLE"
        elif len(mine) >= prof.max_active_tasks:
            status = "BUSY"
        else:
            status = "AVAILABLE"
        age = int((now - as_utc(prof.last_received_at)).total_seconds()) if prof.last_received_at else None
        loc_state = ("NONE" if age is None else "LIVE" if age <= settings.tracking_stale_s
                     else "STALE" if age <= settings.dispatch_location_max_age_s else "OFFLINE")
        workers.append({
            "worker_id": user.user_id, "name": user.display_name, "status": status, "available": prof.available,
            "active_tasks": len(mine), "max_active_tasks": prof.max_active_tasks, "skills": prof.skills,
            "current_incident_id": current.incident_id if current else None,
            "location_state": loc_state, "location_age_s": age,
            "location": ({"latitude": prof.last_latitude, "longitude": prof.last_longitude, "accuracy_m": prof.last_accuracy_m,
                          "mode": prof.last_mode, "source": prof.last_source} if loc_state in ("LIVE", "STALE") else None),
        })

    local_midnight = datetime.combine(datetime.now().astimezone().date(), dtime.min).astimezone()
    resolved_today = session.scalar(select(func.count()).select_from(TaskProgressRow)
                                    .where(TaskProgressRow.resolved_at >= local_midnight.astimezone(now.tzinfo)))
    flags = b["counts"]
    kpis = {
        "total_reported": session.scalar(select(func.count()).select_from(IncidentRow)) or 0,
        "resolved_total": session.scalar(select(func.count()).select_from(IncidentRow).where(IncidentRow.status == "RESOLVED")) or 0,
        "work_in_progress": sum(i["phase"] in ("ARRIVED", "IN_PROGRESS") for i in incidents),
        "open_incidents": len(incidents),
        "available_workers": sum(w["status"] == "AVAILABLE" for w in workers),
        "assigned_workers": sum(w["status"] == "ASSIGNED" for w in workers),
        "travelling_workers": sum(w["status"] == "EN_ROUTE" for w in workers),
        "on_site_workers": sum(w["status"] == "ON_SITE" for w in workers),
        "being_resolved": sum(i["phase"] in ("ARRIVED", "IN_PROGRESS", "AWAITING_REVIEW") for i in incidents),
        "resolved_today": resolved_today or 0,
        "overdue": sum(bool({"ETR_OVERDUE", "ACCEPTANCE_OVERDUE"} & set(i["flags"])) for i in incidents),
        "awaiting_worker": flags["UNASSIGNED"],
        "awaiting_review": flags["AWAITING_REVIEW"],
    }
    return {"generated_at": iso(now), "kpis": kpis, "incidents": incidents, "workers": workers,
            "routing": settings.routing_provider, "stale_after_s": settings.tracking_stale_s,
            "offline_after_s": settings.dispatch_location_max_age_s}
