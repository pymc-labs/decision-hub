"""Tests for decision_hub.api.seo_routes -- sitemap.xml and robots.txt.

These tests pin two contracts that have no other coverage:

* ``sitemap.xml`` includes static landing pages, every published public
  skill (with a per-row lastmod), and every org with a published skill,
  and the output is valid XML — XML-escaped where the inputs aren't
  trusted (skill/org slugs come from user input).
* ``robots.txt`` blocks indexing on every host except the production
  domains. Forgetting this on a dev / staging hostname is how unindexed
  preview environments end up in Google.
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
def seo_app(test_settings: MagicMock) -> FastAPI:
    """Minimal app exposing only the SEO router.

    We can't reuse ``test_app`` from conftest because the SEO routes
    need a real ``conn.execute()`` shape (iterable of rows), and the
    other test fixtures wire in the full router stack we don't need
    here.
    """
    app = FastAPI()
    app.state.settings = test_settings
    app.state.engine = MagicMock()
    app.state.s3_client = MagicMock()
    app.state.cache = TTLCache(default_ttl=60)
    app.include_router(seo_router)
    return app


@pytest.fixture
def seo_client(seo_app: FastAPI) -> TestClient:
    return TestClient(seo_app)


def _mock_engine_with_rows(seo_app: FastAPI, skill_rows: list, org_rows: list) -> None:
    """Wire the mocked engine so the SEO route's two queries return our rows."""
    conn = MagicMock()

    # The route executes two SELECTs in order: skills, then orgs.
    # We can't distinguish them by the SQL text here, so iterate.
    results_iter = iter([skill_rows, org_rows])
    conn.execute.side_effect = lambda *_args, **_kwargs: next(results_iter)

    # ``with engine.begin() as conn`` is the get_connection contract.
    cm = MagicMock()
    cm.__enter__.return_value = conn
    cm.__exit__.return_value = False
    seo_app.state.engine.begin.return_value = cm


class TestSitemapXml:
    """``/sitemap.xml`` advertises every public skill and org."""

    def test_returns_xml_with_static_pages(self, seo_app, seo_client):
        _mock_engine_with_rows(seo_app, [], [])

        resp = seo_client.get("/sitemap.xml")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        # Valid XML — ET.fromstring raises on malformed input.
        root = ET.fromstring(resp.text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [u.text for u in root.findall("sm:url/sm:loc", ns)]
        # Static landing pages are always present.
        assert "https://hub.decision.ai/" in locs
        assert "https://hub.decision.ai/skills" in locs
        assert "https://hub.decision.ai/orgs" in locs
        assert "https://hub.decision.ai/how-it-works" in locs

    def test_includes_skill_and_org_rows(self, seo_app, seo_client):
        skill_row = MagicMock()
        skill_row.org_slug = "acme"
        skill_row.skill_name = "doc-writer"
        skill_row.latest_published_at = datetime(2025, 6, 1, tzinfo=UTC)
        org_row = ("acme",)

        _mock_engine_with_rows(seo_app, [skill_row], [org_row])

        resp = seo_client.get("/sitemap.xml")

        assert resp.status_code == 200
        root = ET.fromstring(resp.text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        entries = {url.find("sm:loc", ns).text: url.find("sm:lastmod", ns).text for url in root.findall("sm:url", ns)}
        assert entries.get("https://hub.decision.ai/skills/acme/doc-writer") == "2025-06-01"
        assert "https://hub.decision.ai/orgs/acme" in entries

    def test_escapes_xml_special_chars_in_slugs(self, seo_app, seo_client):
        """Slugs are user input. If a malicious slug ever sneaks past
        validation, the sitemap must still produce valid XML rather
        than blowing up downstream consumers."""
        skill_row = MagicMock()
        skill_row.org_slug = "evil&co"
        skill_row.skill_name = "<script>"
        skill_row.latest_published_at = None
        _mock_engine_with_rows(seo_app, [skill_row], [])

        resp = seo_client.get("/sitemap.xml")

        assert resp.status_code == 200
        # The raw < and & must not appear unescaped.
        assert "<script>" not in resp.text
        assert "evil&co" not in resp.text
        # Standard XML escapes show up instead.
        assert "&amp;" in resp.text or "&lt;" in resp.text
        # And the output is still parseable.
        ET.fromstring(resp.text)

    def test_response_is_cached(self, seo_app, seo_client):
        """The second request short-circuits the two SELECT queries —
        defends against expensive sitemap regeneration under crawler
        hammering. (The connection itself is still acquired by FastAPI's
        dependency injection; only the queries are skipped.)"""
        skill_rows = [MagicMock(org_slug="acme", skill_name="s", latest_published_at=None)]
        _mock_engine_with_rows(seo_app, skill_rows, [("acme",)])
        seo_client.get("/sitemap.xml")

        # The first request executed two queries (skills + orgs).
        # Track that with a fresh side_effect that would raise if
        # called again — proving the cache skipped them on request 2.
        cm_conn = seo_app.state.engine.begin.return_value.__enter__.return_value
        cm_conn.execute.side_effect = AssertionError(
            "execute() must not be called when the sitemap is served from cache"
        )

        resp = seo_client.get("/sitemap.xml")

        assert resp.status_code == 200
        # Body matches the cached payload.
        assert "/skills/acme/s" in resp.text


class TestRobotsTxt:
    """``/robots.txt`` blocks crawlers everywhere except the prod hosts."""

    def test_blocks_indexing_on_non_prod_host(self, seo_client):
        # TestClient defaults to "testserver" as the hostname.
        resp = seo_client.get("/robots.txt")
        assert resp.status_code == 200
        assert "Disallow: /" in resp.text
        # No sitemap reference on non-prod — we don't want crawlers
        # discovering staging content.
        assert "Sitemap:" not in resp.text

    def test_allows_indexing_on_prod_host(self, seo_client):
        resp = seo_client.get("/robots.txt", headers={"host": "hub.decision.ai"})
        assert resp.status_code == 200
        assert "Allow: /" in resp.text
        assert "Sitemap: https://hub.decision.ai/sitemap.xml" in resp.text
