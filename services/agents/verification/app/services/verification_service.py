import uuid
from datetime import datetime, timezone

from ..config import Settings
from ..adapters.agent_contracts import ContractAdapterError, adapt_field_worker_completion
from ..contracts.v1 import CONTRACT_VERSION, ReasonCode
from ..repositories.interfaces import EvidenceRepositoryInterface, TaskRepositoryInterface, VerificationRepositoryInterface
from ..schemas.verification_request import VerificationRequest
from .decision_engine import decide
from .gps_verification_service import verify_location
from .image_evidence_service import validate_and_collect
from .image_alignment_service import ImageAlignmentService
from .image_quality_service import ImageQualityService
from .plan_compliance_service import build_plan_findings
from .remarks_service import build_remarks
from .score_calculator import calculate_score
from .vision_model_service import VisionAnalyzer


class UnknownTask(Exception): pass
class UnknownSubmission(Exception): pass


class VerificationService:
    def __init__(self, tasks: TaskRepositoryInterface, submissions: EvidenceRepositoryInterface,
                 vision: VisionAnalyzer, audit: VerificationRepositoryInterface, settings: Settings):
        self.tasks, self.submissions, self.vision, self.audit, self.settings = tasks, submissions, vision, audit, settings
        self.image_quality = ImageQualityService(settings)
        self.image_alignment = ImageAlignmentService(settings.verification_confidence_threshold)

    def verify(self, task_id: str, request: VerificationRequest) -> dict:
        task = self.tasks.get(task_id)
        if task is None:
            raise UnknownTask(task_id)
        submission_id = request.effective_submission_id
        if request.field_worker_completion is not None:
            completion = request.field_worker_completion.model_dump(mode="json", exclude={"contract_version"})
            evidence_ids = [*completion["before_evidence_ids"], *completion["after_evidence_ids"]]
            event_ids = [completion["completion_location_event_id"]] if completion["completion_location_event_id"] else []
            submission = adapt_field_worker_completion(
                completion,
                evidence_records=self.submissions.get_evidence_records(evidence_ids),
                location_events=self.submissions.get_location_events(event_ids),
            )
            submission["submission_id"] = submission_id
        else:
            submission = self.submissions.get(submission_id)
        if submission is None:
            raise UnknownSubmission(submission_id)
        if submission.get("task_id") != task_id:
            raise UnknownSubmission(f"Submission {submission_id} belongs to another task.")
        return self.audit.get_or_create(
            task_id, submission_id, self.settings.rule_version,
            lambda: self._create_verification(task_id, submission_id, task, submission),
        )

    def _create_verification(self, task_id: str, submission_id: str, task: dict, submission: dict) -> dict:
        contract_warnings = list(task.get("contract_warnings", []))
        evidence, missing = validate_and_collect(task_id, submission)
        evidence_refs = [item["evidence_id"] for item in evidence]
        quality_audit = self.image_quality.inspect_pair(evidence, self.submissions.load_image)
        alignment = self.image_alignment.align_pair(evidence, self.submissions.load_image)
        vision_failure_category = None
        vision_failure_reason = None
        if missing:
            visual = None
        else:
            try:
                aligned_analyze = getattr(self.vision, "analyze_aligned_pair", None)
                if alignment.status == "ALIGNED" and aligned_analyze is not None:
                    visual_obj = aligned_analyze(
                        alignment.before_image, alignment.before_mime,
                        alignment.aligned_after, alignment.after_mime,
                    )
                else:
                    visual_obj = self.vision.analyze(submission, evidence)
                visual = visual_obj.model_dump(mode="json") if visual_obj else None
                if visual is not None:
                    limitations = visual.get("limitations", [])
                    if alignment.status == "LOW_CONFIDENCE":
                        limitations.append("Before/after images could not be reliably landmark-aligned.")
                    visual["limitations"] = list(dict.fromkeys([
                        *limitations, *quality_audit.limitations,
                    ]))
            except Exception:
                visual = None
                vision_failure_category = "UNEXPECTED_ADAPTER_ERROR"
                vision_failure_reason = "Vision analysis failed unexpectedly; analysis is unavailable."
        location_policy = task["site"].copy()
        if self.settings.gps_tolerance_m is not None:
            location_policy["tolerance_m"] = self.settings.gps_tolerance_m
        tolerance_m = self.settings.gps_tolerance_m
        if tolerance_m is None:
            tolerance_m = location_policy.get("tolerance_m")
        location = verify_location(location_policy, submission.get("location"),
                                   self.settings.gps_max_accuracy_m, tolerance_m)
        plan = build_plan_findings(task, submission, visual)

        image_score = None
        if visual:
            image_score = visual.get("cleanup_score")
            if image_score is None:
                after = visual["after_observations"]
                all_absent = bool(after) and all(value == "ABSENT" for value in after.values())
                image_score = 100.0 if visual["visual_change"] == "IMPROVED" and all_absent else 50.0
        plan_score = (100 * sum(row["evidence_finding"] == "SUPPORTED" for row in plan) / len(plan)) if plan else None
        gps_score = location["score"] if location["status"] == "CONSISTENT" else None
        if location["status"] == "MISMATCH":
            gps_score = 0.0
        components = {"image_evidence": image_score, "gps_consistency": gps_score, "plan_compliance": plan_score}
        score, score_status, breakdown = calculate_score(components, allow_partial=not self.settings.require_gps)
        # GPS mismatch is recorded as a contradiction for review, so do not turn it into a weighted fail.
        if location["status"] == "MISMATCH":
            score, score_status, breakdown = None, "UNAVAILABLE", {**components}

        semantic_confidence = visual.get("confidence") if visual else None
        if isinstance(semantic_confidence, (int, float)):
            verification_confidence = min(semantic_confidence, alignment.confidence) \
                if isinstance(alignment.confidence, (int, float)) else semantic_confidence
            verification_confidence = round(verification_confidence, 1)
        else:
            verification_confidence = None

        status = decide(missing_evidence=missing, visual=visual, location=location, plan=plan,
                        require_gps=self.settings.require_gps, score=score, score_status=score_status,
                        threshold=self.settings.pass_threshold)
        if contract_warnings:
            status = "INCONCLUSIVE"
        if visual is not None and (
            verification_confidence is None
            or verification_confidence < self.settings.verification_confidence_threshold
        ):
            status = "MANUAL_REVIEW"
        mandatory_contradictions = [
            row for row in plan if row["mandatory"] and row["evidence_finding"] == "CONTRADICTED"
        ]
        reason_codes: list[ReasonCode] = []
        if mandatory_contradictions:
            reason_codes.append(ReasonCode.MANDATORY_REQUIREMENT_CONTRADICTED)
        if any(row["mandatory"] and row["worker_claim"] == "UNKNOWN" for row in plan):
            reason_codes.append(ReasonCode.MANDATORY_REQUIREMENT_NOT_CLAIMED)
        if location["status"] == "MISMATCH":
            reason_codes.append(ReasonCode.GPS_MISMATCH)
        if missing:
            reason_codes.append(ReasonCode.EVIDENCE_MISSING)
        if visual is None:
            reason_codes.append(ReasonCode.ANALYSIS_UNAVAILABLE)
        elif (visual.get("limitations")
              or visual.get("visual_change") == "UNCERTAIN"
              or any(value == "UNCERTAIN" for group in (
                  visual.get("before_observations", {}), visual.get("after_observations", {})
              ) for value in group.values())):
            reason_codes.append(ReasonCode.IMAGE_UNCERTAIN)
        if status == "FAIL" and not mandatory_contradictions:
            reason_codes.append(ReasonCode.SCORE_BELOW_THRESHOLD)
        if contract_warnings:
            reason_codes.append(ReasonCode.INTEGRATION_CONTRACT_INCOMPLETE)
        if alignment.status == "LOW_CONFIDENCE":
            reason_codes.append(ReasonCode.IMAGE_ALIGNMENT_LOW_CONFIDENCE)
        if visual is not None and verification_confidence is None:
            reason_codes.append(ReasonCode.VERIFICATION_CONFIDENCE_UNAVAILABLE)
        elif visual is not None and verification_confidence < self.settings.verification_confidence_threshold:
            reason_codes.append(ReasonCode.LOW_VERIFICATION_CONFIDENCE)
        reason_codes.extend(ReasonCode(code.value) for code in quality_audit.reason_codes)
        remarks = build_remarks(location, plan, score, self.settings.pass_threshold,
                                visual.get("limitations", []) if visual else [], not self.settings.require_gps,
                                mandatory_failure=status == "FAIL" and bool(mandatory_contradictions))
        failed_requirement_ids = []
        if status == "FAIL" and mandatory_contradictions:
            failed_requirement_ids = [row["requirement_id"] for row in mandatory_contradictions]
            names = ", ".join(
                f"{row['label']} ({row['requirement_id']})" for row in mandatory_contradictions
            )
            remarks.insert(0, f"Mandatory requirement(s) not met: {names}.")
        remarks.extend("Integration contract issue: " + warning for warning in contract_warnings)
        if missing:
            remarks.append("Required evidence unavailable: " + ", ".join(missing) + ".")
        if visual is None and not missing:
            remarks.append("Vision analysis unavailable or malformed; no result was fabricated.")
        if status == "MANUAL_REVIEW":
            remarks.append("Conflicting or limited evidence requires a human reviewer.")
        if visual is not None and verification_confidence is not None and verification_confidence < self.settings.verification_confidence_threshold:
            remarks.append(
                f"Verification confidence is {verification_confidence:.1f}, below the "
                f"{self.settings.verification_confidence_threshold:.1f} review threshold."
            )
        response = {
            "contract_version": CONTRACT_VERSION,
            "verification_id": "VER-" + uuid.uuid4().hex[:12].upper(), "task_id": task_id,
            "submission_id": submission_id, "verification_status": status,
            "verification_score": score, "verification_confidence": verification_confidence,
            "alignment_finding": alignment.as_dict(), "score_status": score_status,
            "score_breakdown": breakdown if score is not None else None,
            "image_findings": visual or {"status": "UNAVAILABLE", "reason": (
                vision_failure_reason or getattr(self.vision, "unavailable_reason", None) or "No usable image analysis."
            )},
            "location_finding": location, "plan_compliance_findings": plan, "remarks": remarks,
            "requires_manual_review": status in ("INCONCLUSIVE", "MANUAL_REVIEW"),
            "rule_version": self.settings.rule_version,
            "vision_provider": getattr(self.vision, "provider", "mock"),
            "vision_model_version": getattr(self.vision, "model_version", self.settings.vision_model_version),
            "vision_prompt_version": getattr(self.vision, "prompt_version", self.settings.prompt_version),
            "image_quality_audit": quality_audit.model_dump(mode="json"),
            "vision_failure_category": vision_failure_category,
            "reason_codes": [code.value for code in reason_codes],
            "failed_requirement_ids": failed_requirement_ids,
            "evidence_refs": evidence_refs, "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return response
