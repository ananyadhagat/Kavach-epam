def estimate_duration(
    quantity: float | None,
    productivity_per_hour: float | None,
    setup_minutes: float = 0,
) -> dict:
    """Estimate duration using explicit quantity and productivity inputs."""

    if quantity is not None and quantity < 0:
        raise ValueError("Quantity cannot be negative.")

    if setup_minutes < 0:
        raise ValueError("Setup duration cannot be negative.")

    if productivity_per_hour is not None and productivity_per_hour <= 0:
        raise ValueError("Productivity must be greater than zero.")

    if quantity is None or productivity_per_hour is None:
        return {
            "estimated_minutes": None,
            "estimate_status": "NEEDS_MORE_DATA",
            "assumptions": [
                "A valid quantity and productivity rate are required."
            ],
        }

    work_minutes = (quantity / productivity_per_hour) * 60
    total_minutes = round(setup_minutes + work_minutes, 2)

    return {
        "estimated_minutes": total_minutes,
        "estimate_status": "PRELIMINARY_ESTIMATE",
        "assumptions": [
            f"Quantity: {quantity}",
            f"Productivity rate: {productivity_per_hour} units per hour",
            f"Setup time: {setup_minutes} minutes",
        ],
    }
