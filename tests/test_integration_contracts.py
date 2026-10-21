import pytest
from pydantic import ValidationError

from app.schemas.integration import ApprovalStatus
from app.schemas.sanitation import SanitationPriority
from app.schemas.supervisor_request import SupervisorSanitationRequest
from app.schemas.dispatch_contract import DispatchContract


def test_supervisor_request_accepts_valid_approved_complaint():
    request = SupervisorSanitationRequest(
        complaint_id="KAVACH-101",
        description="Overflowing public dustbin",
        location="Main entrance",
        priority=SanitationPriority.HIGH,
        approval_status=ApprovalStatus.APPROVED,
    )
    assert request.approval_status == ApprovalStatus.APPROVED


def test_supervisor_request_rejects_invalid_priority():
    with pytest.raises(ValidationError):
        SupervisorSanitationRequest(
            complaint_id="KAVACH-101",
            description="Overflowing public dustbin",
            location="Main entrance",
            priority="urgent",
            approval_status="approved",
        )


def test_dispatch_contract_requires_valid_approval_status():
    with pytest.raises(ValidationError):
        DispatchContract(
            complaint_id="KAVACH-101",
            location="Main entrance",
            priority="high",
            approval_status="maybe",
        )


def test_dispatch_contract_defaults_to_proposed():
    contract = DispatchContract(
        complaint_id="KAVACH-101",
        location="Main entrance",
        priority="high",
        approval_status="approved",
    )
    assert contract.planning_status == "PROPOSED"
    assert contract.requires_human_review is True
