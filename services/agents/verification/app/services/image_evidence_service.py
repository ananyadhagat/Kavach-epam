from ..validators.evidence_validator import check_required_evidence, validate_evidence_task_ownership


def validate_and_collect(task_id: str, submission: dict) -> tuple[list[dict], list[str]]:
    evidence = submission.get("evidence", [])
    validate_evidence_task_ownership(task_id, evidence)
    return evidence, check_required_evidence(evidence)
