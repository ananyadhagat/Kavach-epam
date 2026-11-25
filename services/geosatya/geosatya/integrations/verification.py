"""In-process adapter for the team's Verification agent (MrBadDrip, branch
`verification-agent`, copied unchanged into services/agents/verification).

That agent has no API to receive tasks or photos: its VerificationService
reads them through three small repository interfaces
(app/repositories/interfaces.py). This adapter implements those interfaces
on top of GeoSatya's own records, so the agent's real checks run on real
field data:

  task      -> site = the task's target and GeoSatya's geofence radius;
               requirements = the Sanitation plan's tasks if one exists,
               else the category's worker instructions
  evidence  -> BEFORE_IMAGE = the citizen's report photos (if any),
               AFTER_IMAGE  = the worker's completion photo,
               read from GeoSatya's private photo store (paths checked)
  location  -> the completion's device fix; a SIMULATED fix is not passed
               on as GPS (it would look like real evidence)

Nothing is invented: there is no checklist in GeoSatya, so plan steps stay
UNKNOWN; in mock vision mode the agent's visual finding is unavailable
(its mock reads hand-written fixtures), while image quality, alignment and
the GPS check are computed for real. The result is advisory and is shown
next to GeoSatya's own PASS / REVIEW_REQUIRED / FAIL, never instead of it.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[3] / "agents" / "verification"


class VerificationUnavailable(RuntimeError):
    pass


def _load():
    """Import the agent's package ('app') from its own folder."""
    if not (AGENT_DIR / "app" / "services" / "verification_service.py").is_file():
        raise VerificationUnavailable("Verification agent code not found")
    if str(AGENT_DIR) not in sys.path:
        sys.path.insert(0, str(AGENT_DIR))
    try:
        mods = {name: importlib.import_module(f"app.{name}") for name in (
            "config", "services.verification_service", "services.vision_model_service",
            "repositories.verification_repository", "repositories.evidence_repository", "schemas.verification_request")}
    except Exception as exc:  # e.g. OpenCV not installed
        raise VerificationUnavailable(f"Verification agent could not load: {type(exc).__name__}: {exc}") from exc
    return mods


class GeoSatyaTasks:
    """TaskRepositoryInterface backed by GeoSatya. Built per request."""

    def __init__(self, task: dict):
        self._task = task

    def get(self, task_id: str) -> dict | None:
        return dict(self._task) if task_id == self._task["task_id"] else None

    def save(self, task_id, task):  # the agent never needs to write tasks here
        raise NotImplementedError

    def save_sanitation_plan(self, task_id, plan, authoritative_site=None):
        raise NotImplementedError


def make_evidence_repo(mods, storage_root: Path, submission: dict):
    base = mods["repositories.evidence_repository"].EvidenceRepository

    class GeoSatyaEvidence(base):
        """EvidenceRepositoryInterface: one submission, images from GeoSatya's store.
        load_image is the agent's own (it refuses paths outside storage_root)."""

        def __init__(self):
            super().__init__(submissions={submission["submission_id"]: submission}, storage_root=storage_root)

    return GeoSatyaEvidence()


class VerificationAgent:
    def __init__(self, *, storage_root: Path, audit_db: Path, vision_provider: str = "mock"):
        mods = _load()
        self.mods = mods
        import dataclasses
        # The agent's Settings is a frozen dataclass: copy it with our values.
        # gps_tolerance_m=None -> the task's own tolerance (GeoSatya's geofence radius) is used.
        self.settings = dataclasses.replace(mods["config"].Settings(), db_path=str(audit_db), evidence_root=str(storage_root),
                                            vision_provider=vision_provider, gps_tolerance_m=None)
        self.storage_root = Path(storage_root).resolve()
        audit_db.parent.mkdir(parents=True, exist_ok=True)
        self.audit = mods["repositories.verification_repository"].SQLiteVerificationRepository(str(audit_db))
        self.audit.initialize()

    def verify(self, task: dict, submission: dict) -> dict:
        m = self.mods
        evidence = make_evidence_repo(m, self.storage_root, submission)
        vision = m["services.vision_model_service"].build_vision_adapter(self.settings, image_loader=evidence.load_image)
        service = m["services.verification_service"].VerificationService(
            tasks=GeoSatyaTasks(task), submissions=evidence, vision=vision, audit=self.audit, settings=self.settings)
        request = m["schemas.verification_request"].VerificationRequest(submission_id=submission["submission_id"])
        return service.verify(task["task_id"], request)
