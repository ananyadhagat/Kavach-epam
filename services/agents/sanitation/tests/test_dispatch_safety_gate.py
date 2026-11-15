import pytest
from pydantic import ValidationError

from app.schemas.dispatch_contract import DispatchContract
from app.schemas.integration import ApprovalStatus
from app.schemas.sanitation import SanitationPriority


def make_contract(**overrides):
    data = {
        "complaint_id": "KAVACH-TEST-001",
        "location": "Zone A",
        "priority": SanitationPriority.HIGH,
        "approval_status": ApprovalStatus.APPROVED,
    }
    data.update(overrides)
    return DispatchContract(**data)


def test_dispatch_eligibility_defaults_to_false():
    contract = make_contract()
    assert contract.dispatch_eligible is False


def test_dispatch_eligibility_cannot_be_enabled():
    with pytest.raises(ValidationError):
        make_contract(dispatch_eligible=True)


def test_human_review_cannot_be_disabled():
    with pytest.raises(ValidationError):
        make_contract(requires_human_review=False)


def test_planning_status_must_remain_proposed():
    with pytest.raises(ValidationError):
        make_contract(planning_status="DISPATCHED")
