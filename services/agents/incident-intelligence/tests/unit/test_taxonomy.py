from kavach.schemas.incident_intelligence import Category, IncidentType
from kavach.services.incident_intelligence.taxonomy import (
    TAXONOMY, normalize_taxonomy, render_taxonomy_for_prompt,
)


def test_valid_pair_passes_through():
    r = normalize_taxonomy("SANITATION", "WASTE_OVERFLOW")
    assert (r.category, r.incident_type, r.notes) == (Category.SANITATION, IncidentType.WASTE_OVERFLOW, [])
    assert not r.is_uncertain


def test_normalizes_case_spaces_and_hyphens():
    r = normalize_taxonomy("sanitation", "waste overflow")
    assert r.incident_type == IncidentType.WASTE_OVERFLOW
    assert normalize_taxonomy("water-supply", "broken-pipe").category == Category.WATER_SUPPLY


def test_unknown_category_and_type_degrade_to_other_unknown():
    r = normalize_taxonomy("ALIEN_INVASION", "UFO")
    assert (r.category, r.incident_type) == (Category.OTHER, IncidentType.UNKNOWN)
    assert "UNKNOWN_CATEGORY" in r.notes and r.is_uncertain


def test_known_category_unknown_type():
    r = normalize_taxonomy("ELECTRICAL", "TELEPORTER")
    assert (r.category, r.incident_type) == (Category.ELECTRICAL, IncidentType.UNKNOWN)
    assert "UNKNOWN_INCIDENT_TYPE" in r.notes and r.is_uncertain


def test_incident_type_wins_over_mismatched_category():
    r = normalize_taxonomy("SANITATION", "BROKEN_PIPE")
    assert r.category == Category.WATER_SUPPLY
    assert "CATEGORY_TYPE_MISMATCH" in r.notes


def test_none_inputs_are_safe():
    r = normalize_taxonomy(None, None)
    assert r.category == Category.OTHER


def test_every_incident_type_belongs_to_exactly_one_category():
    seen = [t for types in TAXONOMY.values() for t in types]
    assert len(seen) == len(set(seen))
    assert set(seen) | {IncidentType.UNKNOWN} == set(IncidentType)


def test_prompt_rendering_lists_all_categories():
    text = render_taxonomy_for_prompt()
    assert all(c.value in text for c in Category)
