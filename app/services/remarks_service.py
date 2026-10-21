def build_remarks(location: dict, plan: list[dict], score: float | None, threshold: float,
                  limitations: list[str], gps_optional: bool, mandatory_failure: bool = False) -> list[str]:
    remarks = list(location.get("reasons", []))
    for item in plan:
        if item["evidence_finding"] == "SUPPORTED":
            continue
        evidence_ids = ", ".join(item.get("evidence_ids", [])) or "none available"
        remarks.append(
            f"{item['label']} ({item['requirement_id']}; evidence: {evidence_ids}): {item['reason']}"
        )
    if gps_optional and location["status"] == "UNAVAILABLE":
        remarks.append("GPS is optional under KAVACH_REQUIRE_GPS=false; score is partial and excludes GPS.")
    if score is not None:
        if mandatory_failure:
            remarks.append(
                f"Weighted score was informational and did not determine the outcome: {score:.1f} "
                f"(configured threshold: {threshold:.1f})."
            )
        else:
            remarks.append(f"Weighted score is {score:.1f}; configured threshold is {threshold:.1f}.")
    remarks.extend("Image limitation: " + item for item in limitations)
    return remarks
