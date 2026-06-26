"""Tests for dhub_core.taxonomy — the canonical skill category taxonomy."""

from dataclasses import FrozenInstanceError

import pytest

from dhub_core.taxonomy import (
    ALL_SUBCATEGORIES,
    CATEGORY_TAXONOMY,
    DEFAULT_CATEGORY,
    SUBCATEGORY_TO_GROUP,
    SkillClassification,
)


class TestTaxonomyIntegrity:
    """Verify the taxonomy data is internally consistent.

    The derived collections (ALL_SUBCATEGORIES, SUBCATEGORY_TO_GROUP,
    DEFAULT_CATEGORY) are computed from CATEGORY_TAXONOMY at import time —
    these tests guard against accidental drift if the dict is edited.
    """

    def test_all_subcategories_matches_taxonomy(self):
        expected = {sub for subs in CATEGORY_TAXONOMY.values() for sub in subs}
        assert expected == ALL_SUBCATEGORIES

    def test_subcategory_to_group_is_reverse_index(self):
        for group, subs in CATEGORY_TAXONOMY.items():
            for sub in subs:
                assert SUBCATEGORY_TO_GROUP[sub] == group

    def test_subcategory_to_group_covers_every_subcategory(self):
        assert set(SUBCATEGORY_TO_GROUP.keys()) == ALL_SUBCATEGORIES

    def test_default_category_is_known(self):
        assert DEFAULT_CATEGORY in ALL_SUBCATEGORIES

    def test_subcategories_are_unique(self):
        flat = [sub for subs in CATEGORY_TAXONOMY.values() for sub in subs]
        assert len(flat) == len(set(flat)), "duplicate subcategory across groups"

    def test_groups_are_non_empty(self):
        for group, subs in CATEGORY_TAXONOMY.items():
            assert subs, f"group {group!r} has no subcategories"


class TestSkillClassification:
    def test_create_with_valid_fields(self):
        c = SkillClassification(category="Backend & APIs", group="Development", confidence=0.92)
        assert c.category == "Backend & APIs"
        assert c.group == "Development"
        assert c.confidence == 0.92

    def test_is_frozen(self):
        c = SkillClassification(category="AI & LLM", group="AI & Automation", confidence=0.5)
        with pytest.raises(FrozenInstanceError):
            c.category = "other"  # type: ignore[misc]
