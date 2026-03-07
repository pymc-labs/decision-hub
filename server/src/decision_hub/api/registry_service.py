"""Registry business logic — HTTP-specific wrappers and background tasks.

Pure publish-pipeline logic (gauntlet, classification, quarantine, manifest
parsing, eval triggering) lives in ``decision_hub.domain.publish_pipeline``.
This module keeps HTTP-specific helpers (``require_org_membership``) and the
background assessment runner (``run_assessment_background``), plus re-exports
of pipeline functions for backward compatibility with scripts and tests that
import from the old location.
"""

from datetime import UTC
from uuid import UUID

from fastapi import HTTPException
from loguru import logger
from sqlalchemy.engine import Connection

# Re-export pipeline functions for backward compatibility.
# Scripts (backfills, crawler), tests, and modal_app may import these
# from ``decision_hub.api.registry_service``.
# Re-export private helpers used by test patches.
from decision_hub.domain.publish_pipeline import (  # noqa: F401  # noqa: F401
    _build_analyze_fn,
    _build_analyze_prompt_fn,
    _build_review_body_fn,
    _build_review_code_fn,
    classify_skill_category,
    extract_assessment_config,
    extract_runtime_config_dict,
    maybe_trigger_agent_assessment,
    parse_manifest_from_content,
    quarantine_and_log_rejection,
    run_gauntlet_pipeline,
    try_parse_assessment_cases,
)
from decision_hub.infra.database import (
    find_org_by_slug,
    find_org_member,
)
from decision_hub.models import Organization
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
        # Retrieve the publishing user's own API keys for the assessment
        # sandbox.  Keys are stored per-user in user_api_keys (encrypted with
        # the server Fernet key) and belong to the user who triggered the
        # assessment — no platform keys are involved.
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

        # Pop the judge key out of agent_env_vars so it is never exposed
        # inside the sandbox. When the agent key IS the judge key (Claude),
        # we must leave it — the agent needs it to run.
        if judge_key_name != agent_config.key_env_var:
            judge_api_key = agent_env_vars.pop(judge_key_name, "")
        else:
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
                endpoint_url=settings.s3_endpoint_url,
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
