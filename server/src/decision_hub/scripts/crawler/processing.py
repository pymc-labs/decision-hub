"""Modal container processing logic for the GitHub skills crawler.

Each Modal container processes exactly one repo: clone, discover skills,
run gauntlet, publish or quarantine. No shared state between containers.

Skills within a repo are processed in parallel using ThreadPoolExecutor.
The gauntlet pipeline is I/O-bound (HTTP calls to Gemini), so threading
gives a large speedup for repos with many skills. DB connections are held
only for short read/write phases — never during the slow Gemini calls.
"""

import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
from loguru import logger

from decision_hub.domain.orgs import METADATA_CACHE_TTL
from decision_hub.domain.publish import (
    build_quarantine_s3_key,
    build_s3_key,
    extract_for_evaluation,
    validate_skill_name,
)
from decision_hub.domain.repo_utils import (
    bump_version,
    clone_repo,
    create_zip,
    discover_skills,
)
from decision_hub.domain.skill_manifest import extract_body, extract_description
from dhub_core.validation import _SLUG_PATTERN

CLONE_TIMEOUT_SECONDS = 120
BOT_GITHUB_ID = "0"
BOT_USERNAME = "dhub-crawler"


@dataclass(frozen=True)
class _SkillPrep:
    """Intermediate data between prepare and finalize phases.

    Carries everything needed by the gauntlet pipeline (phase 2) and
    the DB write phase (phase 3) so the connection can be released
    between phases.
    """

    skill_id: UUID
    name: str
    description: str
    version: str
    checksum: str
    zip_data: bytes
    skill_md_content: str
    skill_md_body: str
    desc: str
    source_files: list[tuple[str, str]]
    lockfile_content: str | None
    unscanned_files: list[str]
    allowed_tools: str | None


def fetch_owner_metadata(
    login: str,
    owner_type: str,
    token: str | None = None,
) -> dict:
    """Fetch public metadata for a GitHub user/org. Works inside Modal containers.

    Returns a dict with keys: avatar_url, email, description, blog.
    On error returns an empty dict.
    """
    headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    endpoint = (
        f"https://api.github.com/orgs/{login}"
        if owner_type == "Organization"
        else f"https://api.github.com/users/{login}"
    )
    try:
        resp = httpx.get(endpoint, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            # GitHub users have "bio" instead of "description"
            description = data.get("description") if owner_type == "Organization" else data.get("bio")
            return {
                "avatar_url": data.get("avatar_url") or None,
                "email": data.get("email") or None,
                "description": description or None,
                "blog": data.get("blog") or None,
            }
    except httpx.HTTPError:
        return {}
    return {}


def _is_repo_archived(full_name: str, token: str | None) -> bool:
    """Check if a GitHub repo is archived via the REST API."""
    headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.get(f"https://api.github.com/repos/{full_name}", headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("archived", False)
    except httpx.HTTPError:
        pass
    return False


def process_repo_on_modal(
    repo_dict: dict,
    bot_user_id_str: str,
    github_token: str | None,
    set_tracker: bool = True,
    force: bool = False,
) -> dict:
    """Process a single repo inside a Modal container.

    Clones the repo, discovers SKILL.md files, runs the gauntlet pipeline,
    and publishes or quarantines each skill.
    """
    import subprocess

    from decision_hub.infra.database import (
        create_engine,
        find_org_by_slug,
        find_org_member,
        insert_org_member,
        insert_organization,
        update_org_github_metadata,
        upsert_user,
    )
    from decision_hub.infra.storage import (
        create_s3_client,
    )
    from decision_hub.settings import create_settings

    result: dict = {
        "repo": repo_dict["full_name"],
        "status": "ok",
        "commit_sha": None,
        "skills_published": 0,
        "skills_skipped": 0,
        "skills_failed": 0,
        "skills_quarantined": 0,
        "org_created": False,
        "metadata_synced": False,
        "error": None,
    }

    try:
        settings = create_settings()
        engine = create_engine(settings.database_url)
        s3_client = create_s3_client(
            region=settings.aws_region,
            access_key_id=settings.aws_access_key_id,
            secret_access_key=settings.aws_secret_access_key,
            endpoint_url=settings.s3_endpoint_url,
        )

        slug = repo_dict["owner_login"].lower()
        if not _SLUG_PATTERN.match(slug):
            result["status"] = "skipped"
            result["error"] = f"Invalid org slug: {slug}"
            return result

        # Skip archived repos. Most discovery strategies filter archived
        # repos during discovery, but code search (size/path) doesn't have
        # the archived flag — only call the API when we don't already know.
        is_archived = repo_dict.get("archived")
        if is_archived is None:
            is_archived = _is_repo_archived(repo_dict["full_name"], github_token)
        if is_archived:
            result["status"] = "skipped"
            result["error"] = "Repo is archived"
            logger.info("Skipping archived repo {}", repo_dict["full_name"])
            return result

        bot_user_id = UUID(bot_user_id_str)

        # Ensure org exists and bot is a member (short-lived transaction)
        with engine.connect() as conn:
            upsert_user(conn, github_id=BOT_GITHUB_ID, username=BOT_USERNAME)

            org = find_org_by_slug(conn, slug)
            if org is None:
                is_personal = repo_dict["owner_type"] == "User"
                org = insert_organization(conn, slug, bot_user_id, is_personal=is_personal)
                insert_org_member(conn, org.id, bot_user_id, "owner")
                result["org_created"] = True
            else:
                existing = find_org_member(conn, org.id, bot_user_id)
                if existing is None:
                    insert_org_member(conn, org.id, bot_user_id, "admin")

            conn.commit()

        # Sync GitHub metadata outside the DB transaction to avoid
        # holding a connection during the HTTP call (up to 15s timeout).
        # Best-effort: failures must not block skill publishing.
        try:
            needs_sync = org.github_synced_at is None or (datetime.now(UTC) - org.github_synced_at) > METADATA_CACHE_TTL
            if needs_sync:
                meta = fetch_owner_metadata(
                    repo_dict["owner_login"],
                    repo_dict["owner_type"],
                    github_token,
                )
                if meta:
                    with engine.connect() as conn:
                        update_org_github_metadata(
                            conn,
                            org.id,
                            avatar_url=meta.get("avatar_url"),
                            email=meta.get("email"),
                            description=meta.get("description"),
                            blog=meta.get("blog"),
                        )
                        conn.commit()
                    result["metadata_synced"] = True
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to sync GitHub metadata for {}; continuing with skill publishing",
                repo_dict["owner_login"],
            )

        # Clone and discover
        repo_root = clone_repo(
            repo_dict["clone_url"],
            github_token=github_token,
            timeout=CLONE_TIMEOUT_SECONDS,
        )
        tmp_dir = repo_root.parent

        # Capture commit SHA for checkpoint change-detection
        sha_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if sha_proc.returncode == 0:
            result["commit_sha"] = sha_proc.stdout.strip()

        try:
            skill_dirs = discover_skills(repo_root)
            if not skill_dirs:
                result["status"] = "no_skills"
                return result

            source_repo_url = f"https://github.com/{repo_dict['full_name']}"
            max_workers = settings.crawler_parallel_skills

            def _process_skill(skill_dir: Path) -> str:
                """Process a single skill in three phases.

                Phase 1 (prepare): short DB connection for reads + skill upsert.
                Phase 2 (gauntlet): Gemini API calls with NO DB connection held.
                Phase 3 (finalize): short DB connection for writes + S3 upload.

                Returns a status string: "published", "skipped",
                "quarantined", or "failed".
                """
                try:
                    return _publish_one_skill(
                        engine,
                        s3_client,
                        settings,
                        org,
                        skill_dir,
                        source_repo_url=source_repo_url,
                        bot_user_id=bot_user_id,
                        set_tracker=set_tracker,
                        force=force,
                    )
                except Exception:
                    logger.opt(exception=True).warning(
                        "Failed to process skill dir {}",
                        skill_dir.name,
                    )
                    return "failed"

            counts: Counter[str] = Counter()
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_process_skill, sd): sd for sd in skill_dirs}
                for i, future in enumerate(as_completed(futures), 1):
                    status = future.result()
                    counts[status] += 1
                    if i % 10 == 0 or i == len(skill_dirs):
                        logger.info(
                            "Skill progress {}/{}: pub={} skip={} quar={} fail={}",
                            i,
                            len(skill_dirs),
                            counts["published"],
                            counts["skipped"],
                            counts["quarantined"],
                            counts["failed"],
                        )

            result["skills_published"] = counts["published"]
            result["skills_skipped"] = counts["skipped"]
            result["skills_quarantined"] = counts["quarantined"]
            result["skills_failed"] = counts["failed"]
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


def _publish_one_skill(
    engine,
    s3_client,
    settings,
    org,
    skill_dir: Path,
    *,
    source_repo_url: str | None = None,
    bot_user_id: UUID | None = None,
    set_tracker: bool = False,
    force: bool = False,
) -> str:
    """Parse, gauntlet-check, and publish a single skill.

    Uses three short-lived DB connections so the connection is NOT held
    during the I/O-bound gauntlet pipeline (Gemini API calls, 5-10s each).

    Returns a status string: "published", "skipped", "quarantined", or "failed".
    """
    # Phase 1: prepare — DB reads + skill upsert (short connection)
    # Note: in force mode, _prepare_skill may delete the existing version.
    # This commit makes the deletion visible before _finalize_skill re-creates
    # it, so there's a brief window where the version doesn't exist. This is
    # acceptable because force mode is only used in manual crawler runs.
    with engine.connect() as conn:
        prep = _prepare_skill(conn, settings, org, skill_dir, source_repo_url=source_repo_url, force=force)
        conn.commit()

    if isinstance(prep, str):
        return prep  # "skipped" or "failed"

    # Phase 2: gauntlet pipeline — NO DB connection held
    from decision_hub.api.registry_service import classify_skill_category, run_gauntlet_pipeline

    report, check_results, llm_reasoning = run_gauntlet_pipeline(
        prep.skill_md_content,
        prep.lockfile_content,
        prep.source_files,
        prep.name,
        prep.desc,
        prep.skill_md_body,
        settings,
        allowed_tools=prep.allowed_tools,
        unscanned_files=prep.unscanned_files,
    )

    # Category classification only for passing skills (also hits Gemini API)
    category = ""
    if report.passed:
        category = classify_skill_category(prep.name, prep.desc, prep.skill_md_body, settings)

    # Phase 3: write results — DB writes + S3 upload (short connection)
    with engine.connect() as conn:
        status = _finalize_skill(
            conn,
            s3_client,
            settings,
            org,
            prep,
            report,
            check_results,
            llm_reasoning,
            category,
            bot_user_id=bot_user_id,
            set_tracker=set_tracker,
            source_repo_url=source_repo_url,
        )
        conn.commit()
        return status


def _prepare_skill(
    conn,
    settings,
    org,
    skill_dir: Path,
    *,
    source_repo_url: str | None = None,
    force: bool = False,
) -> str | _SkillPrep:
    """Phase 1: read from disk + DB, return prep data or early-exit status."""
    from decision_hub.infra.database import (
        find_skill,
        find_version,
        insert_skill,
        resolve_latest_version,
        update_skill_description,
        update_skill_source_repo_url,
    )
    from decision_hub.infra.storage import compute_checksum
    from dhub_core.manifest import parse_skill_md

    manifest = parse_skill_md(skill_dir / "SKILL.md")
    name = manifest.name
    description = manifest.description
    validate_skill_name(name)

    zip_data = create_zip(skill_dir)
    checksum = compute_checksum(zip_data)

    # Upsert skill record
    skill = find_skill(conn, org.id, name)
    if skill is None:
        skill = insert_skill(conn, org.id, name, description, source_repo_url=source_repo_url)
    else:
        update_skill_description(conn, skill.id, description)
        if source_repo_url and skill.source_repo_url != source_repo_url:
            update_skill_source_repo_url(conn, skill.id, source_repo_url)

    # Determine version (auto-bump patch or start at 0.1.0)
    latest = resolve_latest_version(conn, org.slug, name)
    if latest is not None:
        if latest.checksum == checksum and not force:
            return "skipped"  # identical content
        version = bump_version(latest.semver) if latest.checksum != checksum else latest.semver
    else:
        version = "0.1.0"

    if find_version(conn, skill.id, version) is not None:
        if not force:
            return "skipped"
        # Force mode: delete the existing version so it can be re-created
        from decision_hub.infra.database import delete_version

        delete_version(conn, skill.id, version)

    # Extract content for gauntlet evaluation
    skill_md_content = (skill_dir / "SKILL.md").read_text()
    skill_md_body = extract_body(skill_md_content)
    desc = extract_description(skill_md_content)
    try:
        _, source_files, lockfile_content, unscanned_files = extract_for_evaluation(zip_data)
    except ValueError as exc:
        logger.warning("Skipping {}/{}: extraction failed: {}", org.slug, name, exc)
        return "failed"

    return _SkillPrep(
        skill_id=skill.id,
        name=name,
        description=description,
        version=version,
        checksum=checksum,
        zip_data=zip_data,
        skill_md_content=skill_md_content,
        skill_md_body=skill_md_body,
        desc=desc,
        source_files=source_files,
        lockfile_content=lockfile_content,
        unscanned_files=unscanned_files,
        allowed_tools=manifest.allowed_tools,
    )


def _finalize_skill(
    conn,
    s3_client,
    settings,
    org,
    prep: _SkillPrep,
    report,
    check_results,
    llm_reasoning,
    category: str,
    *,
    bot_user_id: UUID | None = None,
    set_tracker: bool = False,
    source_repo_url: str | None = None,
) -> str:
    """Phase 3: write gauntlet results to DB + S3. Returns final status."""
    from decision_hub.infra.database import (
        insert_audit_log,
        insert_version,
        update_skill_category,
    )
    from decision_hub.infra.storage import upload_skill_zip

    if not report.passed:
        # Grade F — quarantine
        q_key = build_quarantine_s3_key(org.slug, prep.name, prep.version)
        insert_audit_log(
            conn,
            org_slug=org.slug,
            skill_name=prep.name,
            semver=prep.version,
            grade=report.grade,
            check_results=check_results,
            publisher=BOT_USERNAME,
            version_id=None,
            llm_reasoning=llm_reasoning,
            quarantine_s3_key=q_key,
        )
        upload_skill_zip(s3_client, settings.s3_bucket, q_key, prep.zip_data)
        return "quarantined"

    # Grade A/B/C — publish
    update_skill_category(conn, prep.skill_id, category)

    # Generate embedding (fail-open: never blocks publish)
    from decision_hub.infra.embeddings import generate_and_store_skill_embedding

    generate_and_store_skill_embedding(conn, prep.skill_id, prep.name, org.slug, category, prep.description, settings)

    s3_key = build_s3_key(org.slug, prep.name, prep.version)
    upload_skill_zip(s3_client, settings.s3_bucket, s3_key, prep.zip_data)
    version_record = insert_version(
        conn,
        skill_id=prep.skill_id,
        semver=prep.version,
        s3_key=s3_key,
        checksum=prep.checksum,
        runtime_config=None,
        published_by=BOT_USERNAME,
        eval_status=report.grade,
        gauntlet_summary=report.gauntlet_summary,
    )
    insert_audit_log(
        conn,
        org_slug=org.slug,
        skill_name=prep.name,
        semver=prep.version,
        grade=report.grade,
        check_results=check_results,
        publisher=BOT_USERNAME,
        version_id=version_record.id,
        llm_reasoning=llm_reasoning,
        quarantine_s3_key=None,
    )

    if set_tracker and source_repo_url and bot_user_id is not None:
        from decision_hub.infra.database import upsert_skill_tracker

        upsert_skill_tracker(conn, bot_user_id, org.slug, source_repo_url)

    return "published"
