"""Tests for the SEO routes (sitemap.xml, robots.txt).

Covers two regressions fixed in this PR:

1. The base URL is now read from ``Settings.site_base_url`` instead of being
   hardcoded to the prod domain. Dev / staging deployments should produce
   sitemaps pointing at themselves, not at prod.
2. The sitemap was running two queries against the same skill→org join.
   It now derives the org URL set in Python from the rows it already
   fetched. We assert the SELECT count to lock that in.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from decision_hub.api.deps import get_cache, get_connection, get_settings
from decision_hub.api.seo_routes import router as seo_router
from decision_hub.infra.cache import TTLCache


def _row(org_slug: str, skill_name: str, when: datetime | None = None):
    """Build a stand-in for a SQLAlchemy Row with the columns the sitemap reads."""
    return SimpleNamespace(
        org_slug=org_slug,
        skill_name=skill_name,
        latest_published_at=when,
    )


def _make_app(rows: list, base_url: str = "https://hub.decision.ai", ttl: int = 0):
    """Build a FastAPI app wired with a connection that returns ``rows`` once."""
    app = FastAPI()
    app.include_router(seo_router)

    settings = SimpleNamespace(site_base_url=base_url, cache_ttl_sitemap=ttl)
    cache = TTLCache(default_ttl=60)
    conn = MagicMock()
    conn.execute.return_value = iter(rows)

    def _override_settings():
        return settings

    def _override_cache():
        return cache

    def _override_conn():
        yield conn

    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_cache] = _override_cache
    app.dependency_overrides[get_connection] = _override_conn
    # Stash references for assertions
    app.state._test_conn = conn  # type: ignore[attr-defined]
    return app


class TestSitemapXml:
    def test_emits_skill_and_org_urls_with_configured_base(self) -> None:
        rows = [
            _row("acme", "alpha", datetime(2026, 1, 5, tzinfo=UTC)),
            _row("acme", "beta", None),
            _row("globex", "gamma", datetime(2026, 2, 1, tzinfo=UTC)),
        ]
        app = _make_app(rows, base_url="https://hub.dev.example/")
        with TestClient(app) as client:
            resp = client.get("/sitemap.xml")
        assert resp.status_code == 200
        body = resp.text
        # Trailing slash on configured base must be normalized
        assert "https://hub.dev.example//" not in body
        # Static + per-skill + per-org URLs all present
        assert "<loc>https://hub.dev.example/</loc>" in body
        assert "<loc>https://hub.dev.example/skills</loc>" in body
        assert "<loc>https://hub.dev.example/skills/acme/alpha</loc>" in body
        assert "<loc>https://hub.dev.example/skills/acme/beta</loc>" in body
        assert "<loc>https://hub.dev.example/skills/globex/gamma</loc>" in body
        # Each unique org appears exactly once
        assert body.count("<loc>https://hub.dev.example/orgs/acme</loc>") == 1
        assert body.count("<loc>https://hub.dev.example/orgs/globex</loc>") == 1
        # lastmod from row used when available
        assert "<lastmod>2026-01-05</lastmod>" in body

    def test_uses_single_db_query(self) -> None:
        """Previously two SELECTs ran against the same join. Now one suffices.

        Locking this with an explicit assertion catches a regression where a
        future change re-introduces the second DISTINCT query.
        """
        rows = [
            _row("acme", "alpha", datetime(2026, 1, 5, tzinfo=UTC)),
            _row("acme", "beta", None),
        ]
        app = _make_app(rows)
        with TestClient(app) as client:
            client.get("/sitemap.xml")
        conn = app.state._test_conn  # type: ignore[attr-defined]
        assert conn.execute.call_count == 1


class TestRobotsTxt:
    def test_dev_host_disallows_all(self) -> None:
        app = _make_app(rows=[], base_url="https://hub.dev.example")
        with TestClient(app, base_url="http://hub.dev.example") as client:
            resp = client.get("/robots.txt")
        assert resp.status_code == 200
        assert "Disallow: /" in resp.text
        assert "Sitemap:" not in resp.text

    def test_prod_host_uses_configured_sitemap_url(self) -> None:
        app = _make_app(rows=[], base_url="https://hub.decision.ai")
        with TestClient(app, base_url="http://hub.decision.ai") as client:
            resp = client.get("/robots.txt")
        assert resp.status_code == 200
        assert "Allow: /" in resp.text
        assert "Sitemap: https://hub.decision.ai/sitemap.xml" in resp.text
