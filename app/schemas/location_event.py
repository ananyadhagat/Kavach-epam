from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LocationEventType(str, Enum):
    ARRIVAL = "ARRIVAL"
    COMPLETION = "COMPLETION"


class LocationCaptureStatus(str, Enum):
    CAPTURED = "CAPTURED"
    UNAVAILABLE = "UNAVAILABLE"
    INACCURATE = "INACCURATE"


class LocationEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: LocationEventType
    capture_status: LocationCaptureStatus

    # allow_inf_nan=False rejects NaN and +/-Infinity explicitly.
    latitude: float | None = Field(
        default=None, ge=-90, le=90, allow_inf_nan=False
    )
    longitude: float | None = Field(
        default=None, ge=-180, le=180, allow_inf_nan=False
    )

    accuracy_meters: float | None = Field(
        default=None, gt=0, le=100_000, allow_inf_nan=False
    )
    captured_at_device: datetime | None = None

    @model_validator(mode="after")
    def validate_location(self):
        if self.capture_status == LocationCaptureStatus.CAPTURED:
            if self.latitude is None or self.longitude is None:
                raise ValueError(
                    "CAPTURED status requires latitude and longitude"
                )

            if self.accuracy_meters is None:
                raise ValueError(
                    "CAPTURED status requires GPS accuracy"
                )

        elif self.latitude is not None or self.longitude is not None:
            raise ValueError(
                "Unavailable or inaccurate GPS must not contain coordinates"
            )

        return self


class LocationEventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_event_id: str
    task_id: str
    worker_id: str

    event_type: LocationEventType
    capture_status: LocationCaptureStatus

    latitude: float | None = Field(default=None, allow_inf_nan=False)
    longitude: float | None = Field(default=None, allow_inf_nan=False)
    accuracy_meters: float | None = Field(default=None, allow_inf_nan=False)

    captured_at_device: datetime | None = None
    received_at_server: datetime = Field(default_factory=utc_now)