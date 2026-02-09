"""Multi-strategy GitHub crawler for discovering public repos with SKILL.md files.

Discovers skills across GitHub using multiple search strategies to work around
the 1,000-result-per-query API limit, then publishes each skill into Decision Hub
under its GitHub owner's organization (creating the org if needed).

Processing runs on Modal (parallel workers) so no local disk space is needed.
Skills go through the full Gauntlet safety pipeline before publishing.

Usage (from server/):
    DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler \
        --github-token ghp_... \
        --max-repos 50 \
        --workers 5

    # Resume after a crash:
    DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler \
        --github-token ghp_... --resume

    # Force re-discovery:
    DHUB_ENV=dev uv run --package decision-hub-server python -m decision_hub.scripts.github_crawler \
        --github-token ghp_... --fresh
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
DEFAULT_CHECKPOINT_PATH = Path("crawl_checkpoint.json")
CLONE_TIMEOUT_SECONDS = 120

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

# File size ranges for partitioning (bytes)
SIZE_RANGES = [
    (0, 500),
    (501, 1000),
    (1001, 2000),
    (2001, 5000),
    (5001, 10000),
    (10001, 50000),
    (50001, None),
]

_SLUG_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")

BOT_GITHUB_ID = "0"
BOT_USERNAME = "dhub-crawler"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DiscoveredRepo:
    full_name: str
    owner_login: str
    owner_type: str
    clone_url: str
    stars: int = 0
    description: str = ""


@dataclass
class CrawlStats:
    queries_made: int = 0
    repos_discovered: int = 0
    repos_processed: int = 0
    repos_skipped_checkpoint: int = 0
    skills_published: int = 0
    skills_skipped: int = 0
    skills_failed: int = 0
    skills_quarantined: int = 0
    orgs_created: int = 0
    emails_saved: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Checkpoint persistence
# ---------------------------------------------------------------------------


@dataclass
class Checkpoint:
    discovered_repos: dict[str, dict] = field(default_factory=dict)
    processed_repos: list[str] = field(default_factory=list)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> Checkpoint:
        data = json.loads(path.read_text())
        return cls(
            discovered_repos=data.get("discovered_repos", {}),
            processed_repos=data.get("processed_repos", []),
        )

    def mark_processed(self, full_name: str, path: Path) -> None:
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
    def __init__(self, token: str | None = None):
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=GITHUB_API, headers=headers, timeout=30,
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
            logger.info("Rate limit low (%d). Waiting %.0fs...",
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
# Discovery strategies (run locally — lightweight HTTP calls)
# ---------------------------------------------------------------------------


def search_by_file_size(gh: GitHubClient, stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    repos: dict[str, DiscoveredRepo] = {}
    for lo, hi in SIZE_RANGES:
        size_q = f"size:>{lo}" if hi is None else f"size:{lo}..{hi}"
        query = f"filename:SKILL.md {size_q}"
        found = _run_code_search(gh, query, stats)
        repos.update(found)
        logger.info("Size %s: +%d (total %d)", size_q, len(found), len(repos))
    return repos


def search_by_path(gh: GitHubClient, stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    repos: dict[str, DiscoveredRepo] = {}
    for skill_path in SKILL_PATHS:
        query = f"filename:SKILL.md path:{skill_path}"
        found = _run_code_search(gh, query, stats)
        repos.update(found)
        logger.info("Path '%s': +%d (total %d)", skill_path, len(found), len(repos))
    return repos


def search_by_topic(gh: GitHubClient, stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    repos: dict[str, DiscoveredRepo] = {}
    for topic in SKILL_TOPICS:
        page = 1
        while page <= 5:
            resp = gh.get("/search/repositories", params={
                "q": f"topic:{topic}", "sort": "stars", "order": "desc",
                "per_page": 100, "page": page,
            })
            stats.queries_made += 1
            if resp.status_code != 200:
                break
            items = resp.json().get("items", [])
            if not items:
                break
            for item in items:
                fn = item["full_name"]
                if fn not in repos:
                    repos[fn] = DiscoveredRepo(
                        full_name=fn, owner_login=item["owner"]["login"],
                        owner_type=item["owner"]["type"], clone_url=item["clone_url"],
                        stars=item.get("stargazers_count", 0),
                        description=item.get("description") or "",
                    )
            if len(items) < 100:
                break
            page += 1
            time.sleep(1)
        logger.info("Topic '%s': total %d", topic, len(repos))
    return repos


def scan_forks(gh: GitHubClient, popular_repos: list[str], stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    repos: dict[str, DiscoveredRepo] = {}
    for repo_name in popular_repos:
        page = 1
        while page <= 3:
            resp = gh.get(f"/repos/{repo_name}/forks", params={
                "sort": "stargazers", "per_page": 100, "page": page,
            })
            stats.queries_made += 1
            if resp.status_code != 200:
                break
            forks = resp.json()
            if not forks:
                break
            for fork in forks:
                fn = fork["full_name"]
                if fn not in repos:
                    repos[fn] = DiscoveredRepo(
                        full_name=fn, owner_login=fork["owner"]["login"],
                        owner_type=fork["owner"]["type"], clone_url=fork["clone_url"],
                        stars=fork.get("stargazers_count", 0),
                        description=fork.get("description") or "",
                    )
            if len(forks) < 100:
                break
            page += 1
        logger.info("Forks of '%s': %d total", repo_name, len(repos))
    return repos


def parse_curated_lists(gh: GitHubClient, stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    repos: dict[str, DiscoveredRepo] = {}
    link_re = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)")
    for list_repo in CURATED_LIST_REPOS:
        resp = gh.get(f"/repos/{list_repo}/readme")
        stats.queries_made += 1
        if resp.status_code != 200:
            continue
        try:
            content = base64.b64decode(resp.json().get("content", "")).decode()
        except Exception:
            continue
        refs = {m.rstrip("/").removesuffix(".git") for m in link_re.findall(content)
                if m.rstrip("/").removesuffix(".git").count("/") == 1}
        for ref in refs:
            if ref in repos:
                continue
            dr = gh.get(f"/repos/{ref}")
            stats.queries_made += 1
            if dr.status_code != 200:
                continue
            d = dr.json()
            repos[ref] = DiscoveredRepo(
                full_name=ref, owner_login=d["owner"]["login"],
                owner_type=d["owner"]["type"], clone_url=d["clone_url"],
                stars=d.get("stargazers_count", 0), description=d.get("description") or "",
            )
        logger.info("Curated '%s': %d refs", list_repo, len(refs))
    return repos


def _run_code_search(gh: GitHubClient, query: str, stats: CrawlStats) -> dict[str, DiscoveredRepo]:
    repos: dict[str, DiscoveredRepo] = {}
    page = 1
    while page <= 10:
        resp = gh.get("/search/code", params={"q": query, "per_page": 100, "page": page})
        stats.queries_made += 1
        if resp.status_code in (422, 403):
            break
        if resp.status_code != 200:
            break
        items = resp.json().get("items", [])
        if not items:
            break
        for item in items:
            repo = item.get("repository", {})
            fn = repo.get("full_name", "")
            if fn and fn not in repos:
                repos[fn] = DiscoveredRepo(
                    full_name=fn, owner_login=repo["owner"]["login"],
                    owner_type=repo["owner"].get("type", "User"),
                    clone_url=repo.get("clone_url", f"https://github.com/{fn}.git"),
                    stars=repo.get("stargazers_count", 0),
                    description=repo.get("description") or "",
                )
        if len(items) < 100:
            break
        page += 1
        time.sleep(2)
    return repos


# ---------------------------------------------------------------------------
# Inlined git operations (avoids dependency on dhub-cli client package)
# ---------------------------------------------------------------------------


def clone_repo(repo_url: str, timeout: int = CLONE_TIMEOUT_SECONDS) -> Path:
    """Shallow-clone a repo into a temp directory. Returns the repo root path."""
    tmp = tempfile.mkdtemp(prefix="crawl-")
    dest = Path(tmp) / "repo"
    subprocess.run(
        ["git", "clone", "--depth", "1", "--single-branch", repo_url, str(dest)],
        capture_output=True, timeout=timeout, check=True,
    )
    return dest


def discover_skills(root: Path) -> list[Path]:
    """Walk a directory tree and return paths of dirs containing a valid SKILL.md."""
    skill_dirs = []
    for skill_md in sorted(root.rglob("SKILL.md")):
        if skill_md.is_file():
            skill_dirs.append(skill_md.parent)
    return skill_dirs


# ---------------------------------------------------------------------------
# GitHub email lookup (used inside Modal workers)
# ---------------------------------------------------------------------------


def fetch_owner_email(login: str, owner_type: str, token: str | None = None) -> str | None:
    """Fetch public email for a GitHub user/org. Works inside Modal containers."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    endpoint = f"https://api.github.com/orgs/{login}" if owner_type == "Organization" \
        else f"https://api.github.com/users/{login}"
    try:
        resp = httpx.get(endpoint, headers=headers, timeout=15)
        if resp.status_code == 200:
            email = resp.json().get("email")
            return email if email else None
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Modal worker: process_repo_on_modal (called by crawl_process_repo in modal_app.py)
# ---------------------------------------------------------------------------


def process_repo_on_modal(repo_dict: dict, bot_user_id_str: str, github_token: str | None) -> dict:
    """Process a single repo inside a Modal container.

    Clones the repo, discovers skills, runs the Gauntlet, and publishes.
    Returns a result dict for the CLI orchestrator.
    """
    from dhub_core.manifest import parse_skill_md

    from decision_hub.api.registry_service import run_gauntlet_pipeline
    from decision_hub.domain.publish import build_quarantine_s3_key, build_s3_key, validate_skill_name
    from decision_hub.domain.skill_manifest import extract_body, extract_description
    from decision_hub.infra.database import (
        create_engine,
        find_org_by_slug,
        find_org_member,
        find_skill,
        find_version,
        insert_audit_log,
        insert_org_member,
        insert_organization,
        insert_skill,
        insert_version,
        resolve_latest_version,
        update_org_email,
        update_skill_description,
        upsert_user,
    )
    from decision_hub.infra.storage import compute_checksum, create_s3_client, upload_skill_zip
    from decision_hub.settings import create_settings

    result = {
        "repo": repo_dict["full_name"],
        "status": "ok",
        "skills_published": 0,
        "skills_skipped": 0,
        "skills_failed": 0,
        "skills_quarantined": 0,
        "org_created": False,
        "email_saved": False,
        "error": None,
    }

    try:
        settings = create_settings()
        engine = create_engine(settings.database_url)
        s3_client = create_s3_client(
            region=settings.aws_region,
            access_key_id=settings.aws_access_key_id,
            secret_access_key=settings.aws_secret_access_key,
        )

        slug = repo_dict["owner_login"].lower()
        if not _SLUG_PATTERN.match(slug):
            result["status"] = "skipped"
            result["error"] = f"Invalid org slug: {slug}"
            return result

        bot_user_id = UUID(bot_user_id_str)

        # Fetch owner email
        email = fetch_owner_email(
            repo_dict["owner_login"], repo_dict["owner_type"], github_token,
        )

        with engine.connect() as conn:
            # Ensure bot user exists
            upsert_user(conn, github_id=BOT_GITHUB_ID, username=BOT_USERNAME)

            # Ensure org exists and bot is a member
            org = find_org_by_slug(conn, slug)
            if org is None:
                org = insert_organization(conn, slug, bot_user_id, is_personal=False)
                insert_org_member(conn, org.id, bot_user_id, "owner")
                result["org_created"] = True
            else:
                existing = find_org_member(conn, org.id, bot_user_id)
                if existing is None:
                    insert_org_member(conn, org.id, bot_user_id, "admin")

            if email and not org.email:
                update_org_email(conn, org.id, email)
                result["email_saved"] = True

            conn.commit()

            # Clone and discover
            repo_root = clone_repo(repo_dict["clone_url"])
            tmp_dir = repo_root.parent

            try:
                skill_dirs = discover_skills(repo_root)
                if not skill_dirs:
                    result["status"] = "no_skills"
                    return result

                for skill_dir in skill_dirs:
                    try:
                        _publish_one_skill(
                            conn, s3_client, settings, org, skill_dir, result,
                        )
                        conn.commit()
                    except Exception as exc:
                        result["skills_failed"] += 1
                        print(f"  Skill failed: {skill_dir.name}: {exc}", flush=True)
                        # Rollback the failed transaction so next skill can proceed
                        conn.rollback()
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    except subprocess.TimeoutExpired:
        result["status"] = "error"
        result["error"] = f"git clone timed out after {CLONE_TIMEOUT_SECONDS}s"
    except subprocess.CalledProcessError as exc:
        result["status"] = "error"
        result["error"] = f"git clone failed: {exc.stderr[:200] if exc.stderr else str(exc)}"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)[:500]

    return result


def _publish_one_skill(conn, s3_client, settings, org, skill_dir: Path, result: dict):
    """Parse, gauntlet-check, and publish a single skill. Mutates `result` counts."""
    from dhub_core.manifest import parse_skill_md

    from decision_hub.api.registry_service import run_gauntlet_pipeline
    from decision_hub.domain.publish import (
        build_quarantine_s3_key,
        build_s3_key,
        extract_for_evaluation,
        validate_skill_name,
    )
    from decision_hub.domain.skill_manifest import extract_body, extract_description
    from decision_hub.infra.database import (
        find_skill,
        find_version,
        insert_audit_log,
        insert_skill,
        insert_version,
        resolve_latest_version,
        update_skill_description,
    )
    from decision_hub.infra.storage import compute_checksum, upload_skill_zip

    manifest = parse_skill_md(skill_dir / "SKILL.md")
    name = manifest.name
    description = manifest.description

    validate_skill_name(name)

    # Create zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(skill_dir.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(skill_dir)
            if any(p.startswith(".") or p == "__pycache__" for p in rel.parts):
                continue
            zf.write(f, rel)
    zip_data = buf.getvalue()
    checksum = compute_checksum(zip_data)

    # Upsert skill record
    skill = find_skill(conn, org.id, name)
    if skill is None:
        skill = insert_skill(conn, org.id, name, description)
    else:
        update_skill_description(conn, skill.id, description)

    # Determine version
    latest = resolve_latest_version(conn, org.slug, name)
    if latest is not None:
        if latest.checksum == checksum:
            result["skills_skipped"] += 1
            return
        parts = latest.semver.split(".")
        parts[2] = str(int(parts[2]) + 1)
        version = ".".join(parts)
    else:
        version = "0.1.0"

    if find_version(conn, skill.id, version) is not None:
        result["skills_skipped"] += 1
        return

    # Extract content for gauntlet
    skill_md_content = (skill_dir / "SKILL.md").read_text()
    skill_md_body = extract_body(skill_md_content)
    desc = extract_description(skill_md_content)

    try:
        _, source_files, lockfile_content = extract_for_evaluation(zip_data)
    except ValueError:
        source_files = []
        lockfile_content = None

    # Run Gauntlet
    report, check_results, llm_reasoning = run_gauntlet_pipeline(
        skill_md_content, lockfile_content, source_files,
        name, desc, skill_md_body, settings,
    )

    if not report.passed:
        # Grade F — quarantine
        q_key = build_quarantine_s3_key(org.slug, name, version)
        insert_audit_log(
            conn, org_slug=org.slug, skill_name=name, semver=version,
            grade=report.grade, check_results=check_results,
            publisher=BOT_USERNAME, version_id=None,
            llm_reasoning=llm_reasoning, quarantine_s3_key=q_key,
        )
        conn.commit()
        upload_skill_zip(s3_client, settings.s3_bucket, q_key, zip_data)
        result["skills_quarantined"] += 1
        print(f"  Quarantined {org.slug}/{name}@{version} (grade {report.grade})", flush=True)
        return

    # Grade A/B/C — publish
    s3_key = build_s3_key(org.slug, name, version)
    upload_skill_zip(s3_client, settings.s3_bucket, s3_key, zip_data)

    version_record = insert_version(
        conn, skill_id=skill.id, semver=version, s3_key=s3_key,
        checksum=checksum, runtime_config=None,
        published_by=BOT_USERNAME, eval_status=report.grade,
    )

    insert_audit_log(
        conn, org_slug=org.slug, skill_name=name, semver=version,
        grade=report.grade, check_results=check_results,
        publisher=BOT_USERNAME, version_id=version_record.id,
        llm_reasoning=llm_reasoning, quarantine_s3_key=None,
    )

    result["skills_published"] += 1
    print(f"  Published {org.slug}/{name}@{version} (grade {report.grade})", flush=True)


# ---------------------------------------------------------------------------
# Main orchestrator (runs locally — dispatches to Modal)
# ---------------------------------------------------------------------------


def run_crawler(
    github_token: str | None = None,
    max_repos: int | None = None,
    env: str = "dev",
    strategies: list[str] | None = None,
    checkpoint_path: Path = DEFAULT_CHECKPOINT_PATH,
    resume: bool = False,
    fresh: bool = False,
    workers: int = 5,
) -> CrawlStats:
    """Run the multi-strategy GitHub skills crawler.

    Phase 1 (local): discover repos via GitHub API.
    Phase 2 (Modal): process repos in parallel with Gauntlet.
    """
    import modal
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

    from decision_hub.infra.database import create_engine, upsert_user
    from decision_hub.settings import create_settings

    all_strategies = {"size", "path", "topic", "fork", "curated"}
    active = set(strategies) if strategies else all_strategies

    stats = CrawlStats()
    gh = GitHubClient(token=github_token)

    # ---- Checkpoint handling ----
    if fresh and checkpoint_path.exists():
        checkpoint_path.unlink()

    checkpoint = Checkpoint()
    already_processed: set[str] = set()

    if resume and checkpoint_path.exists():
        checkpoint = Checkpoint.load(checkpoint_path)
        already_processed = set(checkpoint.processed_repos)
        print(f"Resumed: {len(checkpoint.discovered_repos)} discovered, "
              f"{len(already_processed)} already processed")

    # ---- Phase 1: Discovery (local) ----
    if checkpoint.discovered_repos and resume:
        all_repos = {k: _dict_to_repo(v) for k, v in checkpoint.discovered_repos.items()}
        print(f"Using cached discovery: {len(all_repos)} repos")
    else:
        all_repos: dict[str, DiscoveredRepo] = {}

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
            BarColumn(), MofNCompleteColumn(),
        ) as progress:
            task = progress.add_task("Discovering repos...", total=len(active))

            if "size" in active:
                all_repos.update(search_by_file_size(gh, stats))
                progress.update(task, advance=1, description=f"Discovering... ({len(all_repos)} repos)")

            if "path" in active:
                all_repos.update(search_by_path(gh, stats))
                progress.update(task, advance=1, description=f"Discovering... ({len(all_repos)} repos)")

            if "topic" in active:
                all_repos.update(search_by_topic(gh, stats))
                progress.update(task, advance=1, description=f"Discovering... ({len(all_repos)} repos)")

            if "curated" in active:
                all_repos.update(parse_curated_lists(gh, stats))
                progress.update(task, advance=1, description=f"Discovering... ({len(all_repos)} repos)")

            if "fork" in active:
                top = sorted(all_repos.values(), key=lambda r: r.stars, reverse=True)[:10]
                if top:
                    all_repos.update(scan_forks(gh, [r.full_name for r in top], stats))
                progress.update(task, advance=1, description=f"Discovery done: {len(all_repos)} repos")

        checkpoint.discovered_repos = {k: _repo_to_dict(v) for k, v in all_repos.items()}
        checkpoint.save(checkpoint_path)

    gh.close()

    stats.repos_discovered = len(all_repos)
    if not all_repos:
        print("No repos discovered.")
        return stats

    # Sort by stars, apply max_repos, filter processed
    sorted_repos = sorted(all_repos.values(), key=lambda r: r.stars, reverse=True)
    if max_repos:
        sorted_repos = sorted_repos[:max_repos]
    pending_repos = [r for r in sorted_repos if r.full_name not in already_processed]
    stats.repos_skipped_checkpoint = len(sorted_repos) - len(pending_repos)

    if not pending_repos:
        print("All repos already processed.")
        return stats

    print(f"Processing {len(pending_repos)} repos ({stats.repos_skipped_checkpoint} from checkpoint)")

    # ---- Setup: ensure bot user exists ----
    settings = create_settings(env)
    engine = create_engine(settings.database_url)
    with engine.connect() as conn:
        bot = upsert_user(conn, github_id=BOT_GITHUB_ID, username=BOT_USERNAME)
        conn.commit()
    bot_user_id = str(bot.id)

    # ---- Phase 2: Modal parallel processing ----
    fn = modal.Function.from_name(settings.modal_app_name, "crawl_process_repo")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("| pub:{task.fields[published]} fail:{task.fields[failed]} skip:{task.fields[skipped]}"),
    ) as progress:
        task = progress.add_task(
            "Processing repos", total=len(pending_repos),
            published=0, failed=0, skipped=0,
        )

        total_published = 0
        total_failed = 0
        total_skipped = 0

        # Process in batches of `workers` for controllable parallelism
        for batch_start in range(0, len(pending_repos), workers):
            batch = pending_repos[batch_start:batch_start + workers]
            batch_dicts = [_repo_to_dict(r) for r in batch]

            try:
                results_iter = fn.map(
                    batch_dicts,
                    kwargs={"bot_user_id": bot_user_id, "github_token": github_token},
                    return_exceptions=True,
                )

                for i, result in enumerate(results_iter):
                    repo_name = batch[i].full_name

                    if isinstance(result, Exception):
                        stats.errors.append(f"{repo_name}: {result}")
                        total_failed += 1
                    elif isinstance(result, dict):
                        if result.get("status") == "error":
                            stats.errors.append(f"{repo_name}: {result.get('error', 'unknown')}")
                        stats.skills_published += result.get("skills_published", 0)
                        stats.skills_skipped += result.get("skills_skipped", 0)
                        stats.skills_failed += result.get("skills_failed", 0)
                        stats.skills_quarantined += result.get("skills_quarantined", 0)
                        if result.get("org_created"):
                            stats.orgs_created += 1
                        if result.get("email_saved"):
                            stats.emails_saved += 1

                        total_published += result.get("skills_published", 0)
                        total_failed += result.get("skills_failed", 0) + result.get("skills_quarantined", 0)
                        total_skipped += result.get("skills_skipped", 0)

                    stats.repos_processed += 1
                    checkpoint.mark_processed(repo_name, checkpoint_path)

                    progress.update(
                        task, advance=1,
                        published=total_published, failed=total_failed, skipped=total_skipped,
                    )

            except Exception as exc:
                # Batch-level failure (e.g. Modal connectivity issue)
                for r in batch:
                    if r.full_name not in set(checkpoint.processed_repos):
                        stats.errors.append(f"{r.full_name}: batch error: {exc}")
                        stats.repos_processed += 1
                        checkpoint.mark_processed(r.full_name, checkpoint_path)
                        total_failed += 1
                        progress.update(task, advance=1, published=total_published,
                                        failed=total_failed, skipped=total_skipped)

    # ---- Summary ----
    print()
    print("=" * 60)
    print("CRAWL COMPLETE")
    print(f"  Repos discovered:     {stats.repos_discovered}")
    print(f"  Repos processed:      {stats.repos_processed}")
    print(f"  Repos from checkpoint:{stats.repos_skipped_checkpoint}")
    print(f"  Skills published:     {stats.skills_published}")
    print(f"  Skills quarantined:   {stats.skills_quarantined}")
    print(f"  Skills skipped:       {stats.skills_skipped}")
    print(f"  Skills failed:        {stats.skills_failed}")
    print(f"  Orgs created:         {stats.orgs_created}")
    print(f"  Emails saved:         {stats.emails_saved}")
    if stats.errors:
        print(f"  Errors:               {len(stats.errors)}")
        for err in stats.errors[:10]:
            print(f"    - {err}")
    print("=" * 60)

    return stats


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")

    parser = argparse.ArgumentParser(description="Multi-strategy GitHub skills crawler")
    parser.add_argument("--github-token", default=None,
                        help="GitHub PAT (recommended for rate limits)")
    parser.add_argument("--max-repos", type=int, default=None,
                        help="Max repos to process")
    parser.add_argument("--env", default="dev", choices=["dev", "prod"],
                        help="Decision Hub environment (default: dev)")
    parser.add_argument("--workers", type=int, default=5,
                        help="Max parallel Modal workers (default: 5)")
    parser.add_argument("--strategies", nargs="+",
                        choices=["size", "path", "topic", "fork", "curated"], default=None,
                        help="Discovery strategies (default: all)")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT_PATH,
                        help="Checkpoint file path")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from checkpoint")
    parser.add_argument("--fresh", action="store_true",
                        help="Delete checkpoint, start fresh")
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
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
