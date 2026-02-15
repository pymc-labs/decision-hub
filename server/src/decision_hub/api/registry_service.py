"""Registry business logic — extracted from registry_routes.py.

Pure functions that handle publishing, validation, gauntlet pipeline,
and eval triggering. Route handlers call these instead of inlining
the logic, making the business rules testable without HTTP mocking.
"""

import tempfile
from datetime import UTC
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from loguru import logger
from sqlalchemy.engine import Connection

from decision_hub.domain.gauntlet import run_static_checks
from decision_hub.domain.publish import build_quarantine_s3_key
from decision_hub.domain.skill_manifest import parse_skill_md
from decision_hub.infra.database import (
    find_org_by_slug,
    find_org_member,
    insert_audit_log,
)
from decision_hub.infra.storage import upload_skill_zip
from decision_hub.models import GauntletReport, Organization
from decision_hub.settings import Settings


def require_org_membership(
    conn: Connection,
    org_slug: str,
    user_id: UUID,
    *,
    admin_only: bool = False,
) -> Organization:
    """Verify org exists and user is a member; return the Organisation.

    Raises 404 if org not found, 403 if not a member (or not admin
    when admin_only=True).
    """
    org = find_org_by_slug(conn, org_slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation not found")

    member = find_org_member(conn, org.id, user_id)
    if member is None:
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this organisation",
        )
    if admin_only and member.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Only org owners and admins can perform this action",
        )
    return org


def parse_manifest_from_content(
    skill_md_content: str,
    file_bytes: bytes,
) -> tuple[dict | None, object | None, tuple, str | None]:
    """Parse SKILL.md and extract runtime config, eval config, eval cases, and allowed_tools.

    Uses a temp file because parse_skill_md expects a file path.
    Returns (runtime_config_dict, eval_config, eval_cases, allowed_tools).

    Raises HTTPException(422) if the manifest is malformed — fail-closed
    to prevent publishing skills with unparseable manifests.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
        tmp.write(skill_md_content)
        tmp_path = Path(tmp.name)

    try:
        manifest = parse_skill_md(tmp_path)
        return (
            extract_runtime_config_dict(manifest),
            extract_assessment_config(manifest),
            try_parse_assessment_cases(file_bytes),
            manifest.allowed_tools,
        )
    except ValueError as exc:
        logger.warning("Manifest parse failed (rejecting publish): {}", exc)
        raise HTTPException(
            status_code=422,
            detail=f"SKILL.md manifest is malformed: {exc}",
        ) from exc
    finally:
        tmp_path.unlink()


def run_gauntlet_pipeline(
    skill_md_content: str,
    lockfile_content: str | None,
    source_files: list[tuple[str, str]],
    skill_name: str,
    description: str,
    skill_md_body: str,
    settings: Settings,
    *,
    allowed_tools: str | None = None,
    is_verified_org: bool = False,
) -> tuple[GauntletReport, list[dict], dict | None]:
    """Run Gauntlet static checks and serialize results for audit logging.

    Returns (report, check_results_dicts, llm_reasoning).
    """
    report = run_static_checks(
        skill_md_content,
        lockfile_content,
        source_files,
        skill_name=skill_name,
        skill_description=description,
        analyze_fn=_build_analyze_fn(settings),
        skill_md_body=skill_md_body,
        allowed_tools=allowed_tools,
        analyze_prompt_fn=_build_analyze_prompt_fn(settings),
        is_verified_org=is_verified_org,
        review_body_fn=_build_review_body_fn(settings),
    )

    check_results_dicts = [
        {
            "check_name": r.check_name,
            "severity": r.severity,
            "message": r.message,
        }
        for r in report.results
    ]

    llm_reasoning = {r.check_name: r.details for r in report.results if r.details is not None} or None

    return report, check_results_dicts, llm_reasoning


def quarantine_rejected_skill(
    conn: Connection,
    s3_client,
    bucket: str,
    file_bytes: bytes,
    *,
    org_slug: str,
    skill_name: str,
    version: str,
    report: GauntletReport,
    check_results: list[dict],
    llm_reasoning: dict | None,
    publisher: str,
) -> None:
    """Upload rejected zip to quarantine, log the rejection, and raise 422.

    Inserts and commits the audit log before uploading to quarantine S3,
    so the rejection record is durable even if the S3 upload fails.
    """
    logger.warning(
        "Quarantining {}/{} v{} — grade={} summary={}",
        org_slug,
        skill_name,
        version,
        report.grade,
        report.summary,
    )
    q_key = build_quarantine_s3_key(org_slug, skill_name, version)

    insert_audit_log(
        conn,
        org_slug=org_slug,
        skill_name=skill_name,
        semver=version,
        grade=report.grade,
        check_results=check_results,
        publisher=publisher,
        version_id=None,
        llm_reasoning=llm_reasoning,
        quarantine_s3_key=q_key,
    )
    # Commit the audit record before raising (or uploading to S3) so it
    # survives the transaction rollback that engine.begin() performs on
    # exception. This ensures rejection forensics are always preserved.
    conn.commit()

    upload_skill_zip(s3_client, bucket, q_key, file_bytes)

    raise HTTPException(
        status_code=422,
        detail=f"Gauntlet checks failed: {report.summary}",
    )


def _build_analyze_fn(settings: Settings):
    """Build a Gemini analyze callback if google_api_key is configured.

    Returns None if no API key is set, which causes the safety scan
    to run in strict regex-only mode.
    """
    if not settings.google_api_key:
        return None

    from decision_hub.infra.gemini import analyze_code_safety, create_gemini_client

    gemini_client = create_gemini_client(settings.google_api_key)

    def analyze_fn(snippets, source_files, skill_name, skill_description):
        return analyze_code_safety(
            gemini_client,
            snippets,
            source_files,
            skill_name,
            skill_description,
            model=settings.gemini_model,
        )

    return analyze_fn


def _build_analyze_prompt_fn(settings: Settings):
    """Build a Gemini prompt analyze callback if google_api_key is configured.

    Returns None if no API key is set, which causes the prompt safety scan
    to run in strict regex-only mode.
    """
    if not settings.google_api_key:
        return None

    from decision_hub.infra.gemini import analyze_prompt_safety, create_gemini_client

    gemini_client = create_gemini_client(settings.google_api_key)

    def analyze_prompt_fn(prompt_hits, skill_name, skill_description):
        return analyze_prompt_safety(
            gemini_client,
            prompt_hits,
            skill_name,
            skill_description,
            model=settings.gemini_model,
        )

    return analyze_prompt_fn


def _build_review_body_fn(settings: Settings):
    """Build a Gemini holistic body review callback if google_api_key is configured.

    Returns None if no API key is set, disabling the holistic body review.
    """
    if not settings.google_api_key:
        return None

    from decision_hub.infra.gemini import create_gemini_client, review_prompt_body_safety

    gemini_client = create_gemini_client(settings.google_api_key)

    def review_body_fn(body, skill_name, skill_description):
        return review_prompt_body_safety(
            gemini_client,
            body,
            skill_name,
            skill_description,
            model=settings.gemini_model,
        )

    return review_body_fn


def classify_skill_category(
    skill_name: str,
    description: str,
    skill_md_body: str,
    settings: Settings,
) -> str:
    """Run LLM classification to assign a category to a skill.

    Returns the subcategory string (e.g. "Backend & APIs"). Falls back
    to DEFAULT_CATEGORY if the LLM is unavailable or returns garbage.
    """
    from dhub_core.taxonomy import DEFAULT_CATEGORY

    if not settings.google_api_key:
        return DEFAULT_CATEGORY

    from decision_hub.domain.classification import build_taxonomy_prompt_fragment, parse_classification_response
    from decision_hub.infra.gemini import classify_skill, create_gemini_client

    try:
        gemini_client = create_gemini_client(settings.google_api_key)
        taxonomy_fragment = build_taxonomy_prompt_fragment()
        raw_response = classify_skill(
            gemini_client,
            skill_name,
            description,
            skill_md_body,
            taxonomy_fragment,
            model=settings.gemini_model,
        )
        result = parse_classification_response(raw_response)
        logger.info(
            "Classified {} as {} (group={}, confidence={:.2f})",
            skill_name,
            result.category,
            result.group,
            result.confidence,
        )
        return result.category
    except Exception:
        logger.opt(exception=True).warning("Skill classification failed for {}, using default", skill_name)
        return DEFAULT_CATEGORY


def extract_runtime_config_dict(manifest) -> dict | None:
    """Extract runtime config as a JSON-compatible dict for database storage."""
    if manifest.runtime is None:
        return None

    runtime_dict = {
        "language": manifest.runtime.language,
        "entrypoint": manifest.runtime.entrypoint,
        "version_hint": manifest.runtime.version_hint,
        "env": list(manifest.runtime.env),
        "capabilities": list(manifest.runtime.capabilities),
        "repair_strategy": manifest.runtime.repair_strategy,
    }

    if manifest.runtime.dependencies:
        runtime_dict["dependencies"] = {
            "system": list(manifest.runtime.dependencies.system),
            "package_manager": manifest.runtime.dependencies.package_manager,
            "packages": list(manifest.runtime.dependencies.packages),
            "lockfile": manifest.runtime.dependencies.lockfile,
        }

    return runtime_dict


def extract_assessment_config(manifest):
    """Extract eval config from manifest (returns None if not present)."""
    return manifest.evals


def try_parse_assessment_cases(file_bytes: bytes):
    """Parse eval cases from zip. Returns empty tuple if no evals/ directory.

    Raises HTTPException(422) if eval files exist but are malformed —
    fail-closed to prevent bypassing the eval pipeline with broken YAML.
    """
    from decision_hub.domain.skill_manifest import parse_eval_cases_from_zip

    try:
        return parse_eval_cases_from_zip(file_bytes)
    except ValueError as exc:
        logger.warning("Eval case parse failed (rejecting publish): {}", exc)
        raise HTTPException(
            status_code=422,
            detail=f"Eval case files are malformed: {exc}",
        ) from exc


def maybe_trigger_agent_assessment(
    eval_config,
    eval_cases: tuple,
    s3_key: str,
    s3_bucket: str,
    version_id,
    org_slug: str,
    skill_name: str,
    settings: Settings,
    user_id,
) -> tuple[str | None, str | None]:
    """Conditionally trigger background agent assessment if config present.

    Creates an eval_run row BEFORE spawning the Modal function, so the
    CLI can immediately start tailing logs.

    Uses a fresh DB connection because the caller's engine.begin()
    transaction is already committed and closed.

    Returns (eval_report_status, eval_run_id) — both None if no assessment config.

    Raises HTTPException(422) if config is declared but no case files found.
    """
    if eval_config and not eval_cases:
        raise HTTPException(
            status_code=422,
            detail="Assessment config declared in manifest but no case files found in evals/",
        )
    if eval_config and eval_cases:
        # Use a fresh connection — the caller's transaction is already closed
        # after the explicit conn.commit() that makes the version row visible.
        # Generate the run ID client-side so the S3 prefix is known before insert.
        from uuid import uuid4

        import modal

        from decision_hub.infra.database import create_engine, insert_eval_run

        run_uuid = uuid4()
        log_s3_prefix = f"eval-logs/{run_uuid}/"

        engine = create_engine(settings.database_url)
        with engine.connect() as eval_conn:
            eval_run = insert_eval_run(
                eval_conn,
                run_id=run_uuid,
                version_id=version_id,
                user_id=user_id,
                agent=eval_config.agent,
                judge_model=eval_config.judge_model,
                total_cases=len(eval_cases),
                log_s3_prefix=log_s3_prefix,
            )
            eval_conn.commit()

        logger.info(
            "Spawning eval task run_id={} agent={} cases={} for {}/{}",
            eval_run.id,
            eval_config.agent,
            len(eval_cases),
            org_slug,
            skill_name,
        )

        # Serialize EvalCase dataclasses to dicts for Modal transport
        cases_dicts = [
            {
                "name": c.name,
                "description": c.description,
                "prompt": c.prompt,
                "judge_criteria": c.judge_criteria,
            }
            for c in eval_cases
        ]

        run_eval = modal.Function.from_name(
            settings.modal_app_name,
            "run_eval_task",
        )
        run_eval.spawn(
            version_id=str(version_id),
            eval_run_id=str(eval_run.id),
            eval_agent=eval_config.agent,
            eval_judge_model=eval_config.judge_model,
            eval_cases_dicts=cases_dicts,
            s3_key=s3_key,
            s3_bucket=s3_bucket,
            org_slug=org_slug,
            skill_name=skill_name,
            user_id=str(user_id),
        )
        return "pending", str(eval_run.id)
    return None, None


def run_assessment_background(
    version_id,
    assessment_config,
    assessment_cases: tuple,
    skill_zip: bytes,
    org_slug: str,
    skill_name: str,
    settings: Settings,
    user_id,
    run_id=None,
):
    """Background task to run agent assessments and store report.

    When run_id is provided, uses the streaming pipeline that writes S3
    log chunks and updates the eval_runs table. Otherwise falls back to
    the original batch pipeline for backward compat.
    """
    from cryptography.fernet import Fernet

    from decision_hub.infra.database import create_engine, get_api_keys_for_eval
    from decision_hub.infra.modal_client import get_agent_config, validate_api_key

    try:
        logger.info("Assessment phase 1: loading API keys for {}/{}", org_slug, skill_name)
        engine = create_engine(settings.database_url)

        # --- Phase 1: read API keys then release the connection ---
        agent_config = get_agent_config(assessment_config.agent)
        required_keys = [agent_config.key_env_var] if agent_config.key_env_var else []
        judge_key_name = "ANTHROPIC_API_KEY"
        if judge_key_name not in required_keys:
            required_keys.append(judge_key_name)
        with engine.connect() as conn:
            encrypted_keys = get_api_keys_for_eval(conn, user_id, required_keys)
            conn.commit()

        logger.info("Got {} API keys: {}", len(encrypted_keys), list(encrypted_keys.keys()))

        fernet = Fernet(settings.fernet_key.encode())
        agent_env_vars = {name: fernet.decrypt(value).decode() for name, value in encrypted_keys.items()}

        for key_name, key_value in agent_env_vars.items():
            validate_api_key(key_name, key_value)
        logger.info("API key validation passed")

        judge_api_key = agent_env_vars.get(judge_key_name, "")

        # --- Phase 2: run pipeline ---
        if run_id is not None:
            # Streaming pipeline with S3 persistence
            from decision_hub.domain.evals import run_streaming_eval
            from decision_hub.infra.storage import create_s3_client

            s3_client = create_s3_client(
                region=settings.aws_region,
                access_key_id=settings.aws_access_key_id,
                secret_access_key=settings.aws_secret_access_key,
            )
            log_s3_prefix = f"eval-logs/{run_id}/"

            logger.info(
                "Assessment phase 2: running streaming pipeline ({} cases) for {}/{}",
                len(assessment_cases),
                org_slug,
                skill_name,
            )
            run_streaming_eval(
                run_id=run_id,
                version_id=version_id,
                skill_zip=skill_zip,
                eval_config=assessment_config,
                eval_cases=assessment_cases,
                agent_env_vars=agent_env_vars,
                org_slug=org_slug,
                skill_name=skill_name,
                judge_api_key=judge_api_key,
                database_url=settings.database_url,
                s3_client=s3_client,
                s3_bucket=settings.s3_bucket,
                log_s3_prefix=log_s3_prefix,
                sandbox_memory_mb=settings.sandbox_memory_mb,
                sandbox_timeout_seconds=settings.sandbox_timeout_seconds,
                sandbox_cpu=settings.sandbox_cpu,
            )
            logger.info("Streaming pipeline completed for {}/{}", org_slug, skill_name)
        else:
            # Original batch pipeline (backward compat)
            from decision_hub.domain.evals import run_eval_pipeline

            logger.info(
                "Assessment phase 2: running batch pipeline ({} cases) for {}/{}",
                len(assessment_cases),
                org_slug,
                skill_name,
            )
            case_results, passed, total, total_duration_ms = run_eval_pipeline(
                skill_zip=skill_zip,
                eval_config=assessment_config,
                eval_cases=assessment_cases,
                agent_env_vars=agent_env_vars,
                org_slug=org_slug,
                skill_name=skill_name,
                judge_api_key=judge_api_key,
                sandbox_memory_mb=settings.sandbox_memory_mb,
                sandbox_timeout_seconds=settings.sandbox_timeout_seconds,
                sandbox_cpu=settings.sandbox_cpu,
            )

            all_passed = all(r["verdict"] == "pass" for r in case_results)
            status = "completed" if all_passed else "failed"

            logger.info(
                "Assessment phase 3: storing results — {}/{} passed, status={}",
                passed,
                total,
                status,
            )
            with engine.connect() as conn:
                from decision_hub.infra.database import insert_eval_report

                insert_eval_report(
                    conn,
                    version_id=version_id,
                    agent=assessment_config.agent,
                    judge_model=assessment_config.judge_model,
                    case_results=case_results,
                    passed=passed,
                    total=total,
                    total_duration_ms=total_duration_ms,
                    status=status,
                )
                conn.commit()

            logger.info("Assessment done — {}/{} passed in {}ms", passed, total, total_duration_ms)

    except Exception as e:
        logger.error("Agent assessment failed for version {}: {}", version_id, e)

        # Update run row if using streaming pipeline
        if run_id is not None:
            try:
                from datetime import datetime

                from decision_hub.infra.database import create_engine as _ce
                from decision_hub.infra.database import update_eval_run_status

                err_engine = _ce(settings.database_url)
                with err_engine.connect() as err_conn:
                    update_eval_run_status(
                        err_conn,
                        run_id,
                        status="failed",
                        error_message=str(e),
                        completed_at=datetime.now(UTC),
                    )
                    err_conn.commit()
            except Exception as inner:
                logger.error("Failed to update run {}: {}", run_id, inner)

        # INSERT an error report
        try:
            from decision_hub.infra.database import create_engine as _create_engine
            from decision_hub.infra.database import insert_eval_report

            err_engine = _create_engine(settings.database_url)
            with err_engine.connect() as err_conn:
                insert_eval_report(
                    err_conn,
                    version_id=version_id,
                    agent=assessment_config.agent,
                    judge_model=assessment_config.judge_model,
                    case_results=[],
                    passed=0,
                    total=len(assessment_cases),
                    total_duration_ms=0,
                    status="failed",
                    error_message=str(e),
                )
                err_conn.commit()
        except Exception as inner:
            logger.error(
                "Failed to store error report for version {}: {}",
                version_id,
                inner,
            )
