from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.worker_task_routes import get_worker_id
from app.schemas.location_event import LocationEventCreate, LocationEventType
from app.services.location_capture_service import LocationCaptureService

router = APIRouter(prefix="/worker/tasks", tags=["Task Locations"])


def get_location_service(request: Request) -> LocationCaptureService:
    return request.app.state.location_service


@router.post("/{task_id}/arrival")
async def capture_arrival(
    task_id: str,
    payload: LocationEventCreate,
    worker_id: str = Depends(get_worker_id),
    service: LocationCaptureService = Depends(get_location_service),
):
    # Prevent a client from using the arrival endpoint for completion GPS.
    if payload.event_type != LocationEventType.ARRIVAL:
        raise HTTPException(422, "event_type must be ARRIVAL.")

    event = await service.capture(task_id, worker_id, payload)
    return {"location_event": event}


@router.post("/{task_id}/completion-location")
async def capture_completion_location(
    task_id: str,
    payload: LocationEventCreate,
    worker_id: str = Depends(get_worker_id),
    service: LocationCaptureService = Depends(get_location_service),
):
    if payload.event_type != LocationEventType.COMPLETION:
        raise HTTPException(422, "event_type must be COMPLETION.")

    event = await service.capture(task_id, worker_id, payload)
    return {"location_event": event}
