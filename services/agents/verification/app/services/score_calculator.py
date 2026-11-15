from ..config import WEIGHTS


def calculate_score(components: dict[str, float | None], allow_partial: bool = False) -> tuple[float | None, str, dict[str, float | None]]:
    breakdown = {name: components.get(name) for name in WEIGHTS}
    missing = [name for name, value in breakdown.items() if value is None]
    if missing and not allow_partial:
        return None, "UNAVAILABLE", breakdown
    active_weight = sum(WEIGHTS[name] for name, value in breakdown.items() if value is not None)
    if active_weight == 0:
        return None, "UNAVAILABLE", breakdown
    score = sum(WEIGHTS[name] * value for name, value in breakdown.items() if value is not None) / active_weight
    return round(score, 1), "PARTIAL" if missing else "AVAILABLE", breakdown
