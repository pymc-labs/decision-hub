"""Tests for dhub_core.taxonomy -- shared skill category taxonomy.

This module is the single source of truth for categories used by the Gemini
classifier, the search API, the CLI, and the frontend; the tests guard the
invariants every consumer depends on (e.g. no duplicate subcategories, the
default category is part of the taxonomy, derived lookup maps agree with the
declared structure).
"""

from dhub_core.taxonomy import (
    ALL_SUBCATEGORIES,
    CATEGORY_TAXONOMY,
    DEFAULT_CATEGORY,
    SUBCATEGORY_TO_GROUP,
    SkillClassification,
)


class TestTaxonomyStructure:
    """The declared category map satisfies basic structural invariants."""

    def test_has_at_least_one_group(self) -> None:
        assert len(CATEGORY_TAXONOMY) > 0

    def test_every_group_has_at_least_one_subcategory(self) -> None:
        for group, subs in CATEGORY_TAXONOMY.items():
            assert subs, f"group {group!r} has no subcategories"

    def test_subcategories_are_globally_unique(self) -> None:
        """A subcategory belongs to exactly one group; reverse lookup must be unambiguous."""
        flat = [sub for subs in CATEGORY_TAXONOMY.values() for sub in subs]
        assert len(flat) == len(set(flat)), "duplicate subcategory across groups"


class TestDerivedConstants:
    """The derived lookup tables agree with the declared taxonomy."""

    def test_all_subcategories_matches_declared_set(self) -> None:
        declared = {sub for subs in CATEGORY_TAXONOMY.values() for sub in subs}
        assert declared == ALL_SUBCATEGORIES

    def test_subcategory_to_group_round_trips(self) -> None:
        for group, subs in CATEGORY_TAXONOMY.items():
            for sub in subs:
                assert SUBCATEGORY_TO_GROUP[sub] == group

    def test_subcategory_to_group_covers_every_subcategory(self) -> None:
        assert set(SUBCATEGORY_TO_GROUP) == ALL_SUBCATEGORIES


class TestDefaultCategory:
    """The fallback category must be one of the taxonomy's real subcategories."""

    def test_default_is_a_known_subcategory(self) -> None:
        assert DEFAULT_CATEGORY in ALL_SUBCATEGORIES

    def test_default_has_a_group(self) -> None:
        assert DEFAULT_CATEGORY in SUBCATEGORY_TO_GROUP


class TestSkillClassification:
    """SkillClassification is the frozen result type returned by the classifier."""

    def test_is_frozen(self) -> None:
        result = SkillClassification(category="Backend & APIs", group="Development", confidence=0.9)
        try:
            result.category = "other"  # type: ignore[misc]
        except Exception as exc:
            # Frozen dataclass raises FrozenInstanceError, a dataclasses-specific subclass
            # of AttributeError; check via class name rather than importing the private type.
            assert exc.__class__.__name__ == "FrozenInstanceError"
        else:
            raise AssertionError("SkillClassification should be immutable")

    def test_holds_fields(self) -> None:
        result = SkillClassification(category="Backend & APIs", group="Development", confidence=0.42)
        assert result.category == "Backend & APIs"
        assert result.group == "Development"
        assert result.confidence == 0.42
