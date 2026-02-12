"""Backfill GitHub metadata and fix is_personal for existing orgs.

One-off script to populate metadata for orgs discovered by the crawler
that never had a user log in via OAuth, and to fix the is_personal flag
for orgs that were incorrectly classified.

Usage:
    cd server && DHUB_ENV=dev uv run --package decision-hub-server \
        python -m decision_hub.scripts.backfill_org_metadata --github-token "$(gh auth token)"
    cd server && DHUB_ENV=dev uv run --package decision-hub-server \
        python -m decision_hub.scripts.backfill_org_metadata fix-is-personal --github-token "$(gh auth token)"
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


def _make_github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
    }


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--github-token", type=str, required=True, help="GitHub PAT")
    parser.add_argument("--dry-run", action="store_true")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill org metadata and fix classifications.",
    )
    sub = parser.add_subparsers(dest="command")

    # "metadata" subcommand (also the default when no subcommand given)
    meta_cmd = sub.add_parser("metadata", help="Backfill GitHub metadata for unsynced orgs")
    _add_common_args(meta_cmd)

    # "fix-is-personal" subcommand
    fix_cmd = sub.add_parser("fix-is-personal", help="Fix is_personal flag using GitHub API")
    _add_common_args(fix_cmd)

    args, _remaining = parser.parse_known_args(argv)

    # Default to "metadata" when no subcommand given
    if args.command is None:
        args = parser.parse_args(["metadata"] + (argv if argv else sys.argv[1:]))

    return args


# ---------------------------------------------------------------------------
# Metadata backfill
# ---------------------------------------------------------------------------


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


def _fetch_metadata_one(client: httpx.Client, org_id: UUID, slug: str, is_personal: bool) -> tuple[UUID, str, dict]:
    """Fetch metadata for a single org. Returns (org_id, slug, meta_dict)."""
    try:
        meta = _fetch_metadata(client, slug, is_personal)
    except httpx.HTTPError:
        meta = {}
    return org_id, slug, meta


def backfill_metadata(engine: sa.engine.Engine, token: str, *, dry_run: bool) -> None:
    """Backfill GitHub metadata for orgs where github_synced_at is NULL."""
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

    if dry_run:
        for row in rows:
            _log(f"  Would backfill: {row.slug} (personal={row.is_personal})")
        return

    if total == 0:
        return

    _log(f"Fetching metadata from GitHub ({_MAX_WORKERS} concurrent)...")
    results: list[tuple[UUID, str, dict]] = []

    with (
        httpx.Client(headers=_make_github_headers(token)) as client,
        ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor,
    ):
        futures = {
            executor.submit(_fetch_metadata_one, client, row.id, row.slug, row.is_personal): row.slug for row in rows
        }
        for done, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            if done % 100 == 0:
                _log(f"  Fetched {done}/{total}")

    _log(f"  Fetched {total}/{total}")

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


# ---------------------------------------------------------------------------
# Fix is_personal classification
# ---------------------------------------------------------------------------


def _fetch_type(client: httpx.Client, slug: str) -> str | None:
    """Return 'User' or 'Organization' for a GitHub account, or None on error."""
    resp = client.get(f"{_GITHUB_API}/users/{slug}", timeout=15)
    if resp.status_code == 200:
        return resp.json().get("type")
    return None


def _fetch_type_one(client: httpx.Client, org_id: UUID, slug: str) -> tuple[UUID, str, str | None]:
    try:
        gh_type = _fetch_type(client, slug)
    except httpx.HTTPError:
        gh_type = None
    return org_id, slug, gh_type


def fix_is_personal(engine: sa.engine.Engine, token: str, *, dry_run: bool) -> None:
    """Fix is_personal for orgs where is_personal=False but GitHub type is User."""
    stmt = (
        sa.select(
            organizations_table.c.id,
            organizations_table.c.slug,
        )
        .where(organizations_table.c.is_personal.is_(False))
        .order_by(organizations_table.c.slug)
    )

    with engine.connect() as conn:
        rows = conn.execute(stmt).fetchall()

    total = len(rows)
    _log(f"Found {total} orgs with is_personal=False, checking GitHub type...")

    results: list[tuple[UUID, str, str | None]] = []

    with (
        httpx.Client(headers=_make_github_headers(token)) as client,
        ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor,
    ):
        futures = {executor.submit(_fetch_type_one, client, row.id, row.slug): row.slug for row in rows}
        for done, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            if done % 100 == 0:
                _log(f"  Checked {done}/{total}")

    _log(f"  Checked {total}/{total}")

    to_fix = [(org_id, slug) for org_id, slug, gh_type in results if gh_type == "User"]
    _log(f"  {len(to_fix)} need is_personal=True (actual GitHub Users)")

    if dry_run:
        for _org_id, slug in to_fix:
            _log(f"  Would fix: {slug}")
        return

    if not to_fix:
        return

    with engine.begin() as conn:
        for org_id, _slug in to_fix:
            conn.execute(
                sa.update(organizations_table).where(organizations_table.c.id == org_id).values(is_personal=True)
            )

    _log(f"Fixed {len(to_fix)} orgs → is_personal=True")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    args = parse_args()
    env = os.environ.get("DHUB_ENV", "dev")
    settings = create_settings(env)
    engine = create_engine(settings.database_url)

    if args.command == "fix-is-personal":
        fix_is_personal(engine, args.github_token, dry_run=args.dry_run)
    elif args.command == "metadata":
        backfill_metadata(engine, args.github_token, dry_run=args.dry_run)

    sys.exit(0)


if __name__ == "__main__":
    main()
