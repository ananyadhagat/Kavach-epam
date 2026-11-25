def build_plan_findings(task: dict, submission: dict, visual: dict | None) -> list[dict]:
    findings = []
    after = (visual or {}).get("after_observations", {})
    evidence_ids = [item["evidence_id"] for item in submission.get("evidence", [])
                    if item.get("type") == "AFTER_IMAGE" and item.get("status") == "READY"]
    observations = {
        "STEP-01": ("scattered_waste", "ABSENT"),
        "STEP-02": ("path_obstructed", "ABSENT"),
        "STEP-03": ("overflow", "ABSENT"),
    }
    for requirement in task["requirements"]:
        rid = requirement["requirement_id"]
        claim = submission.get("checklist", {}).get(rid)
        if "target_observation" in requirement:
            observation_name = requirement.get("target_observation")
            target = (observation_name, "ABSENT") if observation_name in {"scattered_waste", "path_obstructed", "overflow"} else None
        else:
            target = observations.get(rid)
        observation = after.get(target[0]) if target else None
        if claim is False or observation == "PRESENT":
            state = "CONTRADICTED"
            reason = "Worker checklist says this step was not completed." if claim is False else f"After-image finding shows {target[0].replace('_', ' ')} remains visible."
        elif claim is True and target and observation == target[1]:
            state, reason = "SUPPORTED", "Checklist claim agrees with the structured after-image finding."
        else:
            state, reason = "UNKNOWN", "Available checklist or visual evidence cannot determine this requirement."
        findings.append({"requirement_id": rid, "label": requirement["label"], "mandatory": requirement["mandatory"],
                         "worker_claim": "COMPLETED" if claim is True else "NOT_COMPLETED" if claim is False else "UNKNOWN",
                         "evidence_finding": state, "reason": reason, "evidence_ids": evidence_ids})
    return findings
