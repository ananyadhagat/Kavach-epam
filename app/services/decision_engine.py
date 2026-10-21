def decide(*, missing_evidence: list[str], visual: dict | None, location: dict, plan: list[dict],
           require_gps: bool, score: float | None, score_status: str, threshold: float) -> str:
    if missing_evidence or visual is None:
        return "INCONCLUSIVE"
    if visual.get("limitations"):
        return "MANUAL_REVIEW"
    if visual.get("visual_change") == "UNCERTAIN":
        return "MANUAL_REVIEW"
    if any(value == "UNCERTAIN" for group in (visual.get("before_observations", {}), visual.get("after_observations", {})) for value in group.values()):
        return "MANUAL_REVIEW"
    if location["status"] == "INCONCLUSIVE":
        return "INCONCLUSIVE"
    failed = any(row["mandatory"] and row["evidence_finding"] == "CONTRADICTED" for row in plan)
    if failed:
        return "FAIL"
    if location["status"] == "MISMATCH":
        # A location mismatch conflicts with otherwise usable photographic evidence.
        return "MANUAL_REVIEW"
    if any(row["mandatory"] and row["evidence_finding"] == "UNKNOWN" for row in plan):
        return "INCONCLUSIVE"
    if require_gps and location["status"] == "UNAVAILABLE":
        return "INCONCLUSIVE"
    if score is None:
        return "INCONCLUSIVE"
    return "PASS" if score >= threshold else "FAIL"
