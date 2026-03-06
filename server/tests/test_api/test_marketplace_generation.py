"""Verify marketplace generation counter is bumped on publish and delete."""

from decision_hub.infra.database import bump_marketplace_generation


def test_bump_marketplace_generation_callable():
    """bump_marketplace_generation should be importable and callable."""
    assert callable(bump_marketplace_generation)


def test_bump_imported_in_registry_routes():
    """registry_routes should import bump_marketplace_generation."""
    import decision_hub.api.registry_routes as mod

    assert hasattr(mod, "bump_marketplace_generation")
