from app.schemas.sanitation import SanitationTask


def estimate_resources(
    tasks: list[SanitationTask],
) -> dict:
    """Summarize proposed resources without inventing availability."""

    resources = sorted({
        resource.strip()
        for task in tasks
        for resource in task.required_resources
        if resource.strip()
    })

    return {
        "required_resources": resources,
        "resource_count": len(resources),
        "worker_count": None,
        "availability_confirmed": False,
        "requires_human_review": True,
        "estimation_basis": (
            "Resources are derived from configured sanitation task policies. "
            "Worker requirements and actual resource availability have not "
            "been established."
        ),
    }
