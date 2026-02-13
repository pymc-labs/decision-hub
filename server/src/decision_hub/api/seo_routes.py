"""SEO routes -- sitemap.xml and robots.txt for search engine crawlers."""

from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.engine import Connection

from decision_hub.api.deps import get_connection
from decision_hub.infra.database import organizations_table, skills_table

router = APIRouter(tags=["seo"])

_BASE_URL = "https://decisionhub.dev"


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml(conn: Connection = Depends(get_connection)) -> Response:
    """Generate a dynamic XML sitemap with all public skills and orgs."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    urls: list[tuple[str, str, str]] = [
        # (loc, lastmod, changefreq)
        (f"{_BASE_URL}/", today, "daily"),
        (f"{_BASE_URL}/skills", today, "daily"),
        (f"{_BASE_URL}/orgs", today, "daily"),
        (f"{_BASE_URL}/how-it-works", today, "monthly"),
    ]

    # Public skills
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
    for row in conn.execute(stmt):
        lastmod = (
            row.latest_published_at.strftime("%Y-%m-%d")
            if row.latest_published_at
            else today
        )
        urls.append(
            (f"{_BASE_URL}/skills/{row.org_slug}/{row.skill_name}", lastmod, "weekly")
        )

    # Public orgs (only those with at least one published skill)
    org_stmt = (
        sa.select(sa.distinct(organizations_table.c.slug))
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
        .order_by(organizations_table.c.slug)
    )
    for row in conn.execute(org_stmt):
        urls.append((f"{_BASE_URL}/orgs/{row[0]}", today, "weekly"))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for loc, lastmod, changefreq in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{loc}</loc>")
        lines.append(f"    <lastmod>{lastmod}</lastmod>")
        lines.append(f"    <changefreq>{changefreq}</changefreq>")
        lines.append("  </url>")
    lines.append("</urlset>")

    xml = "\n".join(lines)
    return Response(content=xml, media_type="application/xml")


@router.get("/robots.txt", include_in_schema=False)
def robots_txt() -> Response:
    """Serve robots.txt with sitemap reference."""
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {_BASE_URL}/sitemap.xml\n"
    )
    return Response(content=content, media_type="text/plain")
