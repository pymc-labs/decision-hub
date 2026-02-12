"""Backfill GitHub metadata (avatar, description, blog) for existing orgs.

One-off script to populate metadata for orgs discovered by the crawler
that never had a user log in via OAuth.

Usage:
    cd server && DHUB_ENV=dev uv run --package decision-hub-server \
        python -m decision_hub.scripts.backfill_org_metadata --github-token "$(gh auth token)"
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import UUID

import httpx
import sqlalchemy as sa

from decision_hub.infra.database import (
    create_engine,
    organizations_table,
    update_org_github_metadata,
)
from decision_hub.settings import create_settings

_GITHUB_API = "https://api.github.com"
_MAX_WORKERS = 30


def _log(msg: str) -> None:
    """Print with immediate flush for non-TTY environments."""
    print(msg, flush=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill GitHub metadata for orgs missing github_synced_at.",
    )
    parser.add_argument(
        "--github-token",
        type=str,
        required=True,
        help="GitHub PAT for API requests",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without making changes",
    )
    return parser.parse_args(argv)


def _fetch_metadata(client: httpx.Client, slug: str, is_personal: bool) -> dict:
    """Fetch GitHub metadata for an org/user using a persistent HTTP client.

    Tries /orgs/{slug} first for non-personal accounts; falls back to
    /users/{slug} if the org endpoint returns non-200.
    """
    endpoints = (
        [f"{_GITHUB_API}/users/{slug}"]
        if is_personal
        else [f"{_GITHUB_API}/orgs/{slug}", f"{_GITHUB_API}/users/{slug}"]
    )
    for endpoint in endpoints:
        resp = client.get(endpoint, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            is_user = "/users/" in endpoint
            description = data.get("bio") if is_user else data.get("description")
            return {
                "avatar_url": data.get("avatar_url") or None,
                "email": data.get("email") or None,
                "description": description or None,
                "blog": data.get("blog") or None,
            }
    return {}


def _fetch_one(client: httpx.Client, org_id: UUID, slug: str, is_personal: bool) -> tuple[UUID, str, dict]:
    """Fetch metadata for a single org. Returns (org_id, slug, meta_dict)."""
    try:
        meta = _fetch_metadata(client, slug, is_personal)
    except httpx.HTTPError:
        meta = {}
    return org_id, slug, meta


def main() -> None:
    args = parse_args()
    env = os.environ.get("DHUB_ENV", "dev")
    settings = create_settings(env)
    engine = create_engine(settings.database_url)

    # Find all orgs where github_synced_at is NULL
    stmt = (
        sa.select(
            organizations_table.c.id,
            organizations_table.c.slug,
            organizations_table.c.is_personal,
        )
        .where(organizations_table.c.github_synced_at.is_(None))
        .order_by(organizations_table.c.slug)
    )

    with engine.connect() as conn:
        rows = conn.execute(stmt).fetchall()

    total = len(rows)
    _log(f"Found {total} orgs with github_synced_at IS NULL")

    if args.dry_run:
        for row in rows:
            _log(f"  Would backfill: {row.slug} (personal={row.is_personal})")
        return

    if total == 0:
        return

    # Phase 1: Fetch all metadata concurrently
    _log(f"Fetching metadata from GitHub ({_MAX_WORKERS} concurrent)...")
    results: list[tuple[UUID, str, dict]] = []
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {args.github_token}",
    }

    with httpx.Client(headers=headers) as client, ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {executor.submit(_fetch_one, client, row.id, row.slug, row.is_personal): row.slug for row in rows}
        for done, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            if done % 100 == 0:
                _log(f"  Fetched {done}/{total}")

    _log(f"  Fetched {total}/{total}")

    # Phase 2: Batch DB writes in a single transaction
    updated = 0
    failed = 0
    skipped = 0

    with engine.begin() as conn:
        for org_id, _slug, meta in results:
            if not meta:
                failed += 1
                continue
            if not any(meta.values()):
                skipped += 1
                continue
            update_org_github_metadata(
                conn,
                org_id,
                avatar_url=meta.get("avatar_url"),
                email=meta.get("email"),
                description=meta.get("description"),
                blog=meta.get("blog"),
            )
            updated += 1

    _log(f"\nDone: {updated} updated, {skipped} skipped, {failed} failed (of {total})")
    sys.exit(0)


if __name__ == "__main__":
    main()
