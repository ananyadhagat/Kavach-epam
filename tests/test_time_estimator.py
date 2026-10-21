import pytest

from app.services.time_estimator import estimate_duration


def test_time_estimator_calculates_duration():
    result = estimate_duration(
        quantity=120,
        productivity_per_hour=60,
        setup_minutes=10,
    )

    assert result["estimated_minutes"] == 130
    assert result["estimate_status"] == "PRELIMINARY_ESTIMATE"


def test_time_estimator_does_not_invent_missing_quantity():
    result = estimate_duration(
        quantity=None,
        productivity_per_hour=60,
    )

    assert result["estimated_minutes"] is None
    assert result["estimate_status"] == "NEEDS_MORE_DATA"


def test_time_estimator_rejects_negative_quantity():
    with pytest.raises(ValueError, match="Quantity cannot be negative"):
        estimate_duration(
            quantity=-5,
            productivity_per_hour=60,
        )


def test_time_estimator_rejects_invalid_productivity():
    with pytest.raises(ValueError, match="greater than zero"):
        estimate_duration(
            quantity=120,
            productivity_per_hour=0,
        )
