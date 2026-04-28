"""Tests for decision_hub.api.taxonomy_routes -- the /v1/taxonomy endpoint.

The taxonomy endpoint is tiny but completely public and was the only
route under api/ with no test coverage at all. The test locks in the
response shape and the cache header behaviour.
"""

from fastapi.testclient import TestClient


class TestGetTaxonomy:
    def test_returns_groups_dict(self, client: TestClient) -> None:
        """Returns a `groups` mapping from taxonomy group name → subcategory list."""
        resp = client.get("/v1/taxonomy")
        assert resp.status_code == 200

        body = resp.json()
        assert "groups" in body
        groups = body["groups"]
        assert isinstance(groups, dict)
        assert len(groups) > 0
        # Every value should be a list of strings.
        for key, value in groups.items():
            assert isinstance(key, str)
            assert isinstance(value, list)
            assert all(isinstance(s, str) for s in value)

    def test_sets_cache_control_header(self, client: TestClient) -> None:
        """Static content — clients should be told to cache it."""
        resp = client.get("/v1/taxonomy")
        assert resp.status_code == 200
        # Default test settings set cache_ttl_taxonomy=300.
        assert "max-age=" in resp.headers.get("cache-control", "")

    def test_returns_same_content_on_repeat_calls(self, client: TestClient) -> None:
        """The taxonomy is static; repeated requests yield identical bodies."""
        first = client.get("/v1/taxonomy").json()
        second = client.get("/v1/taxonomy").json()
        assert first == second
