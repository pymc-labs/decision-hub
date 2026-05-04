"""Tests for the SEO routes (sitemap.xml, robots.txt)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from decision_hub.api.deps import get_cache, get_connection, get_settings
from decision_hub.api.seo_routes import router as seo_router
from decision_hub.infra.cache import TTLCache


@pytest.fixture
def seo_app() -> FastAPI:
    """A minimal FastAPI app that mounts only the SEO router.

    SEO routes are mounted at the app root in production (no /v1 prefix), so
    we replicate that here. The connection dependency is overridden per-test
    to return rows that simulate published-skill output.
    """
    app = FastAPI()
    app.state.cache = TTLCache(default_ttl=60)
    app.state.settings = SimpleNamespace(cache_ttl_sitemap=300)
    app.include_router(seo_router)
    return app


def _mock_conn_with_rows(skills: list[tuple[str, str, datetime]], orgs: list[str]) -> MagicMock:
    """Build a SQLAlchemy-ish connection that yields the given rows.

    The first execute() call (the skills query) returns skill rows; the
    second (the distinct-orgs query) returns single-column org rows. The
    sitemap implementation iterates the result objects directly, so we
    return iterables.
    """
    skill_rows = [SimpleNamespace(org_slug=s[0], skill_name=s[1], latest_published_at=s[2]) for s in skills]
    org_rows = [(slug,) for slug in orgs]

    conn = MagicMock()
    conn.execute.side_effect = [skill_rows, org_rows]
    return conn


def test_sitemap_xml_includes_static_pages_and_public_skills(seo_app: FastAPI) -> None:
    """Static pages, every published skill, and every distinct org slug appear in the sitemap."""
    conn = _mock_conn_with_rows(
        skills=[
            ("acme", "auditor", datetime(2026, 1, 15, tzinfo=UTC)),
            ("widgets", "linter", datetime(2026, 4, 2, tzinfo=UTC)),
        ],
        orgs=["acme", "widgets"],
    )
    seo_app.dependency_overrides[get_connection] = lambda: conn
    client = TestClient(seo_app)

    resp = client.get("/sitemap.xml")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    body = resp.text
    # Static pages
    assert "https://hub.decision.ai/" in body
    assert "https://hub.decision.ai/skills" in body
    assert "https://hub.decision.ai/orgs" in body
    assert "https://hub.decision.ai/how-it-works" in body
    # Skill pages
    assert "https://hub.decision.ai/skills/acme/auditor" in body
    assert "https://hub.decision.ai/skills/widgets/linter" in body
    # Org pages
    assert "https://hub.decision.ai/orgs/acme" in body
    assert "https://hub.decision.ai/orgs/widgets" in body
    # Lastmod uses the per-skill latest_published_at when present.
    assert "<lastmod>2026-01-15</lastmod>" in body


def test_sitemap_xml_uses_cache_on_second_call(seo_app: FastAPI) -> None:
    """The sitemap is cached for ``cache_ttl_sitemap`` seconds; second call hits cache."""
    conn = _mock_conn_with_rows(skills=[], orgs=[])
    seo_app.dependency_overrides[get_connection] = lambda: conn
    client = TestClient(seo_app)

    first = client.get("/sitemap.xml")
    second = client.get("/sitemap.xml")

    assert first.status_code == 200
    assert second.status_code == 200
    # The DB execute() chain is consumed exactly once across both calls.
    # On the cache hit, no execute() runs at all.
    assert conn.execute.call_count == 2  # one skills query + one orgs query, total
    assert first.text == second.text
    assert first.headers["Cache-Control"] == "public, max-age=300"


def test_sitemap_skips_cache_when_ttl_zero(seo_app: FastAPI) -> None:
    """A zero TTL means the response is regenerated on every request and no Cache-Control is set."""
    seo_app.state.settings = SimpleNamespace(cache_ttl_sitemap=0)
    # We need two full sets of rows because execute() is called twice per request.
    conn = MagicMock()
    conn.execute.side_effect = [[], [], [], []]
    seo_app.dependency_overrides[get_connection] = lambda: conn
    # Reset cache so we don't pick up something from another test.
    seo_app.dependency_overrides[get_cache] = lambda: TTLCache(default_ttl=60)
    seo_app.dependency_overrides[get_settings] = lambda: SimpleNamespace(cache_ttl_sitemap=0)
    client = TestClient(seo_app)

    first = client.get("/sitemap.xml")
    second = client.get("/sitemap.xml")

    assert first.status_code == 200
    assert second.status_code == 200
    assert "Cache-Control" not in first.headers
    # Both requests hit the DB (4 execute calls total: 2 per request).
    assert conn.execute.call_count == 4


def test_robots_txt_blocks_non_prod_hosts(seo_app: FastAPI) -> None:
    """On non-prod hostnames, robots.txt disallows everything to prevent indexing."""
    client = TestClient(seo_app)

    resp = client.get("/robots.txt")  # TestClient host defaults to "testserver"

    assert resp.status_code == 200
    assert "Disallow: /" in resp.text
    assert "Sitemap:" not in resp.text


def test_robots_txt_allows_prod_hosts(seo_app: FastAPI) -> None:
    """On the prod hostname, robots.txt allows everything and points at the sitemap."""
    client = TestClient(seo_app)

    resp = client.get("/robots.txt", headers={"host": "hub.decision.ai"})

    assert resp.status_code == 200
    assert "Allow: /" in resp.text
    assert "Sitemap: https://hub.decision.ai/sitemap.xml" in resp.text
