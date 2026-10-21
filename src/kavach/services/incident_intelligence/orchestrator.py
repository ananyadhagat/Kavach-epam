"""Pipeline orchestration (plain Python; LangGraph can wrap these steps later if branching/retries grow).

idempotency check -> validate media -> store media -> EXIF -> location verification -> build input
-> LLM -> validate -> severity floor -> merge server evidence/provenance -> persist -> (optional) handoff.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from kavach.agents.incident_intelligence import IncidentIntelligenceAgent
from kavach.errors import IdempotencyConflictError, KavachError, RepositoryError
from kavach.schemas.incident_intelligence import (
    Category,
    EvidenceReference,
    EvidenceSource,
    FactSource,
    IncidentIntelligenceInput,
    IncidentSubmission,
    IncidentType,
    LocationEvidenceSummary,
    MediaReference,
    Severity,
    StructuredIncidentRecord,
)
from kavach.schemas.location import (
    Coordinates,
    ImageMetadataResult,
    LocationSource,
    LocationStatus,
    ReasonCode,
)
from kavach.repositories.incident_repository import IncidentRepository
from kavach.services.incident_intelligence.handoff import DuplicateDetectionClient
from kavach.services.incident_intelligence.prompt_builder import PROMPT_VERSION
from kavach.services.incident_intelligence.severity_rules import apply_severity_floor, parse_severity
from kavach.services.incident_intelligence.taxonomy import TAXONOMY_VERSION
from kavach.services.location.exif_reader import read_image_metadata
from kavach.services.location.verification import LocationVerificationService
from kavach.services.media.storage import InMemoryMediaStore, MediaStorageError, MediaStore
from kavach.services.media.validation import MediaValidationError, ValidatedImage, validate_image

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UploadedFile:
    filename: str | None
    content: bytes


def request_fingerprint(submission: IncidentSubmission, uploads: list[UploadedFile]) -> str:
    """Stable hash of what the citizen sent (request_id excluded). Same request_id + different
    fingerprint = a different complaint reusing an ID -> rejected, never silently merged."""
    payload = {
        "complaint_text": submission.complaint_text,
        "voice_transcript": submission.voice_transcript,
        "selected": submission.selected_incident_location.model_dump() if submission.selected_incident_location else None,
        "device": submission.device_location.model_dump(mode="json") if submission.device_location else None,
        "images": [hashlib.sha256(u.content).hexdigest() for u in uploads],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


class IncidentIntelligenceOrchestrator:
    def __init__(
        self,
        agent: IncidentIntelligenceAgent,
        repository: IncidentRepository,
        location_service: LocationVerificationService | None = None,
        max_image_bytes: int = 8 * 1024 * 1024,
        max_images: int = 4,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        id_factory: Callable[[], str] = lambda: f"INC-{uuid.uuid4().hex[:10].upper()}",
        media_store: MediaStore | None = None,
        handoff_client: DuplicateDetectionClient | None = None,
    ):
        self.agent = agent
        self.repository = repository
        self.location_service = location_service or LocationVerificationService()
        self.max_image_bytes = max_image_bytes
        self.max_images = max_images
        self.media_store = media_store or InMemoryMediaStore()
        self.handoff_client = handoff_client
        self._clock = clock
        self._new_id = id_factory
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ------------------------------------------------------------------ helpers
    def _lock_for(self, request_id: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(request_id, threading.Lock())

    def _release_lock(self, request_id: str) -> None:
        with self._locks_guard:
            self._locks.pop(request_id, None)

    @staticmethod
    def _check_same_request(existing: StructuredIncidentRecord, fingerprint: str) -> StructuredIncidentRecord:
        if existing.request_fingerprint and existing.request_fingerprint != fingerprint:
            raise IdempotencyConflictError("request_id was already used for a different complaint")
        return existing

    # ------------------------------------------------------------------ steps
    def _prepare_media(self, uploads: list[UploadedFile]):
        refs: list[MediaReference] = []
        valid: list[ValidatedImage] = []
        exif: list[ImageMetadataResult] = []
        for i, up in enumerate(uploads):
            media_id = f"img-{i + 1}"
            if i >= self.max_images:
                refs.append(MediaReference(media_id=media_id, accepted=False, reject_reason="TOO_MANY_IMAGES"))
                continue
            try:
                img = validate_image(media_id, up.content, self.max_image_bytes)
            except MediaValidationError as exc:
                refs.append(MediaReference(media_id=media_id, accepted=False, reject_reason=exc.code))
                continue
            try:
                storage_ref = self.media_store.put(img.sha256, img.mime_type, img.content)
            except MediaStorageError as exc:
                raise RepositoryError("could not store uploaded image") from exc
            valid.append(img)
            refs.append(MediaReference(media_id=media_id, accepted=True, mime_type=img.mime_type,
                                       width=img.width, height=img.height, sha256=img.sha256,
                                       perceptual_hash=img.perceptual_hash, storage_ref=storage_ref))
            exif.append(read_image_metadata(img.content, media_id))
        return refs, valid, exif

    @staticmethod
    def _reported_location(sub: IncidentSubmission):
        """Incident location = where the citizen SAYS the incident is (pin) or an approved facility.

        Device GPS / image EXIF are where the device/photo was - not necessarily the incident (remote
        reports are legitimate). They are preserved separately as evidence and never promoted here.
        """
        if sub.selected_incident_location:
            return sub.selected_incident_location, LocationSource.USER_SELECTED_PIN
        if sub.facility_reference:
            return sub.facility_reference, LocationSource.FACILITY_REFERENCE
        return None, None

    # ------------------------------------------------------------------ main entry
    def process(self, submission: IncidentSubmission, uploads: list[UploadedFile] | None = None) -> StructuredIncidentRecord:
        uploads = uploads or []
        fingerprint = request_fingerprint(submission, uploads)
        lock = self._lock_for(submission.request_id)
        try:
            with lock:  # same request_id in parallel (this process): only one LLM call
                try:
                    existing = self.repository.get_by_request_id(submission.request_id)
                except KavachError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    raise RepositoryError("could not read incident") from exc
                if existing:  # idempotent retry: same request_id + same payload returns the same record
                    return self._check_same_request(existing, fingerprint)
                record = self._process_new(submission, uploads, fingerprint)
        finally:
            self._release_lock(submission.request_id)
        self._handoff(record)
        return record

    def _process_new(self, submission: IncidentSubmission, uploads: list[UploadedFile],
                     fingerprint: str) -> StructuredIncidentRecord:
        submitted_at = self._clock()
        refs, valid_images, exif_results = self._prepare_media(uploads)

        # Location check targets the claimed incident location (pin, or approved facility if known).
        target = submission.facility_reference or submission.selected_incident_location
        target_source = (LocationSource.FACILITY_REFERENCE if submission.facility_reference
                         else LocationSource.USER_SELECTED_PIN if target else None)
        location_check = self.location_service.verify(target, target_source, submission.device_location, exif_results)

        inp = IncidentIntelligenceInput(
            request_id=submission.request_id,
            complaint_text=submission.complaint_text,
            selected_incident_location=submission.selected_incident_location,
            device_location=submission.device_location,
            image_refs=refs,
            image_exif_results=exif_results,
            voice_transcript=submission.voice_transcript,
            location_check=location_check,
            submitted_at=submitted_at,
            taxonomy_version=TAXONOMY_VERSION,
        )

        proposal = self.agent.interpret(inp, valid_images)  # may raise LLMUnavailable / Rejected / ProcessingError

        # --- no accepted image => no image observations / image facts (model must not invent them)
        image_observations = list(proposal.image_observations) if valid_images else []
        facts = list(proposal.extracted_facts)
        if not valid_images:
            facts = [f for f in facts if f.source != FactSource.IMAGE]
        if submission.voice_transcript is None:
            facts = [f for f in facts if f.source != FactSource.VOICE_TRANSCRIPT]  # no transcript, no voice facts

        # --- deterministic severity floor over everything the citizen/model said
        text_for_rules = " ".join(filter(None, [submission.complaint_text, submission.voice_transcript,
                                                *image_observations]))
        sev = apply_severity_floor(text_for_rules, parse_severity(proposal.severity_recommendation) or Severity.UNKNOWN,
                                   proposal.severity_reason)

        # --- server-side additions to uncertainty fields
        missing = list(proposal.missing_information)
        conflicts = list(proposal.conflicting_information)
        questions = list(proposal.clarification_questions)
        needs = proposal.needs_clarification

        for r in refs:
            if not r.accepted:
                missing.append(f"IMAGE_REJECTED:{r.media_id}:{r.reject_reason}")
        if submission.device_location is None:
            missing.append("DEVICE_LOCATION_UNAVAILABLE")

        reported_loc, reported_src = self._reported_location(submission)
        if reported_loc is None:
            missing.append("INCIDENT_LOCATION_UNKNOWN")
            if proposal.claimed_location_text:
                questions.append(f'Please mark "{proposal.claimed_location_text}" on the map so the team can find it.')
            else:
                questions.append("Where exactly is the incident located?")
            needs = True
        if location_check.status == LocationStatus.MISMATCH:
            conflicts.append("Device/photo location differs from the reported incident location "
                             "(may be a legitimate remote report).")
        if ReasonCode.SOURCE_CONFLICT in location_check.reason_codes:
            conflicts.append("Device location and image GPS disagree; review recommended.")

        category = Category(proposal.category)
        itype = IncidentType(proposal.incident_type)

        provenance = [EvidenceReference(source=EvidenceSource.COMPLAINT_TEXT)]
        if submission.voice_transcript:
            provenance.append(EvidenceReference(source=EvidenceSource.VOICE_TRANSCRIPT))
        provenance += [EvidenceReference(source=EvidenceSource.IMAGE, ref_id=r.media_id,
                                         note=f"sha256:{r.sha256}" if r.sha256 else f"rejected:{r.reject_reason}")
                       for r in refs]
        provenance += [EvidenceReference(source=EvidenceSource.IMAGE_EXIF, ref_id=m.media_id, note=m.status.value)
                       for m in exif_results]
        if submission.device_location:
            provenance.append(EvidenceReference(source=EvidenceSource.DEVICE_GEOLOCATION))
        if submission.selected_incident_location:
            provenance.append(EvidenceReference(source=EvidenceSource.USER_SELECTED_PIN))
        if submission.facility_reference:
            provenance.append(EvidenceReference(source=EvidenceSource.FACILITY_REFERENCE))
        provenance.append(EvidenceReference(source=EvidenceSource.LOCATION_CHECK,
                                            note=f"{location_check.status.value}; {location_check.rule_version}"))
        if sev.matched_rules:
            provenance.append(EvidenceReference(source=EvidenceSource.SEVERITY_RULE, note=",".join(sev.matched_rules)))
        provenance.append(EvidenceReference(source=EvidenceSource.LLM, note=f"{self.agent.llm.name}; {PROMPT_VERSION}"))

        record = StructuredIncidentRecord(
            incident_id=self._new_id(),
            request_id=submission.request_id,
            incident_summary=proposal.incident_summary,
            category=category,
            incident_type=itype,
            severity_recommendation=sev.severity,
            severity_reason=sev.reason,
            severity_rule_matches=sev.matched_rules,
            extracted_facts=facts,
            claimed_location_text=proposal.claimed_location_text,
            claimed_time_text=proposal.claimed_time_text,
            reported_incident_location=reported_loc,
            location_evidence_summary=LocationEvidenceSummary(
                check=location_check,
                reported_location_source=reported_src,
                device_location_available=submission.device_location is not None,
                images_with_gps=sum(1 for m in exif_results if m.coordinates),
                images_total=len(refs),
            ),
            image_observations=image_observations,
            missing_information=list(dict.fromkeys(missing)),
            conflicting_information=list(dict.fromkeys(conflicts)),
            needs_clarification=needs,
            clarification_questions=list(dict.fromkeys(questions)),
            evidence_provenance=provenance,
            taxonomy_version=TAXONOMY_VERSION,
            prompt_version=PROMPT_VERSION,
            created_at=self._clock(),
            complaint_text=submission.complaint_text,
            voice_transcript=submission.voice_transcript,
            submitted_at=submitted_at,
            device_location=submission.device_location,
            image_exif_results=exif_results,
            media=refs,
            request_fingerprint=fingerprint,
        )
        try:
            stored = self.repository.save(record)
        except KavachError:
            raise
        except Exception as exc:  # noqa: BLE001 - any storage failure is a controlled, retryable error
            raise RepositoryError("could not save incident") from exc
        if stored.incident_id != record.incident_id:  # another process stored this request_id first
            return self._check_same_request(stored, fingerprint)
        logger.info("incident_created id=%s category=%s severity=%s loc_status=%s",
                    record.incident_id, record.category.value, record.severity_recommendation.value,
                    location_check.status.value)  # no coordinates in logs
        return record

    def _handoff(self, record: StructuredIncidentRecord) -> None:
        """Best-effort push to Duplicate Detection. The record is already stored; a failed handoff is
        logged and can be retried via GET /api/v1/incidents/{id}/duplicate-detection-request."""
        if self.handoff_client is None:
            return
        result = self.handoff_client.send(record)
        if result.delivered:
            logger.info("handoff_delivered id=%s status=%s", record.incident_id, result.status_code)
        else:
            logger.warning("handoff_failed id=%s status=%s error=%s", record.incident_id,
                           result.status_code, result.error)
