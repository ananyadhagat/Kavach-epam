"""Unit tests for the repository abstraction and in-memory implementation."""

from __future__ import annotations

import pytest

from app.repositories.base import ComplaintRepository, RepositoryError
from app.repositories.in_memory import InMemoryComplaintRepository
from app.repositories.synthetic import synthetic_incidents
from app.schemas.complaint import Complaint


@pytest.fixture()
def seeded_repository() -> InMemoryComplaintRepository:
    return InMemoryComplaintRepository(synthetic_incidents())


def test_in_memory_repository_satisfies_the_interface():
    repo = InMemoryComplaintRepository()
    assert isinstance(repo, ComplaintRepository)


def test_synthetic_fixtures_are_deterministic_and_unique():
    first = synthetic_incidents()
    second = synthetic_incidents()
    assert [c.complaint_id for c in first] == [c.complaint_id for c in second]
    ids = [c.complaint_id for c in first]
    assert len(ids) == len(set(ids))


def test_seed_and_retrieve_all_incidents(seeded_repository):
    incidents = seeded_repository.list_candidates()
    assert seeded_repository.count() == len(synthetic_incidents())
    assert len(incidents) == seeded_repository.count()
    assert {c.complaint_id for c in incidents} == {
        c.complaint_id for c in synthetic_incidents()
    }


def test_get_by_id_returns_matching_record(seeded_repository):
    record = seeded_repository.get_by_id("CMP-2026-0101")
    assert record is not None
    assert record.complaint_id == "CMP-2026-0101"
    assert record.category == "WASTE_MANAGEMENT"


def test_get_by_id_missing_returns_none(seeded_repository):
    assert seeded_repository.get_by_id("CMP-2099-9999") is None


def test_list_candidates_excludes_self_comparison(seeded_repository):
    candidates = seeded_repository.list_candidates(exclude_complaint_id="CMP-2026-0101")
    ids = {c.complaint_id for c in candidates}
    assert "CMP-2026-0101" not in ids
    assert len(candidates) == seeded_repository.count() - 1


def test_list_candidates_does_not_insert_the_incoming_complaint(seeded_repository):
    before = seeded_repository.count()
    candidates = seeded_repository.list_candidates(exclude_complaint_id="CMP-2099-9999")
    assert seeded_repository.count() == before
    assert "CMP-2099-9999" not in {c.complaint_id for c in candidates}


def test_empty_repository_returns_empty_list():
    repo = InMemoryComplaintRepository()
    assert repo.list_candidates() == []
    assert repo.count() == 0


def test_no_eligible_candidates_when_only_self_is_present():
    only = Complaint(complaint_id="CMP-2026-0001", description="solo")
    repo = InMemoryComplaintRepository([only])
    assert repo.list_candidates(exclude_complaint_id="CMP-2026-0001") == []


def test_missing_optional_fields_are_preserved(seeded_repository):
    record = seeded_repository.get_by_id("CMP-2026-0107")
    assert record is not None
    assert record.description is None
    assert record.category is None
    assert record.location is None
    assert record.reported_at is None


def test_list_candidates_order_is_deterministic(seeded_repository):
    ids_first = [c.complaint_id for c in seeded_repository.list_candidates()]
    ids_second = [c.complaint_id for c in seeded_repository.list_candidates()]
    assert ids_first == ids_second
    assert ids_first == sorted(ids_first)


def test_returned_records_cannot_mutate_internal_state(seeded_repository):
    fetched = seeded_repository.get_by_id("CMP-2026-0101")
    fetched.category = "MUTATED"
    fetched.location.facility_id = "MUTATED"
    again = seeded_repository.get_by_id("CMP-2026-0101")
    assert again.category == "WASTE_MANAGEMENT"
    assert again.location.facility_id == "FAC-CENTRAL-MARKET"


def test_listed_records_cannot_mutate_internal_state(seeded_repository):
    first_listing = seeded_repository.list_candidates()
    for record in first_listing:
        record.description = "MUTATED"
    second_listing = seeded_repository.list_candidates()
    assert all(record.description != "MUTATED" for record in second_listing)


def test_stored_record_is_isolated_from_caller_mutation():
    repo = InMemoryComplaintRepository()
    original = Complaint(complaint_id="CMP-2026-0001", description="original text")
    repo.add(original)
    original.description = "changed after add"
    stored = repo.get_by_id("CMP-2026-0001")
    assert stored.description == "original text"


def test_duplicate_id_raises_repository_error():
    repo = InMemoryComplaintRepository()
    repo.add(Complaint(complaint_id="CMP-2026-0001", description="first"))
    with pytest.raises(RepositoryError):
        repo.add(Complaint(complaint_id="CMP-2026-0001", description="second"))


def test_add_many_seeds_multiple_records():
    repo = InMemoryComplaintRepository()
    repo.add_many(
        [
            Complaint(complaint_id="CMP-A"),
            Complaint(complaint_id="CMP-B"),
        ]
    )
    assert repo.count() == 2
    assert {c.complaint_id for c in repo.list_candidates()} == {"CMP-A", "CMP-B"}
