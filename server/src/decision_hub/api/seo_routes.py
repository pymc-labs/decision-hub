"""SEO routes -- sitemap.xml and robots.txt for search engine crawlers."""

from datetime import UTC, datetime
from xml.sax.saxutils import escape

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.engine import Connection

from decision_hub.api.deps import get_cache, get_connection, get_settings
from decision_hub.infra.cache import TTLCache
from decision_hub.infra.database import organizations_table, skills_table
from decision_hub.settings import Settings

router = APIRouter(tags=["seo"])

_BASE_URL = "https://hub.decision.ai"


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml(
    conn: Connection = Depends(get_connection),
    cache: TTLCache = Depends(get_cache),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Generate a dynamic XML sitemap with all public skills and orgs.

    The rendered XML body is cached as a string so every response can
    reuse a fresh ``Response`` object.  Caching the ``Response`` itself
    would share mutable headers (e.g. ``content-length`` stamped during
    ``__call__``) across concurrent requests.
    """
    ttl = settings.cache_ttl_sitemap
    xml: str | None = cache.get("sitemap_xml") if ttl else None

    if xml is None:
        xml = _render_sitemap(conn)
        if ttl:
            cache.set("sitemap_xml", xml, ttl=ttl)

    headers = {"Cache-Control": f"public, max-age={ttl}"} if ttl else {}
    return Response(content=xml, media_type="application/xml", headers=headers)


def _render_sitemap(conn: Connection) -> str:
    """Query the DB and render the sitemap XML.  Extracted so the cached
    representation is a plain string and the HTTP wrapper stays tiny."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    urls: list[tuple[str, str, str]] = [
        # (loc, lastmod, changefreq)
        (f"{_BASE_URL}/", today, "daily"),
        (f"{_BASE_URL}/skills", today, "daily"),
        (f"{_BASE_URL}/orgs", today, "daily"),
        (f"{_BASE_URL}/how-it-works", today, "monthly"),
    ]

    # Single query delivers both the skill URLs and (via the unique
    # ``org_slug`` values) the org URLs, replacing the previous pattern
    # of two near-identical queries hitting the same join.
    stmt = (
        sa.select(
            organizations_table.c.slug.label("org_slug"),
            skills_table.c.name.label("skill_name"),
            skills_table.c.latest_published_at,
        )
        .select_from(
            skills_table.join(
                organizations_table,
                skills_table.c.org_id == organizations_table.c.id,
            )
        )
        .where(
            skills_table.c.latest_semver.isnot(None),
            skills_table.c.visibility == "public",
        )
        .order_by(organizations_table.c.slug, skills_table.c.name)
    )

    org_slugs: list[str] = []
    seen_orgs: set[str] = set()
    for row in conn.execute(stmt):
        lastmod = row.latest_published_at.strftime("%Y-%m-%d") if row.latest_published_at else today
        urls.append((f"{_BASE_URL}/skills/{row.org_slug}/{row.skill_name}", lastmod, "weekly"))
        if row.org_slug not in seen_orgs:
            seen_orgs.add(row.org_slug)
            org_slugs.append(row.org_slug)

    for slug in org_slugs:
        urls.append((f"{_BASE_URL}/orgs/{slug}", today, "weekly"))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for loc, lastmod, changefreq in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(loc)}</loc>")
        lines.append(f"    <lastmod>{escape(lastmod)}</lastmod>")
        lines.append(f"    <changefreq>{escape(changefreq)}</changefreq>")
        lines.append("  </url>")
    lines.append("</urlset>")

    return "\n".join(lines)


_PROD_HOSTS = {"hub.decision.ai", "decisionhub.dev"}


@router.get("/robots.txt", include_in_schema=False)
def robots_txt(request: Request) -> Response:
    """Serve robots.txt — disallow everything on non-prod to prevent indexing."""
    if request.url.hostname not in _PROD_HOSTS:
        content = "User-agent: *\nDisallow: /\n"
    else:
        content = f"User-agent: *\nAllow: /\n\nSitemap: {_BASE_URL}/sitemap.xml\n"
    return Response(content=content, media_type="text/plain")
