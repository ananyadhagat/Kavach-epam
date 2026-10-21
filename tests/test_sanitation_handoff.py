import pytest

from app.schemas.integration import ApprovalStatus
from app.schemas.sanitation import SanitationPriority
from app.schemas.supervisor_request import SupervisorSanitationRequest
from app.services.sanitation_handoff import prepare_dispatch_contract


def make_supervisor_request(
    approval_status: ApprovalStatus,
) -> SupervisorSanitationRequest:
    return SupervisorSanitationRequest(
        complaint_id="KAVACH-201",
        description="Overflowing public dustbin near the main entrance",
        location="Main entrance",
        priority=SanitationPriority.HIGH,
        approval_status=approval_status,
    )


def test_approved_request_produces_dispatch_contract():
    request = make_supervisor_request(ApprovalStatus.APPROVED)

    contract = prepare_dispatch_contract(request)

    assert contract.complaint_id == "KAVACH-201"
    assert contract.location == "Main entrance"
    assert contract.approval_status == ApprovalStatus.APPROVED
    assert contract.planning_status == "PROPOSED"
    assert len(contract.tasks) > 0


@pytest.mark.parametrize(
    "status",
    [ApprovalStatus.PENDING, ApprovalStatus.REJECTED],
)
def test_unapproved_request_cannot_be_handed_to_dispatch(status):
    request = make_supervisor_request(status)

    with pytest.raises(ValueError, match="approved complaint"):
        prepare_dispatch_contract(request)


def test_dispatch_contract_keeps_human_review_enabled():
    request = make_supervisor_request(ApprovalStatus.APPROVED)

    contract = prepare_dispatch_contract(request)

    assert contract.requires_human_review is True
