"""Tests for Cache-Control headers on public read endpoints."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


class TestTaxonomyCacheHeaders:
    """GET /v1/taxonomy -- Cache-Control header."""

    def test_returns_cache_control_header(self, client: TestClient) -> None:
        resp = client.get("/v1/taxonomy")
        assert resp.status_code == 200
        assert "Cache-Control" in resp.headers
        assert "public" in resp.headers["Cache-Control"]
        assert "max-age=300" in resp.headers["Cache-Control"]


class TestRegistryStatsCacheHeaders:
    """GET /v1/stats -- Cache-Control header (no in-memory cache)."""

    @patch("decision_hub.api.registry_routes.fetch_registry_stats")
    def test_returns_cache_control_header(
        self,
        mock_fetch: MagicMock,
        client: TestClient,
    ) -> None:
        mock_fetch.return_value = {"total_skills": 10, "total_orgs": 3, "total_downloads": 100}
        resp = client.get("/v1/stats")
        assert resp.status_code == 200
        assert "Cache-Control" in resp.headers
        assert "public" in resp.headers["Cache-Control"]
        assert "max-age=60" in resp.headers["Cache-Control"]


class TestOrgProfilesCacheHeaders:
    """GET /v1/orgs/profiles -- Cache-Control header + in-memory cache."""

    @patch("decision_hub.api.org_routes.list_all_org_profiles")
    def test_returns_cache_control_header(
        self,
        mock_list: MagicMock,
        client: TestClient,
    ) -> None:
        mock_list.return_value = []
        resp = client.get("/v1/orgs/profiles")
        assert resp.status_code == 200
        assert "Cache-Control" in resp.headers
        assert "public" in resp.headers["Cache-Control"]
        assert "max-age=60" in resp.headers["Cache-Control"]

    @patch("decision_hub.api.org_routes.list_all_org_profiles")
    def test_in_memory_cache_avoids_repeated_db_call(
        self,
        mock_list: MagicMock,
        client: TestClient,
    ) -> None:
        mock_list.return_value = []
        resp1 = client.get("/v1/orgs/profiles")
        resp2 = client.get("/v1/orgs/profiles")
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert mock_list.call_count == 1


class TestOrgStatsCacheHeaders:
    """GET /v1/orgs/stats -- Cache-Control header + in-memory cache."""

    @patch("decision_hub.api.org_routes.fetch_org_stats")
    def test_returns_cache_control_header(
        self,
        mock_fetch: MagicMock,
        client: TestClient,
    ) -> None:
        mock_fetch.return_value = []
        resp = client.get("/v1/orgs/stats")
        assert resp.status_code == 200
        assert "Cache-Control" in resp.headers
        assert "public" in resp.headers["Cache-Control"]
        assert "max-age=60" in resp.headers["Cache-Control"]

    @patch("decision_hub.api.org_routes.fetch_org_stats")
    def test_in_memory_cache_avoids_repeated_db_call(
        self,
        mock_fetch: MagicMock,
        client: TestClient,
    ) -> None:
        mock_fetch.return_value = []
        resp1 = client.get("/v1/orgs/stats")
        resp2 = client.get("/v1/orgs/stats")
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert mock_fetch.call_count == 1

    @patch("decision_hub.api.org_routes.fetch_org_stats")
    def test_different_params_are_cached_separately(
        self,
        mock_fetch: MagicMock,
        client: TestClient,
    ) -> None:
        mock_fetch.return_value = []
        client.get("/v1/orgs/stats?sort=slug")
        client.get("/v1/orgs/stats?sort=skill_count")
        # Different query params should result in separate cache entries
        assert mock_fetch.call_count == 2
