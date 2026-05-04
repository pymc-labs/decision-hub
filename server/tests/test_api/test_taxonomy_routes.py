"""Tests for the taxonomy public route."""

from fastapi.testclient import TestClient

from dhub_core.taxonomy import CATEGORY_TAXONOMY


def test_get_taxonomy_returns_groups(client: TestClient) -> None:
    """The endpoint returns the full category taxonomy under ``groups``."""
    resp = client.get("/v1/taxonomy")

    assert resp.status_code == 200
    body = resp.json()
    assert "groups" in body
    assert body["groups"] == CATEGORY_TAXONOMY


def test_get_taxonomy_sets_cache_control_when_ttl_configured(client: TestClient) -> None:
    """When ``cache_ttl_taxonomy`` is set, the response advertises that max-age."""
    # The test_settings fixture sets cache_ttl_taxonomy=300.
    resp = client.get("/v1/taxonomy")

    assert resp.headers.get("Cache-Control") == "public, max-age=300"


def test_get_taxonomy_omits_cache_control_when_ttl_zero(client: TestClient, test_settings) -> None:
    """A zero TTL means no caching directive is emitted (clients revalidate)."""
    test_settings.cache_ttl_taxonomy = 0

    resp = client.get("/v1/taxonomy")

    assert resp.status_code == 200
    assert "Cache-Control" not in resp.headers
