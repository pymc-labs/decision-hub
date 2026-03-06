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
    """GET /v1/stats -- Cache-Control header + in-memory cache."""

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

    @patch("decision_hub.api.registry_routes.fetch_registry_stats")
    def test_in_memory_cache_avoids_repeated_db_call(
        self,
        mock_fetch: MagicMock,
        client: TestClient,
    ) -> None:
        mock_fetch.return_value = {"total_skills": 10, "total_orgs": 3, "total_downloads": 100}
        resp1 = client.get("/v1/stats")
        resp2 = client.get("/v1/stats")
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # DB function should only be called once — second hit is from cache
        assert mock_fetch.call_count == 1


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


class TestSkillListCacheHeaders:
    """GET /v1/skills -- Cache-Control for anonymous requests only."""

    @patch("decision_hub.api.registry_routes.fetch_all_skills_for_index")
    def test_anonymous_request_has_cache_control(
        self,
        mock_fetch: MagicMock,
        client: TestClient,
    ) -> None:
        mock_fetch.return_value = ([], 0)
        resp = client.get("/v1/skills")
        assert resp.status_code == 200
        assert "Cache-Control" in resp.headers
        assert "public" in resp.headers["Cache-Control"]
        assert "max-age=30" in resp.headers["Cache-Control"]

    @patch("decision_hub.api.registry_routes.list_user_org_ids")
    @patch("decision_hub.api.registry_routes.list_granted_skill_ids")
    @patch("decision_hub.api.registry_routes.fetch_all_skills_for_index")
    def test_authenticated_request_has_no_cache_control(
        self,
        mock_fetch: MagicMock,
        mock_granted: MagicMock,
        mock_org_ids: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_fetch.return_value = ([], 0)
        mock_org_ids.return_value = []
        mock_granted.return_value = []
        resp = client.get("/v1/skills", headers=auth_headers)
        assert resp.status_code == 200
        assert "Cache-Control" not in resp.headers

    @patch("decision_hub.api.registry_routes.fetch_all_skills_for_index")
    def test_anonymous_in_memory_cache_avoids_repeated_db_call(
        self,
        mock_fetch: MagicMock,
        client: TestClient,
    ) -> None:
        mock_fetch.return_value = ([], 0)
        resp1 = client.get("/v1/skills")
        resp2 = client.get("/v1/skills")
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert mock_fetch.call_count == 1
