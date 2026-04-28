"""Tests for decision_hub.api.seo_routes -- robots.txt and sitemap.xml.

These public, unauthenticated endpoints had no coverage. They're served
to crawlers, so a regression (e.g. allowing indexing on a non-prod host
or breaking the XML schema) is hard to detect without a CI test.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from xml.etree import ElementTree as ET

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from decision_hub.api.seo_routes import router as seo_router
from decision_hub.infra.cache import TTLCache


@pytest.fixture
def seo_app() -> FastAPI:
    """A minimal FastAPI app with only the SEO routes wired up."""
    app = FastAPI()

    settings = MagicMock()
    settings.cache_ttl_sitemap = 0  # disable caching so each test gets fresh content

    app.state.settings = settings
    app.state.cache = TTLCache(default_ttl=60)

    # The sitemap endpoint queries the DB; provide a stub engine that
    # yields an empty result set (no skills, no orgs).
    mock_conn = MagicMock()
    mock_conn.execute.return_value = []  # iter() over an empty list

    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_engine = MagicMock()
    mock_engine.begin.return_value = mock_ctx
    app.state.engine = mock_engine

    app.include_router(seo_router)
    return app


@pytest.fixture
def seo_client(seo_app: FastAPI) -> TestClient:
    return TestClient(seo_app)


class TestRobotsTxt:
    def test_non_prod_host_disallows_everything(self, seo_client: TestClient) -> None:
        """On any host other than the production domains, deny all crawlers
        so dev / preview environments aren't indexed."""
        resp = seo_client.get("/robots.txt", headers={"host": "hub-dev.decision.ai"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        assert "Disallow: /" in resp.text
        assert "Allow: /" not in resp.text

    def test_prod_host_allows_indexing(self, seo_client: TestClient) -> None:
        """On the canonical prod hosts, indexing is allowed and the
        sitemap location is advertised."""
        resp = seo_client.get("/robots.txt", headers={"host": "hub.decision.ai"})
        assert resp.status_code == 200
        assert "Allow: /" in resp.text
        assert "Sitemap: https://hub.decision.ai/sitemap.xml" in resp.text

    def test_localhost_disallows(self, seo_client: TestClient) -> None:
        """localhost is not in the prod allow-list."""
        resp = seo_client.get("/robots.txt", headers={"host": "localhost"})
        assert resp.status_code == 200
        assert "Disallow: /" in resp.text


class TestSitemapXml:
    def test_returns_valid_xml(self, seo_client: TestClient) -> None:
        """The sitemap is well-formed XML using the standard schema."""
        resp = seo_client.get("/sitemap.xml")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")

        # Parses without error → well-formed XML.
        root = ET.fromstring(resp.text)
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        assert root.tag == f"{ns}urlset"

        # The static landing-page URLs are always present.
        locs = {url.findtext(f"{ns}loc") for url in root.findall(f"{ns}url")}
        assert "https://hub.decision.ai/" in locs
        assert "https://hub.decision.ai/skills" in locs
        assert "https://hub.decision.ai/orgs" in locs

    def test_lastmod_uses_today(self, seo_client: TestClient) -> None:
        """The static URLs are stamped with today's date."""
        resp = seo_client.get("/sitemap.xml")
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        assert today in resp.text
