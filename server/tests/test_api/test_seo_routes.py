"""Tests for sitemap.xml caching behaviour.

Earlier the sitemap endpoint stashed a Starlette ``Response`` object in the
TTL cache. Response objects carry mutable per-request state (headers,
charset finalisation when first sent), so reusing them across requests is
risky. The cache should hold the rendered XML string and the route should
build a fresh Response on each hit.
"""

from unittest.mock import MagicMock

from fastapi.responses import Response

from decision_hub.api.seo_routes import _build_sitemap_xml, sitemap_xml
from decision_hub.infra.cache import TTLCache


class TestSitemapCaching:
    def _empty_conn(self) -> MagicMock:
        """A conn whose ``execute()`` returns an empty iterator."""
        conn = MagicMock()
        conn.execute.return_value = iter([])
        return conn

    def test_cache_stores_xml_string_not_response_object(self) -> None:
        """Caching a Response object is unsafe — cache the body instead."""
        conn = self._empty_conn()
        cache = TTLCache(default_ttl=60)
        settings = MagicMock()
        settings.cache_ttl_sitemap = 60

        first = sitemap_xml(conn=conn, cache=cache, settings=settings)

        assert isinstance(first, Response)
        cached_value = cache.get("sitemap_xml")
        assert isinstance(cached_value, str), (
            f"Expected cache to hold the XML string, got {type(cached_value).__name__}"
        )
        assert cached_value.startswith('<?xml version="1.0"')

    def test_cache_hit_returns_fresh_response_with_same_body(self) -> None:
        """A second call must reuse the cached XML but build a new Response."""
        conn = self._empty_conn()
        cache = TTLCache(default_ttl=60)
        settings = MagicMock()
        settings.cache_ttl_sitemap = 60

        first = sitemap_xml(conn=conn, cache=cache, settings=settings)
        first_call_count = conn.execute.call_count

        second_conn = self._empty_conn()  # Distinct conn proves we skipped DB.
        second = sitemap_xml(conn=second_conn, cache=cache, settings=settings)

        assert second_conn.execute.call_count == 0, "cache hit must skip DB queries"
        assert conn.execute.call_count == first_call_count
        assert first.body == second.body
        assert first is not second, "must return a fresh Response per request"

    def test_ttl_zero_disables_cache(self) -> None:
        """When the TTL setting is zero, every call should re-render."""
        cache = TTLCache(default_ttl=60)
        settings = MagicMock()
        settings.cache_ttl_sitemap = 0

        first_conn = self._empty_conn()
        second_conn = self._empty_conn()
        sitemap_xml(conn=first_conn, cache=cache, settings=settings)
        sitemap_xml(conn=second_conn, cache=cache, settings=settings)

        assert first_conn.execute.called
        assert second_conn.execute.called
        assert cache.get("sitemap_xml") is None


class TestSitemapBody:
    def test_includes_root_and_static_pages(self) -> None:
        conn = MagicMock()
        conn.execute.return_value = iter([])

        xml = _build_sitemap_xml(conn)

        assert "https://hub.decision.ai/" in xml
        assert "/skills" in xml
        assert "/orgs" in xml
        assert "/how-it-works" in xml
        assert xml.startswith('<?xml version="1.0"')
        assert xml.rstrip().endswith("</urlset>")
