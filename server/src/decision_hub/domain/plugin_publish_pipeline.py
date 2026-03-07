"""Plugin publish pipeline.

Mirrors the skill publish pipeline but handles multi-component plugin
packages containing skills, hooks, agents, and commands. Plugins are
extracted, gauntlet-checked with plugin-specific safety scans, and
published to a separate plugins table.
"""

from __future__ import annotations

import dataclasses
import io
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from decision_hub.domain.gauntlet import run_plugin_static_checks
from decision_hub.domain.publish import build_plugin_quarantine_s3_key, build_plugin_s3_key
from decision_hub.domain.publish_pipeline import (
    GauntletRejectionError,
    VersionConflictError,
    classify_skill_category,
)
from decision_hub.infra.database import (
    deprecate_skills_by_repo_url,
    find_plugin,
    find_plugin_version,
    insert_audit_log,
    insert_plugin,
    insert_plugin_version,
    update_plugin_category,
    update_plugin_component_counts,
    update_plugin_description,
)
from decision_hub.infra.storage import upload_skill_zip
from decision_hub.settings import Settings
from dhub_core.plugin_manifest import PluginManifest, parse_plugin_manifest

# Reuse extraction limits from publish.py
_MAX_FILE_SIZE = 10 * 1024 * 1024
_MAX_TOTAL_EXTRACTED = 100 * 1024 * 1024
_MAX_ZIP_ENTRIES = 500

_SECURITY_SCAN_EXTENSIONS = frozenset(
    {
        ".py",
        ".sh",
        ".bash",
        ".zsh",
        ".js",
        ".ts",
        ".tsx",
        ".cs",
        ".json",
        ".yml",
        ".yaml",
        ".md",
        ".txt",
    }
)
_SECURITY_SCAN_NAMES = frozenset({"Makefile", "Dockerfile", ".env", "LICENSE"})


def _is_scannable_file(basename: str) -> bool:
    if basename in _SECURITY_SCAN_NAMES:
        return True
    _, ext = os.path.splitext(basename)
    return ext in _SECURITY_SCAN_EXTENSIONS


@dataclass(frozen=True)
class PluginPublishResult:
    """Outcome of a successful plugin publish."""

    plugin_id: UUID
    version_id: UUID
    version: str
    s3_key: str
    checksum: str
    eval_status: str
    deprecated_skills_count: int


def extract_plugin_for_evaluation(
    zip_bytes: bytes,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Extract scannable files from a plugin zip archive.

    Returns (source_files, unscanned_files) tuples. Unlike skill extraction,
    there is no required SKILL.md -- plugins use plugin.json instead.
    """
    source_files: list[tuple[str, str]] = []
    unscanned_files: list[str] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        entries = zf.infolist()
        if len(entries) > _MAX_ZIP_ENTRIES:
            raise ValueError(f"Zip contains {len(entries)} entries, exceeding limit of {_MAX_ZIP_ENTRIES}")

        total_uncompressed = sum(info.file_size for info in entries)
        if total_uncompressed > _MAX_TOTAL_EXTRACTED:
            raise ValueError(
                f"Total uncompressed size ({total_uncompressed // (1024 * 1024)} MB) "
                f"exceeds limit of {_MAX_TOTAL_EXTRACTED // (1024 * 1024)} MB"
            )

        for name in zf.namelist():
            if name.endswith("/"):
                continue
            if zf.getinfo(name).file_size > _MAX_FILE_SIZE:
                raise ValueError(f"File '{name}' exceeds max size of {_MAX_FILE_SIZE // (1024 * 1024)} MB")

            basename = name.rsplit("/", 1)[-1] if "/" in name else name
            if _is_scannable_file(basename):
                try:
                    source_files.append((name, zf.read(name).decode()))
                except UnicodeDecodeError:
                    unscanned_files.append(name)
            else:
                unscanned_files.append(name)

    source_files.sort(key=lambda fc: len(fc[1]))
    return source_files, unscanned_files


def extract_plugin_to_dir(zip_bytes: bytes, dest: str) -> None:
    """Extract a plugin zip to a directory for manifest parsing."""
    from dhub_core.ziputil import validate_zip_entries

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # Validate: no path traversal, entry count, and total size limits
        validate_zip_entries(zf, dest)

        entries = zf.infolist()
        if len(entries) > _MAX_ZIP_ENTRIES:
            raise ValueError(f"Zip contains {len(entries)} entries, exceeding limit of {_MAX_ZIP_ENTRIES}")
        total_uncompressed = sum(info.file_size for info in entries)
        if total_uncompressed > _MAX_TOTAL_EXTRACTED:
            raise ValueError(
                f"Total uncompressed size ({total_uncompressed // (1024 * 1024)} MB) "
                f"exceeds limit of {_MAX_TOTAL_EXTRACTED // (1024 * 1024)} MB"
            )

        zf.extractall(dest)


def execute_plugin_publish(
    *,
    conn: Connection,
    s3_client: Any,
    settings: Settings,
    org_id: UUID,
    org_slug: str,
    plugin_name: str,
    version: str,
    checksum: str,
    file_bytes: bytes,
    publisher: str,
    source_repo_url: str | None = None,
    manifest_path: str | None = None,
    auto_bump_version: bool = False,
    visibility: str | None = None,
) -> PluginPublishResult:
    """Run the full publish pipeline for a plugin version.

    Args:
        conn: Active DB connection (caller manages the transaction).
        s3_client: Boto3 S3 client.
        settings: Application settings.
        org_id: UUID of the owning organization.
        org_slug: Organization slug.
        plugin_name: Validated plugin name.
        version: Semver version string.
        checksum: SHA-256 hex digest of file_bytes.
        file_bytes: Raw zip bytes.
        publisher: Attribution string.
        source_repo_url: GitHub repo URL.
        manifest_path: Relative path to plugin dir.
        auto_bump_version: Auto-bump patch if version exists.
        visibility: "public" or "org". Defaults to "public" if None.

    Returns:
        PluginPublishResult with IDs, version, S3 key, and deprecation count.

    Raises:
        ValueError: If zip extraction or manifest parsing fails.
        GauntletRejectionError: If the gauntlet grades the plugin F.
        VersionConflictError: If version exists and auto_bump is False.
    """
    # 1. Extract zip to temp dir for manifest parsing
    with tempfile.TemporaryDirectory() as tmpdir:
        extract_plugin_to_dir(file_bytes, tmpdir)
        manifest: PluginManifest = parse_plugin_manifest(Path(tmpdir))

    # 2. Extract scannable files for gauntlet
    source_files, unscanned_files = extract_plugin_for_evaluation(file_bytes)

    # Build hooks list for plugin-specific checks
    hooks = [(h.event, h.command) for h in manifest.hooks]

    # 3. Run plugin gauntlet (includes standard + plugin-specific checks)
    # Use a synthetic SKILL.md-like content for the manifest schema check
    synthetic_skill_md = f"---\nname: {manifest.name}\ndescription: {manifest.description}\n---\n{manifest.description}"

    report = run_plugin_static_checks(
        source_files=source_files,
        hooks=hooks,
        skill_md_content=synthetic_skill_md,
        skill_name=manifest.name,
        skill_description=manifest.description,
        skill_md_body=manifest.description,
        unscanned_files=unscanned_files,
    )
    # 4. Quarantine if rejected
    if not report.passed:
        quarantine_s3_key = build_plugin_quarantine_s3_key(org_slug, plugin_name, version)
        try:
            upload_skill_zip(s3_client, settings.s3_bucket, quarantine_s3_key, file_bytes)
        except Exception:
            logger.opt(exception=True).warning(
                "Failed to upload quarantined plugin {}/{} v{}",
                org_slug,
                plugin_name,
                version,
            )
        check_results_dicts = [
            {"check_name": r.check_name, "severity": r.severity, "message": r.message} for r in report.results
        ]
        insert_audit_log(
            conn,
            org_slug=org_slug,
            skill_name=plugin_name,
            semver=version,
            grade=report.grade,
            check_results=check_results_dicts,
            publisher=publisher,
            quarantine_s3_key=quarantine_s3_key,
            plugin_name=plugin_name,
        )
        conn.commit()
        raise GauntletRejectionError(report.summary)

    # 5. Classify category
    category = classify_skill_category(manifest.name, manifest.description, manifest.description, settings)

    # 6. Upsert plugin record
    plugin = find_plugin(conn, org_id, plugin_name)
    if plugin is None:
        plugin = insert_plugin(
            conn,
            org_id,
            plugin_name,
            description=manifest.description,
            category=category,
            author_name=manifest.author_name,
            homepage=manifest.homepage,
            license=manifest.license,
            keywords=manifest.keywords,
            platforms=manifest.platforms,
            skill_count=len(manifest.skills),
            hook_count=len(manifest.hooks),
            agent_count=len(manifest.agents),
            command_count=len(manifest.commands),
            visibility=visibility or "public",
            source_repo_url=source_repo_url,
            manifest_path=manifest_path,
        )
    else:
        update_plugin_description(conn, plugin.id, manifest.description)
        update_plugin_category(conn, plugin.id, category)
        update_plugin_component_counts(
            conn,
            plugin.id,
            skill_count=len(manifest.skills),
            hook_count=len(manifest.hooks),
            agent_count=len(manifest.agents),
            command_count=len(manifest.commands),
        )

    # 6b. Generate embedding (fail-open)
    from decision_hub.infra.embeddings import generate_and_store_plugin_embedding

    generate_and_store_plugin_embedding(
        conn, plugin.id, manifest.name, org_slug, category, manifest.description, settings
    )

    # 7. Handle duplicate version
    if find_plugin_version(conn, plugin.id, version) is not None:
        if auto_bump_version:
            from decision_hub.domain.repo_utils import bump_version

            version = bump_version(version)
        else:
            raise VersionConflictError(org_slug, plugin_name, version)

    # 8. Record the version and audit log, then commit before S3 upload
    s3_key = build_plugin_s3_key(org_slug, plugin_name, version)

    # Serialize manifest for storage
    manifest_dict = dataclasses.asdict(manifest)
    # Convert tuples to lists for JSON serialization
    for key in ("skills", "hooks", "keywords", "platforms", "agents", "commands"):
        if key in manifest_dict and isinstance(manifest_dict[key], tuple):
            manifest_dict[key] = list(manifest_dict[key])

    check_results_dicts = [
        {"check_name": r.check_name, "severity": r.severity, "message": r.message} for r in report.results
    ]

    try:
        version_record = insert_plugin_version(
            conn,
            plugin_id=plugin.id,
            semver=version,
            s3_key=s3_key,
            checksum=checksum,
            plugin_manifest=manifest_dict,
            published_by=publisher,
            eval_status=report.grade,
            gauntlet_summary=report.gauntlet_summary,
        )
    except IntegrityError:
        raise VersionConflictError(org_slug, plugin_name, version) from None

    # 9. Audit log
    insert_audit_log(
        conn,
        org_slug=org_slug,
        skill_name=plugin_name,
        semver=version,
        grade=report.grade,
        check_results=check_results_dicts,
        publisher=publisher,
        plugin_version_id=version_record.id,
        plugin_id=plugin.id,
        plugin_name=plugin_name,
    )

    # 10. Commit DB, then upload to S3.
    # NOTE: Not atomic — if S3 upload fails, the DB version record persists
    # pointing to a missing S3 key (ghost version). This matches the skill
    # publish pipeline behavior. A cleanup job or retry mechanism would be
    # needed for full atomicity.
    conn.commit()

    try:
        upload_skill_zip(s3_client, settings.s3_bucket, s3_key, file_bytes)
    except Exception:
        logger.opt(exception=True).error(
            "S3 upload failed for plugin {}/{} v{}",
            org_slug,
            plugin_name,
            version,
        )
        raise

    # 11. Auto-deprecate matching skills from the same repo
    deprecated_count = 0
    if source_repo_url:
        deprecated_count = deprecate_skills_by_repo_url(
            conn,
            source_repo_url,
            plugin.id,
            f"Superseded by plugin {org_slug}/{plugin_name}. Install with: dhub install {org_slug}/{plugin_name}",
            org_id=org_id,
        )
        if deprecated_count:
            conn.commit()

    return PluginPublishResult(
        plugin_id=plugin.id,
        version_id=version_record.id,
        version=version,
        s3_key=s3_key,
        checksum=checksum,
        eval_status=report.grade,
        deprecated_skills_count=deprecated_count,
    )
