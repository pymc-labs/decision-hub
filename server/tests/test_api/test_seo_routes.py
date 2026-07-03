"""Tests for the sitemap.xml and robots.txt SEO endpoints.

Adds coverage for `decision_hub.api.seo_routes` which previously had no
tests. The routes power search-engine indexing and their correctness
matters for organic discovery, so we exercise both the happy path and
the host-gating fallback used to keep non-prod deploys out of Google.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from decision_hub.api.seo_routes import router as seo_router


def _make_app(settings: MagicMock) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    app.state.engine = MagicMock()
    app.state.s3_client = MagicMock()
    from decision_hub.infra.cache import TTLCache

    app.state.cache = TTLCache(default_ttl=60)
    app.include_router(seo_router)
    return app


def _mk_settings(sitemap_ttl: int = 0) -> MagicMock:
    s = MagicMock()
    s.cache_ttl_sitemap = sitemap_ttl
    return s


class TestSitemap:
    def test_returns_xml_with_all_public_skills(self):
        settings = _mk_settings()
        app = _make_app(settings)

        skill_row = MagicMock()
        skill_row.org_slug = "acme"
        skill_row.skill_name = "data-tool"
        skill_row.latest_published_at = datetime(2026, 1, 15, tzinfo=UTC)

        org_row = ("acme",)

        with patch("decision_hub.api.seo_routes.get_connection") as mock_conn_dep:
            conn = MagicMock()
            # Order matters: routes call skills stmt first, then orgs stmt.
            conn.execute.side_effect = [[skill_row], [org_row]]
            mock_conn_dep.return_value = conn
            app.dependency_overrides[
                __import__("decision_hub.api.deps", fromlist=["get_connection"]).get_connection
            ] = lambda: conn

            client = TestClient(app)
            resp = client.get("/sitemap.xml")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        body = resp.text
        # Static entries always present
        assert "<loc>https://hub.decision.ai/</loc>" in body
        assert "<loc>https://hub.decision.ai/skills</loc>" in body
        assert "<loc>https://hub.decision.ai/orgs</loc>" in body
        assert "<loc>https://hub.decision.ai/how-it-works</loc>" in body
        # Skill + org rows populated from the mocked query
        assert "<loc>https://hub.decision.ai/skills/acme/data-tool</loc>" in body
        assert "<loc>https://hub.decision.ai/orgs/acme</loc>" in body

    def test_serves_from_cache_on_second_call(self):
        # cache_ttl_sitemap > 0 caches the response and short-circuits the DB.
        settings = _mk_settings(sitemap_ttl=60)
        app = _make_app(settings)

        with patch("decision_hub.api.seo_routes.get_connection") as _:
            conn = MagicMock()
            conn.execute.side_effect = [[], []]
            app.dependency_overrides[
                __import__("decision_hub.api.deps", fromlist=["get_connection"]).get_connection
            ] = lambda: conn

            client = TestClient(app)
            first = client.get("/sitemap.xml")
            assert first.status_code == 200
            assert "public, max-age=60" in first.headers["cache-control"]
            # Second call — conn.execute must not be invoked again.
            second = client.get("/sitemap.xml")
            assert second.status_code == 200
            assert conn.execute.call_count == 2  # only from the first call


class TestRobotsTxt:
    def test_non_prod_host_disallows_all(self):
        # Any hostname not in _PROD_HOSTS returns Disallow: / so dev/staging
        # deploys don't leak into search engines.
        settings = _mk_settings()
        app = _make_app(settings)
        client = TestClient(app)
        resp = client.get("/robots.txt", headers={"host": "hub-dev.decision.ai"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        assert "Disallow: /" in resp.text
        # No sitemap advertised on non-prod
        assert "Sitemap:" not in resp.text

    def test_prod_host_allows_all_and_advertises_sitemap(self):
        settings = _mk_settings()
        app = _make_app(settings)
        client = TestClient(app)
        resp = client.get("/robots.txt", headers={"host": "hub.decision.ai"})
        assert resp.status_code == 200
        text = resp.text
        assert "Allow: /" in text
        assert "Sitemap: https://hub.decision.ai/sitemap.xml" in text
