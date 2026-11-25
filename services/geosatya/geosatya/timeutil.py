from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Return an aware UTC datetime. Naive values are assumed to be UTC
    (SQLite drops tzinfo on the way back out)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def seen_time(received: datetime | None, observed: datetime | None) -> datetime | None:
    """When a position was actually true: the device's reading time, but never
    later than the server received it (a wrong device clock can't make it fresher).
    A position saved offline and sent later therefore shows its real age."""
    received, observed = as_utc(received), as_utc(observed)
    if observed is None or received is None:
        return received
    return min(received, observed)


def iso(value: datetime | None) -> str | None:
    value = as_utc(value)
    return value.isoformat().replace("+00:00", "Z") if value else None
