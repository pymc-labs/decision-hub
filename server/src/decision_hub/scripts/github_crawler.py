"""Multi-strategy GitHub crawler for discovering public repos with SKILL.md files.

Discovers skills across GitHub using multiple search strategies to work around
the 1,000-result-per-query API limit, then publishes each skill into Decision Hub
under its GitHub owner's organization (creating the org if needed).

Resumable: saves discovery results and processing progress to a JSON checkpoint
file. On restart, skips discovery if the checkpoint exists and resumes processing
from where it left off.

Usage (from server/):
    DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler \
        --github-token ghp_... \
        --max-repos 50

    # Resume after a crash (uses existing checkpoint):
    DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler \
        --github-token ghp_... \
        --resume

    # Force re-discovery (ignore checkpoint):
    DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler \
        --github-token ghp_... \
        --fresh

Strategies:
    1. File-size partitioning — split filename:SKILL.md by size ranges
    2. Path-based searches — target common skill paths (.claude/, skills/, etc.)
    3. Topic-based discovery — find repos by topic, then scan for SKILL.md
    4. Fork scanning — check forks of popular skill repos
    5. Curated list parsing — parse known awesome-lists for linked repos
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import re
import shutil
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import UUID

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# Default checkpoint file location (relative to cwd, i.e. server/)
DEFAULT_CHECKPOINT_PATH = Path("crawl_checkpoint.json")

# Well-known skill topics on GitHub
SKILL_TOPICS = [
    "agent-skills",
    "claude-skills",
    "ai-agent-skills",
    "claude-code-skills",
    "codex-skills",
    "copilot-skills",
    "cursor-skills",
    "windsurf-skills",
]

# Well-known curated lists of skills
CURATED_LIST_REPOS = [
    "skillmatic-ai/awesome-agent-skills",
    "hoodini/ai-agents-skills",
    "CommandCodeAI/agent-skills",
    "heilcheng/awesome-agent-skills",
]

# Paths where skills commonly live
SKILL_PATHS = ["skills", ".claude", ".codex", ".github", "agent-skills"]

# File size ranges for partitioning (bytes) — splits the SKILL.md search space
SIZE_RANGES = [
    (0, 500),
    (501, 1000),
    (1001, 2000),
    (2001, 5000),
    (5001, 10000),
    (10001, 50000),
    (50001, None),  # >50KB
]

# Slug validation pattern (matches the server's org slug rules)
_SLUG_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")

# Bot user identity — a special service account that the crawler uses to own
# orgs and publish skills.  It is added as an "admin" member to every org it
# touches so it can publish via the normal API path too.
BOT_GITHUB_ID = "0"
BOT_USERNAME = "dhub-crawler"


@dataclass
class DiscoveredRepo:
    """A GitHub repo that contains at least one SKILL.md file."""
    full_name: str  # "owner/repo"
    owner_login: str
    owner_type: str  # "User" or "Organization"
    clone_url: str
    stars: int = 0
    description: str = ""


@dataclass
class CrawlStats:
    """Running statistics for the crawl."""
    queries_made: int = 0
    repos_discovered: int = 0
    repos_processed: int = 0
    repos_skipped_checkpoint: int = 0
    skills_published: int = 0
    skills_skipped: int = 0
    skills_failed: int = 0
    orgs_created: int = 0
    emails_saved: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Checkpoint persistence — saves discovery + progress so we can resume
# ---------------------------------------------------------------------------


@dataclass
class Checkpoint:
    """Serialisable crawl state for resume support."""
    discovered_repos: dict[str, dict] = field(default_factory=dict)
    processed_repos: list[str] = field(default_factory=list)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))
        logger.info("Checkpoint saved: %d discovered, %d processed → %s",
                     len(self.discovered_repos), len(self.processed_repos), path)

    @classmethod
    def load(cls, path: Path) -> Checkpoint:
        data = json.loads(path.read_text())
        return cls(
            discovered_repos=data.get("discovered_repos", {}),
            processed_repos=data.get("processed_repos", []),
        )

    def mark_processed(self, full_name: str, path: Path) -> None:
        """Record that a repo was processed and flush to disk immediately."""
        self.processed_repos.append(full_name)
        self.save(path)


def _repo_to_dict(repo: DiscoveredRepo) -> dict:
    return asdict(repo)


def _dict_to_repo(d: dict) -> DiscoveredRepo:
    return DiscoveredRepo(**d)


# ---------------------------------------------------------------------------
# GitHub API client with rate-limit handling
# ---------------------------------------------------------------------------


class GitHubClient:
    """Thin wrapper around the GitHub REST API with rate-limit backoff."""

    def __init__(self, token: str | None = None):
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=GITHUB_API,
            headers=headers,
            timeout=30,
        )
        self._rate_limit_remaining = 999
        self._rate_limit_reset = 0.0

    def close(self):
        self._client.close()

    def get(self, path: str, params: dict | None = None) -> httpx.Response:
        self._wait_for_rate_limit()
        resp = self._client.get(path, params=params)
        self._update_rate_limit(resp)

        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            wait = max(self._rate_limit_reset - time.time(), 5)
            logger.warning("Rate limited. Waiting %.0fs...", wait)
            time.sleep(wait + 1)
            resp = self._client.get(path, params=params)
            self._update_rate_limit(resp)

        return resp

    def _wait_for_rate_limit(self):
        if self._rate_limit_remaining < 3:
            wait = max(self._rate_limit_reset - time.time(), 1)
            logger.info("Rate limit low (%d remaining). Waiting %.0fs...",
                        self._rate_limit_remaining, wait)
            time.sleep(wait + 1)

    def _update_rate_limit(self, resp: httpx.Response):
        remaining = resp.headers.get("x-ratelimit-remaining")
        reset = resp.headers.get("x-ratelimit-reset")
        if remaining is not None:
            self._rate_limit_remaining = int(remaining)
        if reset is not None:
            self._rate_limit_reset = float(reset)


# ---------------------------------------------------------------------------
# Strategy 1: File-size partitioned search
# ---------------------------------------------------------------------------


def search_by_file_size(gh: GitHubClient, stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    """Search for SKILL.md files partitioned by file size to exceed the 1K limit."""
    repos: dict[str, DiscoveredRepo] = {}

    for lo, hi in SIZE_RANGES:
        if hi is None:
            size_q = f"size:>{lo}"
        else:
            size_q = f"size:{lo}..{hi}"

        query = f"filename:SKILL.md {size_q}"
        found = _run_code_search(gh, query, stats)
        repos.update(found)
        logger.info("Size range %s: found %d repos (total unique: %d)",
                     size_q, len(found), len(repos))

    return repos


# ---------------------------------------------------------------------------
# Strategy 2: Path-based search
# ---------------------------------------------------------------------------


def search_by_path(gh: GitHubClient, stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    """Search for SKILL.md in common skill directory paths."""
    repos: dict[str, DiscoveredRepo] = {}

    for skill_path in SKILL_PATHS:
        query = f"filename:SKILL.md path:{skill_path}"
        found = _run_code_search(gh, query, stats)
        repos.update(found)
        logger.info("Path '%s': found %d repos (total unique: %d)",
                     skill_path, len(found), len(repos))

    return repos


# ---------------------------------------------------------------------------
# Strategy 3: Topic-based discovery
# ---------------------------------------------------------------------------


def search_by_topic(gh: GitHubClient, stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    """Find repos by topic, then check if they contain SKILL.md."""
    repos: dict[str, DiscoveredRepo] = {}

    for topic in SKILL_TOPICS:
        page = 1
        while page <= 5:  # cap at 5 pages per topic
            resp = gh.get("/search/repositories", params={
                "q": f"topic:{topic}",
                "sort": "stars",
                "order": "desc",
                "per_page": 100,
                "page": page,
            })
            stats.queries_made += 1

            if resp.status_code != 200:
                logger.warning("Topic search '%s' page %d failed: %d",
                               topic, page, resp.status_code)
                break

            data = resp.json()
            items = data.get("items", [])
            if not items:
                break

            for item in items:
                full_name = item["full_name"]
                if full_name in repos:
                    continue
                repos[full_name] = DiscoveredRepo(
                    full_name=full_name,
                    owner_login=item["owner"]["login"],
                    owner_type=item["owner"]["type"],
                    clone_url=item["clone_url"],
                    stars=item.get("stargazers_count", 0),
                    description=item.get("description") or "",
                )

            if len(items) < 100:
                break
            page += 1
            time.sleep(1)  # be gentle with search API

        logger.info("Topic '%s': total unique repos so far: %d", topic, len(repos))

    return repos


# ---------------------------------------------------------------------------
# Strategy 4: Fork scanning
# ---------------------------------------------------------------------------


def scan_forks(
    gh: GitHubClient,
    popular_repos: list[str],
    stats: CrawlStats,
) -> dict[str, DiscoveredRepo]:
    """For popular skill repos, also discover their forks."""
    repos: dict[str, DiscoveredRepo] = {}

    for repo_name in popular_repos:
        page = 1
        while page <= 3:  # cap at 3 pages of forks
            resp = gh.get(f"/repos/{repo_name}/forks", params={
                "sort": "stargazers",
                "per_page": 100,
                "page": page,
            })
            stats.queries_made += 1

            if resp.status_code != 200:
                break

            forks = resp.json()
            if not forks:
                break

            for fork in forks:
                full_name = fork["full_name"]
                if full_name in repos:
                    continue
                repos[full_name] = DiscoveredRepo(
                    full_name=full_name,
                    owner_login=fork["owner"]["login"],
                    owner_type=fork["owner"]["type"],
                    clone_url=fork["clone_url"],
                    stars=fork.get("stargazers_count", 0),
                    description=fork.get("description") or "",
                )

            if len(forks) < 100:
                break
            page += 1

        logger.info("Forks of '%s': found %d", repo_name, len(repos))

    return repos


# ---------------------------------------------------------------------------
# Strategy 5: Curated list parsing
# ---------------------------------------------------------------------------


def parse_curated_lists(
    gh: GitHubClient,
    stats: CrawlStats,
) -> dict[str, DiscoveredRepo]:
    """Parse README files from curated awesome-lists for GitHub repo links."""
    repos: dict[str, DiscoveredRepo] = {}
    github_link_pattern = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)")

    for list_repo in CURATED_LIST_REPOS:
        resp = gh.get(f"/repos/{list_repo}/readme")
        stats.queries_made += 1

        if resp.status_code != 200:
            logger.warning("Could not fetch README for %s: %d", list_repo, resp.status_code)
            continue

        data = resp.json()
        try:
            content = base64.b64decode(data.get("content", "")).decode("utf-8")
        except Exception:
            logger.warning("Could not decode README for %s", list_repo)
            continue

        matches = github_link_pattern.findall(content)
        unique_refs = set()
        for match in matches:
            ref = match.rstrip("/").removesuffix(".git")
            if ref.count("/") == 1:
                unique_refs.add(ref)

        for ref in unique_refs:
            if ref in repos:
                continue
            detail_resp = gh.get(f"/repos/{ref}")
            stats.queries_made += 1
            if detail_resp.status_code != 200:
                continue
            detail = detail_resp.json()
            repos[ref] = DiscoveredRepo(
                full_name=ref,
                owner_login=detail["owner"]["login"],
                owner_type=detail["owner"]["type"],
                clone_url=detail["clone_url"],
                stars=detail.get("stargazers_count", 0),
                description=detail.get("description") or "",
            )

        logger.info("Curated list '%s': extracted %d unique repo refs", list_repo, len(unique_refs))

    return repos


# ---------------------------------------------------------------------------
# GitHub code search helper
# ---------------------------------------------------------------------------


def _run_code_search(
    gh: GitHubClient,
    query: str,
    stats: CrawlStats,
) -> dict[str, DiscoveredRepo]:
    """Run a GitHub code search query and extract unique repos from results."""
    repos: dict[str, DiscoveredRepo] = {}
    page = 1

    while page <= 10:  # GitHub caps at 1000 results = 10 pages of 100
        resp = gh.get("/search/code", params={
            "q": query,
            "per_page": 100,
            "page": page,
        })
        stats.queries_made += 1

        if resp.status_code == 422:
            logger.warning("Search query '%s' returned 422 — skipping", query)
            break
        if resp.status_code != 200:
            logger.warning("Search query '%s' page %d failed: %d",
                           query, page, resp.status_code)
            break

        data = resp.json()
        items = data.get("items", [])
        if not items:
            break

        for item in items:
            repo = item.get("repository", {})
            full_name = repo.get("full_name", "")
            if not full_name or full_name in repos:
                continue
            repos[full_name] = DiscoveredRepo(
                full_name=full_name,
                owner_login=repo["owner"]["login"],
                owner_type=repo["owner"].get("type", "User"),
                clone_url=repo.get("clone_url", f"https://github.com/{full_name}.git"),
                stars=repo.get("stargazers_count", 0),
                description=repo.get("description") or "",
            )

        if len(items) < 100:
            break
        page += 1
        # Code search has a stricter rate limit — pause between pages
        time.sleep(2)

    return repos


# ---------------------------------------------------------------------------
# Owner email lookup
# ---------------------------------------------------------------------------


def fetch_owner_email(gh: GitHubClient, login: str, owner_type: str) -> str | None:
    """Fetch the public email for a GitHub user or organization."""
    if owner_type == "Organization":
        resp = gh.get(f"/orgs/{login}")
    else:
        resp = gh.get(f"/users/{login}")

    if resp.status_code != 200:
        return None

    data = resp.json()
    email = data.get("email")
    return email if email else None


# ---------------------------------------------------------------------------
# Bot user + org membership
# ---------------------------------------------------------------------------


def ensure_crawler_bot_user(conn) -> UUID:
    """Create or find the dhub-crawler bot user.

    This service account is added as an "admin" member to every org the crawler
    touches, so it can publish via the normal API auth path as well.
    """
    from decision_hub.infra.database import upsert_user

    bot = upsert_user(conn, github_id=BOT_GITHUB_ID, username=BOT_USERNAME)
    return bot.id


def ensure_org(conn, slug: str, bot_user_id: UUID, email: str | None, stats: CrawlStats):
    """Create org if it doesn't exist, ensure the bot is an admin, update email."""
    from decision_hub.infra.database import (
        find_org_by_slug,
        find_org_member,
        insert_org_member,
        insert_organization,
        update_org_email,
    )

    org = find_org_by_slug(conn, slug)

    if org is None:
        org = insert_organization(conn, slug, bot_user_id, is_personal=False)
        insert_org_member(conn, org.id, bot_user_id, "owner")
        stats.orgs_created += 1
        logger.info("Created org: %s", slug)
    else:
        # Org already exists — make sure the bot is a member so it can publish
        existing = find_org_member(conn, org.id, bot_user_id)
        if existing is None:
            insert_org_member(conn, org.id, bot_user_id, "admin")
            logger.info("Added %s as admin to existing org: %s", BOT_USERNAME, slug)

    if email and not org.email:
        update_org_email(conn, org.id, email)
        stats.emails_saved += 1
        logger.info("Saved email for org '%s': %s", slug, email)

    return org


# ---------------------------------------------------------------------------
# Skill publishing pipeline (server-side, bypasses HTTP API)
# ---------------------------------------------------------------------------


def create_zip(path: Path) -> bytes:
    """Create an in-memory zip archive of a skill directory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(path.rglob("*")):
            if not file.is_file():
                continue
            relative = file.relative_to(path)
            parts = relative.parts
            if any(part.startswith(".") or part == "__pycache__" for part in parts):
                continue
            zf.write(file, relative)
    return buf.getvalue()


def publish_skill_to_db(
    conn,
    s3_client,
    bucket: str,
    org,
    skill_dir: Path,
    manifest,
    stats: CrawlStats,
) -> bool:
    """Publish a single skill directly to DB and S3 (bypasses HTTP layer).

    Returns True if published, False if skipped (already exists with same checksum).
    """
    from decision_hub.domain.publish import build_s3_key, validate_skill_name
    from decision_hub.infra.database import (
        find_skill,
        find_version,
        insert_skill,
        insert_version,
        resolve_latest_version,
        update_skill_description,
    )
    from decision_hub.infra.storage import compute_checksum, upload_skill_zip

    name = manifest.name
    description = manifest.description

    try:
        validate_skill_name(name)
    except ValueError:
        logger.warning("Invalid skill name '%s' — skipping", name)
        stats.skills_failed += 1
        return False

    zip_data = create_zip(skill_dir)
    checksum = compute_checksum(zip_data)

    # Upsert skill record
    skill = find_skill(conn, org.id, name)
    if skill is None:
        skill = insert_skill(conn, org.id, name, description)
    else:
        update_skill_description(conn, skill.id, description)

    # Determine version (auto-bump patch from latest, or 0.1.0 for first publish)
    latest = resolve_latest_version(conn, org.slug, name)
    if latest is not None:
        if latest.checksum == checksum:
            logger.info("  Skill '%s/%s' unchanged — skipping", org.slug, name)
            stats.skills_skipped += 1
            return False
        # Bump patch
        parts = latest.semver.split(".")
        parts[2] = str(int(parts[2]) + 1)
        version = ".".join(parts)
    else:
        version = "0.1.0"

    if find_version(conn, skill.id, version) is not None:
        logger.info("  Version %s already exists for %s/%s — skipping", version, org.slug, name)
        stats.skills_skipped += 1
        return False

    s3_key = build_s3_key(org.slug, name, version)
    upload_skill_zip(s3_client, bucket, s3_key, zip_data)

    insert_version(
        conn,
        skill_id=skill.id,
        semver=version,
        s3_key=s3_key,
        checksum=checksum,
        runtime_config=None,
        published_by=BOT_USERNAME,
        eval_status="pending",
    )

    logger.info("  Published %s/%s@%s", org.slug, name, version)
    stats.skills_published += 1
    return True


# ---------------------------------------------------------------------------
# Repo processing
# ---------------------------------------------------------------------------


def process_repo(
    repo: DiscoveredRepo,
    conn,
    s3_client,
    bucket: str,
    bot_user_id: UUID,
    gh: GitHubClient,
    stats: CrawlStats,
) -> None:
    """Clone a repo, discover skills, and publish each one."""
    from dhub.core.git_repo import clone_repo, discover_skills
    from dhub.core.manifest import parse_skill_md

    slug = repo.owner_login.lower()
    if not _SLUG_PATTERN.match(slug):
        logger.warning("Owner '%s' is not a valid org slug — skipping repo %s",
                        repo.owner_login, repo.full_name)
        return

    # Fetch owner email
    email = fetch_owner_email(gh, repo.owner_login, repo.owner_type)

    # Ensure the org exists and the bot user can publish into it
    org = ensure_org(conn, slug, bot_user_id, email, stats)

    # Clone and discover
    tmp_dir = None
    try:
        repo_root = clone_repo(repo.clone_url)
        tmp_dir = repo_root.parent
        skill_dirs = discover_skills(repo_root)

        if not skill_dirs:
            logger.info("No valid skills in %s", repo.full_name)
            return

        logger.info("Found %d skill(s) in %s", len(skill_dirs), repo.full_name)

        for skill_dir in skill_dirs:
            try:
                manifest = parse_skill_md(skill_dir / "SKILL.md")
                publish_skill_to_db(conn, s3_client, bucket, org, skill_dir, manifest, stats)
            except Exception as exc:
                logger.warning("  Failed to publish skill from %s: %s", skill_dir, exc)
                stats.skills_failed += 1

    except Exception as exc:
        logger.warning("Failed to process repo %s: %s", repo.full_name, exc)
        stats.errors.append(f"{repo.full_name}: {exc}")
    finally:
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

    stats.repos_processed += 1


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_crawler(
    github_token: str | None = None,
    max_repos: int | None = None,
    env: str = "dev",
    strategies: list[str] | None = None,
    checkpoint_path: Path = DEFAULT_CHECKPOINT_PATH,
    resume: bool = False,
    fresh: bool = False,
) -> CrawlStats:
    """Run the multi-strategy GitHub skills crawler.

    Args:
        github_token: GitHub personal access token (optional but recommended).
        max_repos: Maximum number of repos to process (None = unlimited).
        env: Decision Hub environment ('dev' or 'prod').
        strategies: List of strategies to run. Default = all.
            Options: 'size', 'path', 'topic', 'fork', 'curated'
        checkpoint_path: Path to the JSON checkpoint file.
        resume: If True, load checkpoint and skip already-processed repos.
        fresh: If True, delete any existing checkpoint and start from scratch.
    """
    from decision_hub.infra.database import create_engine
    from decision_hub.infra.storage import create_s3_client
    from decision_hub.settings import create_settings

    all_strategies = {"size", "path", "topic", "fork", "curated"}
    active = set(strategies) if strategies else all_strategies

    stats = CrawlStats()
    gh = GitHubClient(token=github_token)

    logger.info("Starting multi-strategy GitHub skills crawler (env=%s)", env)
    logger.info("Active strategies: %s", ", ".join(sorted(active)))

    # ---- Checkpoint handling ----
    if fresh and checkpoint_path.exists():
        checkpoint_path.unlink()
        logger.info("Deleted existing checkpoint (--fresh)")

    checkpoint = Checkpoint()
    already_processed: set[str] = set()

    if resume and checkpoint_path.exists():
        checkpoint = Checkpoint.load(checkpoint_path)
        already_processed = set(checkpoint.processed_repos)
        logger.info("Resumed from checkpoint: %d discovered, %d already processed",
                     len(checkpoint.discovered_repos), len(already_processed))

    # ---- Phase 1: Discovery ----
    if checkpoint.discovered_repos and resume:
        # Reuse cached discovery results
        all_repos = {k: _dict_to_repo(v) for k, v in checkpoint.discovered_repos.items()}
        logger.info("Using cached discovery: %d repos", len(all_repos))
    else:
        all_repos: dict[str, DiscoveredRepo] = {}

        if "size" in active:
            logger.info("=== Strategy 1: File-size partitioned search ===")
            all_repos.update(search_by_file_size(gh, stats))

        if "path" in active:
            logger.info("=== Strategy 2: Path-based search ===")
            all_repos.update(search_by_path(gh, stats))

        if "topic" in active:
            logger.info("=== Strategy 3: Topic-based discovery ===")
            all_repos.update(search_by_topic(gh, stats))

        if "curated" in active:
            logger.info("=== Strategy 5: Curated list parsing ===")
            all_repos.update(parse_curated_lists(gh, stats))

        if "fork" in active:
            logger.info("=== Strategy 4: Fork scanning ===")
            top_repos = sorted(all_repos.values(), key=lambda r: r.stars, reverse=True)[:10]
            popular_names = [r.full_name for r in top_repos]
            if popular_names:
                fork_repos = scan_forks(gh, popular_names, stats)
                all_repos.update(fork_repos)

        # Save discovery to checkpoint
        checkpoint.discovered_repos = {k: _repo_to_dict(v) for k, v in all_repos.items()}
        checkpoint.save(checkpoint_path)

    stats.repos_discovered = len(all_repos)
    logger.info("Discovery complete: %d unique repos found (%d API queries)",
                stats.repos_discovered, stats.queries_made)

    if not all_repos:
        logger.info("No repos discovered. Exiting.")
        gh.close()
        return stats

    # Sort by stars (process popular repos first)
    sorted_repos = sorted(all_repos.values(), key=lambda r: r.stars, reverse=True)
    if max_repos:
        sorted_repos = sorted_repos[:max_repos]

    # Filter out already-processed repos
    pending_repos = [r for r in sorted_repos if r.full_name not in already_processed]
    stats.repos_skipped_checkpoint = len(sorted_repos) - len(pending_repos)

    if stats.repos_skipped_checkpoint:
        logger.info("Skipping %d already-processed repos from checkpoint",
                     stats.repos_skipped_checkpoint)

    logger.info("Processing %d repos (%d total, %d from checkpoint)...",
                len(pending_repos), len(sorted_repos), stats.repos_skipped_checkpoint)

    if not pending_repos:
        logger.info("Nothing to process — all repos already done.")
        gh.close()
        return stats

    # ---- Phase 2: Connect to DB and S3, then process each repo ----
    settings = create_settings(env)
    engine = create_engine(settings.database_url)
    s3_client = create_s3_client(
        region=settings.aws_region,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
    )

    with engine.connect() as conn:
        bot_user_id = ensure_crawler_bot_user(conn)
        conn.commit()

        for i, repo in enumerate(pending_repos, 1):
            logger.info("[%d/%d] Processing %s (★ %d)",
                        i, len(pending_repos), repo.full_name, repo.stars)
            process_repo(repo, conn, s3_client, settings.s3_bucket, bot_user_id, gh, stats)
            conn.commit()

            # Flush progress after each repo so a crash loses at most one repo
            checkpoint.mark_processed(repo.full_name, checkpoint_path)

    gh.close()

    # ---- Summary ----
    logger.info("=" * 60)
    logger.info("CRAWL COMPLETE")
    logger.info("  API queries:          %d", stats.queries_made)
    logger.info("  Repos discovered:     %d", stats.repos_discovered)
    logger.info("  Repos processed:      %d", stats.repos_processed)
    logger.info("  Repos from checkpoint:%d", stats.repos_skipped_checkpoint)
    logger.info("  Skills published:     %d", stats.skills_published)
    logger.info("  Skills skipped:       %d", stats.skills_skipped)
    logger.info("  Skills failed:        %d", stats.skills_failed)
    logger.info("  Orgs created:         %d", stats.orgs_created)
    logger.info("  Emails saved:         %d", stats.emails_saved)
    if stats.errors:
        logger.info("  Errors:               %d", len(stats.errors))
        for err in stats.errors[:10]:
            logger.info("    - %s", err)
    logger.info("=" * 60)

    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Multi-strategy GitHub skills crawler for Decision Hub",
    )
    parser.add_argument(
        "--github-token",
        default=None,
        help="GitHub personal access token (recommended for higher rate limits)",
    )
    parser.add_argument(
        "--max-repos",
        type=int,
        default=None,
        help="Maximum number of repos to process (default: unlimited)",
    )
    parser.add_argument(
        "--env",
        default="dev",
        choices=["dev", "prod"],
        help="Decision Hub environment (default: dev)",
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=["size", "path", "topic", "fork", "curated"],
        default=None,
        help="Which discovery strategies to run (default: all)",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_CHECKPOINT_PATH,
        help="Path to checkpoint file (default: crawl_checkpoint.json)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint, skipping already-processed repos",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Delete existing checkpoint and start from scratch",
    )
    args = parser.parse_args()

    if args.resume and args.fresh:
        parser.error("--resume and --fresh are mutually exclusive")

    run_crawler(
        github_token=args.github_token,
        max_repos=args.max_repos,
        env=args.env,
        strategies=args.strategies,
        checkpoint_path=args.checkpoint,
        resume=args.resume,
        fresh=args.fresh,
    )


if __name__ == "__main__":
    main()
